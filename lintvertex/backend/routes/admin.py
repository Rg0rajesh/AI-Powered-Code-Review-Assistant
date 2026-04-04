"""
LintVertex - Hardened Admin Routes
────────────────────────────────────────────────────────────────
Security layers:
  1. Dedicated /api/admin/login  — admin-only endpoint
  2. Separate short-lived JWT signed with ADMIN_JWT_SECRET
  3. IP binding on every request via ip_hash in token
  4. JTI-based token revocation (logout invalidates server-side)
  5. Brute-force lockout: 5 failures → 30-min block
  6. Rate limit: 3 attempts per 60s per IP
  7. All admin API calls written to audit log
  8. X-Admin-Confirm header required for destructive operations
  9. Security response headers on every response
 10. No admin session shared with regular user tokens
"""
import hashlib
import hmac
import time
import logging
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify

from utils.security import (
    require_admin, require_auth,
    admin_login_rate_limit, login_rate_limit, rate_limit,
    generate_admin_token, revoke_admin_token,
    verify_password, hash_password, validate_admin_password,
    record_failed_admin_login, record_failed_user_login,
    clear_login_attempts, get_admin_audit_log,
    _get_ip, _log_admin_intrusion, _audit_admin_action,
    add_security_headers,
)
from config import Config
import services.supabase_client as db

admin_bp = Blueprint("admin", __name__)
logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════
# ADMIN AUTHENTICATION
# ════════════════════════════════════════════════════════════════

@admin_bp.route("/api/admin/login", methods=["POST"])
@admin_login_rate_limit
def admin_login():
    """
    Dedicated admin login.
    Issues a short-lived admin JWT (2h) signed with ADMIN_JWT_SECRET.
    IP-bound — token is revoked if used from a different IP.
    """
    ip = _get_ip()
    data = request.get_json() or {}
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    # Generic error message — never reveal WHY it failed
    FAIL_MSG = "Invalid admin credentials"

    if not email or not password:
        return jsonify({"error": FAIL_MSG}), 401

    # Fetch user
    user = db.get_user_by_email(email)

    # Constant-time failure (prevent user enumeration timing)
    if not user or user.get("role") != "admin":
        # Still run bcrypt to prevent timing attack
        bcrypt_dummy = "$2b$12$aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        verify_password("dummy", bcrypt_dummy)
        record_failed_admin_login(ip)
        _log_admin_intrusion(ip, "invalid_email_or_not_admin", "/api/admin/login")
        logger.warning(f"SECURITY: Admin login failed (user not found or not admin): email={email} ip={ip}")
        return jsonify({"error": FAIL_MSG}), 401

    if not verify_password(password, user["password_hash"]):
        record_failed_admin_login(ip)
        _log_admin_intrusion(ip, "wrong_password", "/api/admin/login")
        logger.warning(f"SECURITY: Admin login failed (wrong password): email={email} ip={ip}")
        return jsonify({"error": FAIL_MSG}), 401

    # ✅ Successful login
    clear_login_attempts(ip, is_admin=True)
    token, jti = generate_admin_token(user["id"], email, ip)

    _audit_admin_action(user["id"], email, ip, "ADMIN_LOGIN_SUCCESS")
    db.log_activity(user["id"], f"admin_login from {ip}")

    return jsonify({
        "message": "Admin authenticated",
        "token": token,
        "token_type": "admin",
        "expires_in_hours": Config.ADMIN_TOKEN_EXPIRY_HOURS,
        "jti": jti,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "email": user["email"],
            "role": "admin",
        },
    }), 200


@admin_bp.route("/api/admin/logout", methods=["POST"])
@require_admin
def admin_logout():
    """Revoke the current admin token server-side."""
    jti = request.user.get("jti", "")
    if jti:
        revoke_admin_token(jti)
    _audit_admin_action(
        request.user.get("user_id"), request.user.get("email"),
        _get_ip(), "ADMIN_LOGOUT"
    )
    return jsonify({"message": "Admin session revoked"}), 200


@admin_bp.route("/api/admin/session", methods=["GET"])
@require_admin
def admin_session_info():
    """Return info about the current admin session."""
    import jwt as pyjwt
    token = request.headers.get("Authorization", "")[7:]
    try:
        from utils.security import decode_admin_token
        payload = decode_admin_token(token)
        exp = payload.get("exp", 0)
        remaining = max(0, exp - int(time.time()))
        return jsonify({
            "user_id": request.user.get("user_id"),
            "email": request.user.get("email"),
            "ip": _get_ip(),
            "token_type": "admin",
            "expires_in_seconds": remaining,
            "jti": request.user.get("jti"),
        }), 200
    except Exception:
        return jsonify({"error": "Could not decode session"}), 400


# ════════════════════════════════════════════════════════════════
# PLATFORM STATS
# ════════════════════════════════════════════════════════════════

@admin_bp.route("/api/admin/stats", methods=["GET"])
@require_admin
def admin_stats():
    stats = db.get_platform_stats()
    return jsonify(stats), 200


# ════════════════════════════════════════════════════════════════
# USER MANAGEMENT
# ════════════════════════════════════════════════════════════════

@admin_bp.route("/api/admin/users", methods=["GET"])
@require_admin
@rate_limit(30, 60, "admin_users_list")
def list_users():
    result = db.get_all_users()
    return jsonify({"users": result.data or []}), 200


@admin_bp.route("/api/admin/users/<user_id>", methods=["PUT"])
@require_admin
def update_user_admin(user_id):
    """
    Update user role/details.
    Role escalation to 'admin' requires X-Admin-Confirm header.
    """
    data = request.get_json() or {}
    allowed = {k: v for k, v in data.items() if k in ("role", "username", "email")}
    if not allowed:
        return jsonify({"error": "No valid fields to update"}), 400

    # Escalating to admin requires re-auth confirm header
    if allowed.get("role") == "admin":
        confirm = request.headers.get("X-Admin-Confirm", "")
        if not confirm:
            return jsonify({
                "error": "Escalating a user to admin requires X-Admin-Confirm header.",
                "hint": "Pass HMAC-SHA256 of 'PUT:/api/admin/users/<id>' signed with your admin password."
            }), 403
        # Verify the confirmation HMAC
        admin_user = db.get_user_by_id(request.user["user_id"])
        if not admin_user:
            return jsonify({"error": "Admin user not found"}), 404
        expected = hmac.new(
            admin_user["password_hash"][:32].encode(),
            f"PUT:/api/admin/users/{user_id}".encode(),
            hashlib.sha256
        ).hexdigest()[:16]
        if not hmac.compare_digest(confirm[:16], expected):
            _log_admin_intrusion(_get_ip(), "bad_role_escalation_confirm", request.path)
            return jsonify({"error": "Invalid confirmation code for role escalation"}), 403

    db.update_user(user_id, allowed)
    _audit_admin_action(
        request.user["user_id"], request.user["email"],
        _get_ip(), f"UPDATE_USER:{user_id} fields={list(allowed.keys())}"
    )
    return jsonify({"message": "User updated", "updated_fields": list(allowed.keys())}), 200


@admin_bp.route("/api/admin/users/<user_id>", methods=["DELETE"])
@require_admin
def delete_user_admin(user_id):
    """
    Delete a user. Requires X-Admin-Confirm header.
    Cannot delete your own admin account.
    """
    if user_id == request.user.get("user_id"):
        return jsonify({"error": "Cannot delete your own admin account"}), 403

    confirm = request.headers.get("X-Admin-Confirm", "")
    if not confirm:
        return jsonify({
            "error": "User deletion requires X-Admin-Confirm header",
            "hint": "Include X-Admin-Confirm: <HMAC> to proceed with this destructive action."
        }), 403

    db.get_admin_client().table("users").delete().eq("id", user_id).execute()
    _audit_admin_action(
        request.user["user_id"], request.user["email"],
        _get_ip(), f"DELETE_USER:{user_id}"
    )
    return jsonify({"message": f"User {user_id} deleted"}), 200


# ════════════════════════════════════════════════════════════════
# ANALYSIS MANAGEMENT
# ════════════════════════════════════════════════════════════════

@admin_bp.route("/api/admin/analyses", methods=["GET"])
@require_admin
@rate_limit(30, 60, "admin_analyses_list")
def list_analyses():
    limit = min(int(request.args.get("limit", 50)), 100)
    result = db.get_all_analyses(limit)
    analyses = []
    for a in (result.data or []):
        user_info = a.get("users") or {}
        analyses.append({
            "id": a["id"],
            "language": a["language_detected"],
            "grade": a["ml_prediction"],
            "syntax_errors": a["syntax_errors"],
            "created_at": a["created_at"],
            "user": user_info.get("username", "Unknown"),
        })
    return jsonify({"analyses": analyses}), 200


# ════════════════════════════════════════════════════════════════
# ROOM MANAGEMENT
# ════════════════════════════════════════════════════════════════

@admin_bp.route("/api/admin/rooms", methods=["GET"])
@require_admin
def list_rooms():
    result = db.get_all_rooms()
    rooms = []
    for r in (result.data or []):
        user_info = r.get("users") or {}
        rooms.append({
            "id": r["id"],
            "name": r["room_name"],
            "key": r["room_key"],
            "created_by": user_info.get("username", "Unknown"),
            "created_at": r["created_at"],
        })
    return jsonify({"rooms": rooms}), 200


@admin_bp.route("/api/admin/rooms/<room_id>", methods=["DELETE"])
@require_admin
def delete_room_admin(room_id):
    confirm = request.headers.get("X-Admin-Confirm", "")
    if not confirm:
        return jsonify({"error": "Room deletion requires X-Admin-Confirm header"}), 403

    db.get_admin_client().table("rooms").delete().eq("id", room_id).execute()
    _audit_admin_action(
        request.user["user_id"], request.user["email"],
        _get_ip(), f"DELETE_ROOM:{room_id}"
    )
    return jsonify({"message": "Room deleted"}), 200


# ════════════════════════════════════════════════════════════════
# FEEDBACK MANAGEMENT
# ════════════════════════════════════════════════════════════════

@admin_bp.route("/api/admin/feedback", methods=["GET"])
@require_admin
def list_feedback():
    email = request.args.get("email")
    if email:
        # Use !inner to filter the main table based on joined table column
        result = db.get_admin_client().table("feedback").select(
            "*, users!inner(username, email)"
        ).eq("users.email", email).order("created_at", desc=True).execute()
    else:
        result = db.get_all_feedback()
    
    feedback = []
    for f in (result.data or []):
        user_info = f.get("users") or {}
        # If filtering by email, users might be null if no match in joined table
        if email and not user_info:
            continue
        feedback.append({
            "id": f["id"],
            "rating": f["rating"],
            "text": f["feedback_text"],
            "user": user_info.get("username", "Unknown"),
            "email": user_info.get("email", ""),
            "created_at": f["created_at"],
        })
    return jsonify({"feedback": feedback}), 200


# ════════════════════════════════════════════════════════════════
# ACTIVITY & SECURITY AUDIT LOGS
# ════════════════════════════════════════════════════════════════

@admin_bp.route("/api/admin/logs", methods=["GET"])
@require_admin
def activity_logs():
    limit = min(int(request.args.get("limit", 100)), 500)
    result = db.get_activity_logs(limit)
    logs = []
    for log in (result.data or []):
        user_info = log.get("users") or {}
        logs.append({
            "id": log["id"],
            "action": log["action"],
            "user": user_info.get("username", "System"),
            "timestamp": log["timestamp"],
        })
    return jsonify({"logs": logs}), 200


@admin_bp.route("/api/admin/audit", methods=["GET"])
@require_admin
def security_audit_log():
    """In-memory admin security audit trail (last 500 entries)."""
    audit = get_admin_audit_log()
    return jsonify({
        "count": len(audit),
        "audit_log": audit,
    }), 200


@admin_bp.route("/api/admin/security-summary", methods=["GET"])
@require_admin
def security_summary():
    """High-level security status for the admin dashboard."""
    from utils.security import _store
    now = time.time()

    # Count active lockouts
    active_lockouts = [
        {"key": k, "unlocks_in": int(v - now)}
        for k, v in _store.lockouts.items()
        if v > now
    ]

    # Count revoked tokens
    revoked_count = len(_store.revoked_jtis)

    # Intrusion attempts from audit log
    audit = get_admin_audit_log()
    intrusions = [e for e in audit if e.get("type") == "intrusion"]

    return jsonify({
        "active_lockouts": len(active_lockouts),
        "lockout_details": active_lockouts,
        "revoked_admin_tokens": revoked_count,
        "intrusion_attempts_in_memory": len(intrusions),
        "recent_intrusions": intrusions[:10],
        "admin_token_expiry_hours": Config.ADMIN_TOKEN_EXPIRY_HOURS,
        "server_time_utc": datetime.now(timezone.utc).isoformat(),
    }), 200
