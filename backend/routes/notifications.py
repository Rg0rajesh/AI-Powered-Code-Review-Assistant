"""
LintVertex - Notification Routes

User endpoints:
  GET  /api/notifications          — fetch user's notifications
  GET  /api/notifications/count    — unread count only (lightweight poll)
  POST /api/notifications/read/<id> — mark one as read
  POST /api/notifications/read-all  — mark all as read
  DELETE /api/notifications/<id>    — delete own notification

Admin endpoints:
  GET  /api/admin/notifications              — list all notifications
  POST /api/admin/notifications/send         — send to one user / all users
  DELETE /api/admin/notifications/<id>       — delete any notification
"""
import logging
from datetime import datetime, timezone, timedelta
from flask import Blueprint, request, jsonify
from utils.security import require_auth, require_admin, _get_ip
import services.supabase_client as db

notif_bp       = Blueprint("notifications",       __name__)
admin_notif_bp = Blueprint("admin_notifications", __name__)
logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# USER ENDPOINTS
# ══════════════════════════════════════════════════════════════

@notif_bp.route("/api/notifications", methods=["GET"])
@require_auth
def get_notifications():
    """Fetch all notifications for the current user."""
    user_id = request.user["user_id"]
    limit   = min(int(request.args.get("limit", 30)), 100)
    notifs  = db.get_user_notifications(user_id, limit)

    return jsonify({
        "notifications": notifs,
        "unread_count": sum(1 for n in notifs if not n.get("is_read")),
        "total": len(notifs),
    }), 200


@notif_bp.route("/api/notifications/count", methods=["GET"])
@require_auth
def get_unread_count():
    """Lightweight endpoint — just the unread count for polling."""
    user_id = request.user["user_id"]
    count   = db.get_unread_count(user_id)
    return jsonify({"unread_count": count}), 200


@notif_bp.route("/api/notifications/read/<notification_id>", methods=["POST"])
@require_auth
def mark_read(notification_id):
    """Mark a single notification as read."""
    user_id = request.user["user_id"]
    db.mark_notification_read(notification_id, user_id)
    return jsonify({"message": "Marked as read"}), 200


@notif_bp.route("/api/notifications/read-all", methods=["POST"])
@require_auth
def mark_all_read():
    """Mark all notifications as read for the current user."""
    user_id = request.user["user_id"]
    db.mark_all_read(user_id)
    return jsonify({"message": "All notifications marked as read"}), 200


@notif_bp.route("/api/notifications/<notification_id>", methods=["DELETE"])
@require_auth
def delete_own_notification(notification_id):
    """User deletes their own personal notification."""
    user_id = request.user["user_id"]
    db.get_admin_client().table("notifications").delete()\
        .eq("id", notification_id).eq("user_id", user_id).execute()
    return jsonify({"message": "Notification deleted"}), 200


# ══════════════════════════════════════════════════════════════
# ADMIN ENDPOINTS
# ══════════════════════════════════════════════════════════════

@admin_notif_bp.route("/api/admin/notifications", methods=["GET"])
@require_admin
def admin_list_notifications():
    """List all notifications with stats."""
    limit  = min(int(request.args.get("limit", 100)), 500)
    notifs = db.get_all_notifications_admin(limit)
    return jsonify({"notifications": notifs, "count": len(notifs)}), 200


@admin_notif_bp.route("/api/admin/notifications/send", methods=["POST"])
@require_admin
def admin_send_notification():
    """
    Admin sends a notification to one user, all users, or a role group.
    """
    try:
        data           = request.get_json() or {}
        recipient_type = data.get("recipient_type", "all")
        notif_type     = data.get("type", "announcement")
        title          = data.get("title", "").strip()
        message        = data.get("message", "").strip()
        icon           = data.get("icon", _type_icon(notif_type))
        action_url     = data.get("action_url", "")
        action_label   = data.get("action_label", "")
        expires_hours  = data.get("expires_hours")

        if not title or not message:
            return jsonify({"error": "title and message are required"}), 400

        expires_at = None
        if expires_hours:
            expires_at = (datetime.now(timezone.utc) + timedelta(hours=int(expires_hours))).isoformat()

        admin_id = request.user["user_id"]
        sent_count = 0

        base = {
            "type":         notif_type,
            "title":        title,
            "message":      message,
            "icon":         icon,
            "action_url":   action_url,
            "action_label": action_label,
            "created_by":   admin_id,
            "expires_at":   expires_at,
        }

        if recipient_type == "all":
            # One global notification row
            res = db.create_global_notification(base.copy())
            if hasattr(res, 'error') and res.error:
                return jsonify({"error": f"DB Error (Global): {res.error}"}), 500
                
            total = db.get_all_users()
            sent_count = len(total.data or [])

        elif recipient_type == "single":
            uid_or_email = data.get("recipient_id", "").strip()
            if not uid_or_email:
                return jsonify({"error": "recipient_id required for single send"}), 400
            
            target_uid = uid_or_email
            if "@" in uid_or_email:
                user = db.get_user_by_email(uid_or_email)
                if not user:
                    return jsonify({"error": f"User with email {uid_or_email} not found"}), 404
                target_uid = user["id"]
                
            row = {**base, "user_id": target_uid, "is_global": False}
            res = db.create_notification(row)
            if hasattr(res, 'error') and res.error:
                return jsonify({"error": f"DB Error (Single): {res.error}"}), 500
            sent_count = 1

        elif recipient_type in ("role_user", "role_admin"):
            role = "admin" if recipient_type == "role_admin" else "user"
            users = db.get_all_users()
            for u in (users.data or []):
                if u.get("role") == role:
                    res = db.create_notification({**base, "user_id": u["id"], "is_global": False})
                    if hasattr(res, 'error') and res.error:
                        return jsonify({"error": f"DB Error (Role): {res.error}"}), 500
                    sent_count += 1
        else:
            return jsonify({"error": "Invalid recipient_type"}), 400

        db.log_activity(admin_id, f"admin_notification_sent: type={notif_type} to={recipient_type} title={title[:40]}")

        return jsonify({
            "message":    f"Notification sent to {sent_count} user(s)",
            "sent_count": sent_count,
        }), 201

    except Exception as e:
        logger.error(f"ADMIN NOTIF SEND FAILED: {e}")
        return jsonify({"error": f"Server crash: {str(e)}"}), 500


@admin_notif_bp.route("/api/admin/notifications/<notification_id>", methods=["DELETE"])
@require_admin
def admin_delete_notification(notification_id):
    """Admin deletes any notification."""
    db.delete_notification(notification_id, request.user["user_id"])
    db.log_activity(request.user["user_id"], f"admin_notification_deleted:{notification_id}")
    return jsonify({"message": "Notification deleted"}), 200


# ══════════════════════════════════════════════════════════════
# AUTO-NOTIFICATION HELPERS (called from other routes)
# ══════════════════════════════════════════════════════════════

def notify_terms_updated(version: str, summary: str, admin_id: str):
    """Called when admin publishes new T&C — notifies all users."""
    try:
        db.create_global_notification({
            "type":         "terms",
            "title":        f"Terms & Conditions Updated — v{version}",
            "message":      summary or "Our Terms and Conditions have been updated. Please review and accept the new terms.",
            "icon":         "📋",
            "action_url":   "/terms.html",
            "action_label": "Review & Accept",
            "created_by":   admin_id,
        })
        logger.info(f"Auto-notification: T&C v{version} published")
    except Exception as e:
        logger.error(f"Failed to create T&C notification: {e}")


def notify_feedback_replied(user_id: str, admin_id: str, rating: int):
    """Called when admin replies to feedback — notifies that user."""
    try:
        db.create_notification({
            "user_id":      user_id,
            "type":         "feedback_reply",
            "title":        "The LintVertex team replied to your feedback",
            "message":      f"We've responded to your {'⭐'*rating} feedback. Check your email or tap to see the reply.",
            "icon":         "💬",
            "action_url":   "/feedback.html",
            "action_label": "View Feedback",
            "created_by":   admin_id,
            "is_global":    False,
        })
    except Exception as e:
        logger.error(f"Failed to create feedback-reply notification: {e}")


def notify_new_feature(title: str, message: str, admin_id: str, action_url: str = ""):
    """Called when admin broadcasts a feature announcement."""
    try:
        db.create_global_notification({
            "type":         "feature",
            "title":        title,
            "message":      message,
            "icon":         "🚀",
            "action_url":   action_url or "/dashboard.html",
            "action_label": "Explore Now",
            "created_by":   admin_id,
        })
    except Exception as e:
        logger.error(f"Failed to create feature notification: {e}")


def _type_icon(notif_type: str) -> str:
    return {
        "update":         "🔄",
        "feedback_reply": "💬",
        "terms":          "📋",
        "announcement":   "📢",
        "feature":        "🚀",
        "security":       "🛡️",
        "maintenance":    "🔧",
        "system":         "⚙️",
    }.get(notif_type, "🔔")
