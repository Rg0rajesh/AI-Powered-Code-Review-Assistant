"""
LintVertex - Email Routes
  POST /api/email/otp/request   — Request OTP for password change
  POST /api/email/otp/verify    — Verify OTP and change password
  GET  /api/email/otp/status    — Check pending OTP status (for countdown)
  POST /api/admin/email/broadcast — Admin sends email to all / specific users
  POST /api/admin/email/feedback-reply — Admin replies to a feedback entry
"""
import logging
from flask import Blueprint, request, jsonify
from utils.security import (
    require_auth, require_admin, rate_limit,
    hash_password, verify_password, validate_password,
)
from services.otp_service import generate_otp, verify_otp, get_otp_status, invalidate_otp, OTPRateLimited
from services.email_service import (
    send_password_otp_email,
    send_feature_announcement,
    send_policy_notice,
    send_custom_email,
    send_feedback_reply,
    test_smtp_connection,
)
import services.supabase_client as db

email_bp   = Blueprint("email",       __name__)
admin_email_bp = Blueprint("admin_email", __name__)
logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════
# OTP — PASSWORD CHANGE
# ════════════════════════════════════════════════════════════════

@email_bp.route("/api/email/otp/request", methods=["POST"])
@require_auth
@rate_limit(3, 120, "otp_request")
def request_otp():
    """
    Step 1 of password change:
    Verify current password, then send OTP to user's email.
    """
    data = request.get_json() or {}
    current_password = data.get("current_password", "")

    if not current_password:
        return jsonify({"error": "Current password is required"}), 400

    user = db.get_user_by_id(request.user["user_id"])
    if not user:
        return jsonify({"error": "User not found"}), 404

    # Verify current password before sending OTP
    if not verify_password(current_password, user["password_hash"]):
        return jsonify({"error": "Current password is incorrect"}), 401

    # Generate OTP
    try:
        code = generate_otp(user["email"], user["id"], ip_address=request.remote_addr)
    except OTPRateLimited as e:
        return jsonify({"error": f"Too many requests. Please try again in {e.retry_after}s"}), 429
    except Exception as e:
        logger.error(f"OTP generation error: {e}")
        return jsonify({"error": "Failed to generate verification code."}), 500

    # Send email (non-blocking)
    try:
        send_password_otp_email(user["email"], user["username"], code)
    except Exception as e:
        logger.error(f"Failed to send OTP email: {e}")
        invalidate_otp(user["email"])
        return jsonify({"error": "Failed to send verification email. Please try again."}), 500

    db.log_activity(user["id"], "otp_requested:password_change")

    return jsonify({
        "message": f"Verification code sent to {_mask_email(user['email'])}",
        "email_hint": _mask_email(user["email"]),
        "expires_in_seconds": 600,
    }), 200


@email_bp.route("/api/email/otp/verify", methods=["POST"])
@require_auth
@rate_limit(5, 60, "otp_verify")
def verify_otp_and_change_password():
    """
    Step 2 of password change:
    Verify OTP + set new password.
    """
    data = request.get_json() or {}
    otp_code     = data.get("otp_code", "").strip()
    new_password = data.get("new_password", "")
    confirm_new  = data.get("confirm_new_password", "")

    if not otp_code:
        return jsonify({"error": "Verification code is required"}), 400

    if not new_password:
        return jsonify({"error": "New password is required"}), 400

    if new_password != confirm_new:
        return jsonify({"error": "Passwords do not match"}), 400

    # Validate new password strength
    valid, err = validate_password(new_password)
    if not valid:
        return jsonify({"error": err}), 400

    user = db.get_user_by_id(request.user["user_id"])
    if not user:
        return jsonify({"error": "User not found"}), 404

    # Verify OTP
    try:
        from services.otp_service import OTPExpired, OTPAlreadyUsed, OTPInvalid
        verify_otp(user["email"], otp_code)
    except OTPExpired:
        return jsonify({"error": "Verification code has expired."}), 400
    except OTPAlreadyUsed:
        return jsonify({"error": "Verification code already used."}), 400
    except OTPInvalid as e:
        return jsonify({"error": f"Invalid verification code. {e.attempts_left} attempts remaining."}), 400
    except Exception as e:
        logger.error(f"OTP verification error: {e}")
        return jsonify({"error": "Verification failed."}), 500

    # Ensure new password is different from current
    if verify_password(new_password, user["password_hash"]):
        return jsonify({"error": "New password must be different from current password"}), 400

    # Update password
    new_hash = hash_password(new_password)
    db.update_user(user["id"], {"password_hash": new_hash})
    db.log_activity(user["id"], "password_changed")

    logger.info(f"Password changed for user {user['email']}")
    return jsonify({"message": "Password changed successfully! Please log in again."}), 200


@email_bp.route("/api/email/otp/status", methods=["GET"])
@require_auth
def otp_status():
    """Get status of pending OTP for the current user (for frontend countdown)."""
    user = db.get_user_by_id(request.user["user_id"])
    if not user:
        return jsonify({"error": "User not found"}), 404

    status = get_otp_status(user["email"])
    if status["has_pending"]:
        status["email_hint"] = _mask_email(user["email"])
    return jsonify(status), 200


# ════════════════════════════════════════════════════════════════
# ADMIN EMAIL BROADCAST
# ════════════════════════════════════════════════════════════════

@admin_email_bp.route("/api/admin/email/broadcast", methods=["POST"])
@require_admin
def admin_broadcast():
    """
    Admin sends an email to one user, a list, or ALL users.

    Body:
    {
      "recipient_type": "all" | "single" | "list",
      "recipient_email": "user@x.com",          // for single
      "recipient_ids":   ["uuid1", "uuid2"],     // for list
      "email_type": "feature" | "policy" | "custom",
      "subject": "...",
      "headline": "...",
      "body_html": "<p>...</p>",
      "features": [{"icon":"🔥","title":"...","desc":"..."}],  // for feature type
      "effective_date": "2025-01-01",                          // for policy type
      "cta_text": "...",
      "cta_url": "...",
      "tag_label": "...",
    }
    """
    data = request.get_json() or {}

    recipient_type = data.get("recipient_type", "all")
    email_type     = data.get("email_type", "custom")
    subject        = data.get("subject", "").strip()
    headline       = data.get("headline", "").strip()
    body_html      = data.get("body_html", "").strip()

    if not subject or not headline or not body_html:
        return jsonify({"error": "subject, headline, and body_html are required"}), 400

    # ── Determine recipients ────────────────────────────────────
    recipients = []

    if recipient_type == "all":
        result = db.get_all_users()
        recipients = result.data or []

    elif recipient_type == "single":
        email = data.get("recipient_email", "").strip().lower()
        if not email:
            return jsonify({"error": "recipient_email required for single send"}), 400
        user = db.get_user_by_email(email)
        if not user:
            return jsonify({"error": f"User not found: {email}"}), 404
        recipients = [user]

    elif recipient_type == "list":
        ids = data.get("recipient_ids", [])
        if not ids:
            return jsonify({"error": "recipient_ids required for list send"}), 400
        for uid in ids:
            user = db.get_user_by_id(uid)
            if user:
                recipients.append(user)

    else:
        return jsonify({"error": "Invalid recipient_type"}), 400

    if not recipients:
        return jsonify({"error": "No recipients found"}), 404

    # ── Send emails ─────────────────────────────────────────────
    sent_count = 0
    failed = []

    for user in recipients:
        to_email = user.get("email")
        username = user.get("username", "Developer")
        if not to_email:
            continue

        try:
            if email_type == "feature":
                send_feature_announcement(
                    to_email, username, subject, headline, body_html,
                    features=data.get("features"),
                    cta_text=data.get("cta_text", "Explore Now"),
                    cta_url=data.get("cta_url", ""),
                )
            elif email_type == "policy":
                send_policy_notice(
                    to_email, username, subject, headline, body_html,
                    effective_date=data.get("effective_date", ""),
                    tag_label=data.get("tag_label", "Policy Update"),
                )
            else:  # custom
                send_custom_email(
                    to_email, username, subject, headline, body_html,
                    tag_label=data.get("tag_label", "Message"),
                    cta_text=data.get("cta_text", ""),
                    cta_url=data.get("cta_url", ""),
                )
            sent_count += 1
        except Exception as e:
            logger.error(f"Broadcast failed for {to_email}: {e}")
            failed.append(to_email)

    # ── Audit ───────────────────────────────────────────────────
    db.log_activity(
        request.user["user_id"],
        f"admin_email_broadcast: type={email_type} recipients={len(recipients)} subject={subject[:50]}"
    )

    return jsonify({
        "message": f"Email queued for {sent_count} recipient(s)",
        "sent_count": sent_count,
        "failed_count": len(failed),
        "failed_emails": failed,
    }), 200


@admin_email_bp.route("/api/admin/email/feedback-reply", methods=["POST"])
@require_admin
def admin_feedback_reply():
    """
    Admin replies to a specific feedback submission.
    Body: { "feedback_id": "uuid", "reply": "<p>...</p>" }
    """
    data = request.get_json() or {}
    feedback_id = data.get("feedback_id", "").strip()
    reply_text  = data.get("reply", "").strip()

    if not feedback_id or not reply_text:
        return jsonify({"error": "feedback_id and reply are required"}), 400

    # Fetch feedback + user info
    fb_result = db.get_admin_client().table("feedback").select(
        "*, users(username, email)"
    ).eq("id", feedback_id).execute()

    if not fb_result.data:
        return jsonify({"error": "Feedback not found"}), 404

    fb = fb_result.data[0]
    user_info = fb.get("users") or {}
    to_email  = user_info.get("email")
    username  = user_info.get("username", "Developer")

    if not to_email:
        return jsonify({"error": "Could not find user email for this feedback"}), 404

    try:
        send_feedback_reply(
            to_email=to_email,
            username=username,
            original_feedback=fb.get("feedback_text", ""),
            original_rating=fb.get("rating", 0),
            admin_reply=reply_text,
        )
    except Exception as e:
        logger.error(f"Feedback reply email failed: {e}")
        return jsonify({"error": "Failed to send email"}), 500

    db.log_activity(
        request.user["user_id"],
        f"admin_feedback_reply: feedback_id={feedback_id} to={to_email}"
    )

    return jsonify({
        "message": f"Reply sent to {_mask_email(to_email)}",
    }), 200


@admin_email_bp.route("/api/admin/email/test-smtp", methods=["POST"])
@require_admin
def admin_test_smtp():
    """Verify SMTP configuration works."""
    success, message = test_smtp_connection()
    if success:
        return jsonify({"message": message}), 200
    return jsonify({"error": message}), 400


# ── Helper ───────────────────────────────────────────────────────────────────

def _mask_email(email: str) -> str:
    """Mask email for display: john@example.com → j***@example.com"""
    try:
        local, domain = email.split("@", 1)
        masked = local[0] + "***" if len(local) > 1 else "***"
        return f"{masked}@{domain}"
    except Exception:
        return "***@***.***"
