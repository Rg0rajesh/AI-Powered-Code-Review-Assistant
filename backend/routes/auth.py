"""
LintVertex - Auth Routes
User registration, login, JWT session management
"""
import base64
from flask import Blueprint, request, jsonify
from utils.security import (
    hash_password, verify_password, generate_token,
    validate_email, validate_password, validate_username, validate_image,
    login_rate_limit, record_failed_user_login, clear_login_attempts, _get_ip,
)
import services.supabase_client as db

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/api/auth/signup", methods=["POST"])
def signup():
    """Register a new user + send welcome email"""
    if request.content_type and "multipart/form-data" in request.content_type:
        data = request.form.to_dict()
        profile_image_file = request.files.get("profile_image")
    else:
        data = request.get_json() or {}
        profile_image_file = None

    username = data.get("username", "").strip()
    email    = data.get("email", "").strip().lower()
    address  = data.get("address", "").strip()
    password = data.get("password", "")
    confirm  = data.get("confirm_password", "")

    errors = {}
    valid_user, user_err = validate_username(username)
    if not valid_user: errors["username"] = user_err
    if not validate_email(email): errors["email"] = "Invalid email address"
    if not address: errors["address"] = "Address is required"
    valid_pass, pass_err = validate_password(password)
    if not valid_pass: errors["password"] = pass_err
    if password != confirm: errors["confirm_password"] = "Passwords do not match"
    if errors:
        return jsonify({"error": "Validation failed", "details": errors}), 400

    existing = db.get_user_by_email(email)
    if existing:
        return jsonify({"error": "Email already registered"}), 409

    profile_image_data = None
    if profile_image_file and profile_image_file.filename:
        valid_img, img_err = validate_image(profile_image_file)
        if not valid_img:
            return jsonify({"error": img_err}), 400
        img_bytes = profile_image_file.read()
        profile_image_data = f"data:{profile_image_file.content_type};base64,{base64.b64encode(img_bytes).decode()}"

    user_data = {
        "username": username,
        "email": email,
        "address": address,
        "password_hash": hash_password(password),
        "profile_image": profile_image_data,
        "role": "user",
    }

    result = db.create_user(user_data)
    if not result.data:
        return jsonify({"error": "Failed to create account"}), 500

    created_user = result.data[0]
    db.log_activity(created_user["id"], "user_registered")

    # ── Send welcome email (non-blocking) ────────────────────────
    try:
        from services.email_service import send_welcome_email
        send_welcome_email(email, username)
    except Exception:
        pass  # Never block signup on email failure

    token = generate_token(created_user["id"], email, "user")
    return jsonify({
        "message": "Account created successfully",
        "token": token,
        "user": {
            "id": created_user["id"],
            "username": username,
            "email": email,
            "role": "user",
            "profile_image": profile_image_data,
        }
    }), 201


@auth_bp.route("/api/auth/login", methods=["POST"])
@login_rate_limit
def login():
    """Authenticate user and return JWT"""
    ip = _get_ip()
    data = request.get_json() or {}
    email    = data.get("email", "").strip().lower()
    password = data.get("password", "")

    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400

    user = db.get_user_by_email(email)
    if not user or not verify_password(password, user["password_hash"]):
        record_failed_user_login(ip)
        return jsonify({"error": "Invalid email or password"}), 401

    clear_login_attempts(ip, is_admin=False)
    db.log_activity(user["id"], "user_login")
    token = generate_token(user["id"], email, user.get("role", "user"))

    return jsonify({
        "message": "Login successful",
        "token": token,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "email": user["email"],
            "role": user.get("role", "user"),
            "profile_image": user.get("profile_image"),
            "address": user.get("address"),
        }
    }), 200


@auth_bp.route("/api/auth/me", methods=["GET"])
def get_me():
    """Get current user profile from token"""
    from utils.security import decode_token
    import jwt as pyjwt

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return jsonify({"error": "Authorization required"}), 401
    try:
        payload = decode_token(auth_header[7:])
        user = db.get_user_by_id(payload["user_id"])
        if not user:
            return jsonify({"error": "User not found"}), 404
        return jsonify({
            "id": user["id"],
            "username": user["username"],
            "email": user["email"],
            "role": user.get("role", "user"),
            "address": user.get("address"),
            "profile_image": user.get("profile_image"),
            "created_at": user.get("created_at"),
        })
    except pyjwt.ExpiredSignatureError:
        return jsonify({"error": "Token expired"}), 401
    except Exception:
        return jsonify({"error": "Invalid token"}), 401

# ════════════════════════════════════════════════════════════════
# FORGOT PASSWORD — DB-BACKED OTP FLOW
# All OTP records and reset tokens stored in Supabase.
# Survives server restarts. Works with multiple Gunicorn workers.
# ════════════════════════════════════════════════════════════════

@auth_bp.route("/api/auth/forgot-password", methods=["POST"])
@login_rate_limit
def forgot_password():
    """
    Step 1 — Request OTP.
    Generates OTP, stores hash+expiry in password_reset_otps table,
    sends email. Returns same message whether email exists or not
    (prevents enumeration).
    """
    from services.otp_service import generate_otp, OTPRateLimited
    from services.email_service import send_otp_email

    data  = request.get_json() or {}
    email = data.get("email", "").strip().lower()

    if not email or not validate_email(email):
        return jsonify({"error": "Valid email address required"}), 400

    SAFE_MSG = "If an account with that email exists, you will receive an OTP shortly."
    ip       = _get_ip()

    user = db.get_user_by_email(email)
    if not user:
        import time; time.sleep(0.3)   # prevent timing attack
        return jsonify({"message": SAFE_MSG}), 200

    try:
        otp = generate_otp(email, user_id=user["id"], ip_address=ip)
    except OTPRateLimited as e:
        return jsonify({
            "error":       "Too many OTP requests. Please wait before trying again.",
            "retry_after": e.retry_after,
        }), 429

    sent = send_otp_email(email, user["username"], otp)
    if not sent:
        import logging as _log
        _log.getLogger(__name__).info(f"[DEV] OTP for {email}: {otp}")

    db.log_activity(user["id"], f"password_reset_requested from {ip}")
    return jsonify({"message": SAFE_MSG}), 200


@auth_bp.route("/api/auth/verify-otp", methods=["POST"])
def verify_otp():
    """
    Step 2 — Verify the 6-digit OTP against the DB record.
    On success: creates a reset token, stores its hash in
    password_reset_tokens, returns plain token to client.
    """
    from services.otp_service import (
        verify_otp as _verify_otp,
        create_reset_token,
        OTPExpired, OTPInvalid, OTPAlreadyUsed,
    )

    data      = request.get_json() or {}
    email     = data.get("email", "").strip().lower()
    otp_input = data.get("otp", "").strip()
    ip        = _get_ip()

    if not email or not otp_input:
        return jsonify({"error": "Email and OTP are required"}), 400

    if not otp_input.isdigit() or len(otp_input) != 6:
        return jsonify({"error": "OTP must be a 6-digit number"}), 400

    # Verify OTP against DB
    try:
        _verify_otp(email, otp_input)
    except OTPExpired:
        return jsonify({"error": "OTP has expired. Please request a new one.", "code": "expired"}), 400
    except OTPAlreadyUsed:
        return jsonify({"error": "This OTP has already been used.", "code": "used"}), 400
    except OTPInvalid as e:
        msg = ("Too many incorrect attempts. Please request a new OTP."
               if e.attempts_left <= 0
               else f"Incorrect OTP. {e.attempts_left} attempt{'s' if e.attempts_left != 1 else ''} remaining.")
        return jsonify({"error": msg, "attempts_left": e.attempts_left, "code": "invalid"}), 400

    # OTP passed — fetch user and create DB-backed reset token
    user = db.get_user_by_email(email)
    if not user:
        return jsonify({"error": "Account not found"}), 404

    reset_token = create_reset_token(email, user_id=user["id"], ip_address=ip)

    db.log_activity(user["id"], f"otp_verified from {ip}")

    return jsonify({
        "message":    "OTP verified",
        "reset_token": reset_token,
        "expires_in":  600,
    }), 200


@auth_bp.route("/api/auth/reset-password", methods=["POST"])
def reset_password():
    """
    Step 3 — Set new password using the reset_token from Step 2.
    Verifies token against DB hash, updates password_hash in users table,
    marks token as used, deletes OTP record, sends confirmation email.
    """
    from services.otp_service import verify_reset_token, consume_reset_token, invalidate_otp
    from services.email_service import send_password_changed_email

    data             = request.get_json() or {}
    reset_token      = data.get("reset_token", "").strip()
    new_password     = data.get("new_password", "")
    confirm_password = data.get("confirm_password", "")
    ip               = _get_ip()

    if not reset_token:
        return jsonify({"error": "Reset token is required"}), 400

    # ── Validate reset token against DB ──────────────────────
    try:
        token_record = verify_reset_token(reset_token)
    except ValueError as e:
        code = str(e)
        msgs = {
            "invalid_token": "Invalid or expired reset token. Please start over.",
            "token_used":    "This reset link has already been used. Please request a new OTP.",
            "token_expired": "Reset session expired. Please request a new OTP.",
        }
        return jsonify({"error": msgs.get(code, "Invalid token."), "code": code}), 400

    email   = token_record["email"]
    user_id = token_record["user_id"]

    # ── Validate new password ─────────────────────────────────
    valid, err = validate_password(new_password)
    if not valid:
        return jsonify({"error": err}), 400

    if new_password != confirm_password:
        return jsonify({"error": "Passwords do not match"}), 400

    # ── Fetch user ────────────────────────────────────────────
    user = db.get_user_by_id(user_id)
    if not user:
        return jsonify({"error": "Account not found"}), 404

    # Prevent reuse of the same password
    if verify_password(new_password, user["password_hash"]):
        return jsonify({"error": "New password must be different from your current password"}), 400

    # ── Update password in Supabase users table ───────────────
    new_hash = hash_password(new_password)
    db.update_user(user_id, {"password_hash": new_hash})

    # ── Mark reset token as used in DB ───────────────────────
    consume_reset_token(reset_token)

    # ── Delete OTP record from DB ─────────────────────────────
    invalidate_otp(email)

    # ── Send confirmation email ───────────────────────────────
    send_password_changed_email(email, user["username"])

    # ── Activity log ──────────────────────────────────────────
    db.log_activity(user_id, f"password_reset_completed from {ip}")

    return jsonify({"message": "Password reset successfully. You can now log in."}), 200


@auth_bp.route("/api/auth/otp-status", methods=["POST"])
def otp_status():
    """Non-sensitive OTP status for frontend countdown display."""
    from services.otp_service import get_otp_status
    data  = request.get_json() or {}
    email = data.get("email", "").strip().lower()
    if not email:
        return jsonify({"error": "Email required"}), 400
    return jsonify(get_otp_status(email)), 200