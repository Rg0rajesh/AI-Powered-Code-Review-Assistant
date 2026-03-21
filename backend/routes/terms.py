"""
LintVertex - Terms & Conditions Routes

User endpoints:
  GET  /api/terms/current          — Get active T&C (always public)
  GET  /api/terms/status           — Check if current user needs to accept
  POST /api/terms/accept           — Record user acceptance

Admin endpoints:
  GET  /api/admin/terms            — All versions list
  POST /api/admin/terms/publish    — Publish new version (forces all users to re-accept)
  PUT  /api/admin/terms/<id>       — Edit draft / update content
  POST /api/admin/terms/<id>/activate — Make a version current
  GET  /api/admin/terms/<id>/stats — Acceptance stats for a version
"""
import logging
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify
from utils.security import require_auth, require_admin, _get_ip
import services.supabase_client as db

terms_bp       = Blueprint("terms",       __name__)
admin_terms_bp = Blueprint("admin_terms", __name__)
logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════
# PUBLIC / USER ENDPOINTS
# ════════════════════════════════════════════════════════════════

@terms_bp.route("/api/terms/current", methods=["GET"])
def get_current_terms():
    """Return the active T&C version. Public — no auth required."""
    terms = db.get_current_terms()
    if not terms:
        return jsonify({"error": "No terms found. Please contact an administrator."}), 404
    return jsonify({
        "id":           terms["id"],
        "version":      terms["version"],
        "title":        terms["title"],
        "content":      terms["content"],
        "summary":      terms["summary"],
        "effective_at": terms["effective_at"],
        "created_at":   terms["created_at"],
    }), 200


@terms_bp.route("/api/terms/status", methods=["GET"])
@require_auth
def terms_status():
    """
    Check whether the current user needs to accept the current T&C.
    Returns:
      { needs_acceptance: bool, terms_id, version, title }
    Called on every login / dashboard load.
    """
    user_id = request.user["user_id"]
    terms = db.get_current_terms()

    if not terms:
        # No T&C configured — don't block the user
        return jsonify({"needs_acceptance": False}), 200

    already_accepted = db.has_user_accepted_terms(user_id, terms["id"])

    return jsonify({
        "needs_acceptance": not already_accepted,
        "terms_id":    terms["id"],
        "version":     terms["version"],
        "title":       terms["title"],
        "summary":     terms.get("summary", ""),
        "effective_at": terms["effective_at"],
    }), 200


@terms_bp.route("/api/terms/accept", methods=["POST"])
@require_auth
def accept_terms():
    """
    Record that the user has accepted the current T&C.
    Body: { "terms_id": "<uuid>", "accepted": true }
    """
    data    = request.get_json() or {}
    terms_id = data.get("terms_id", "").strip()
    accepted = data.get("accepted", False)

    if not accepted:
        return jsonify({"error": "You must accept the Terms and Conditions to use LintVertex"}), 400

    if not terms_id:
        return jsonify({"error": "terms_id is required"}), 400

    # Validate the terms_id still exists and is current
    terms = db.get_terms_by_id(terms_id)
    if not terms:
        return jsonify({"error": "Invalid terms version"}), 404

    user_id    = request.user["user_id"]
    ip         = _get_ip()
    user_agent = request.headers.get("User-Agent", "")[:500]

    db.record_terms_acceptance(user_id, terms_id, ip, user_agent)
    db.log_activity(user_id, f"terms_accepted:v{terms['version']}")

    logger.info(f"User {user_id} accepted T&C v{terms['version']} from {ip}")

    return jsonify({
        "message":      "Terms accepted. Welcome to LintVertex!",
        "version":      terms["version"],
        "accepted_at":  datetime.now(timezone.utc).isoformat(),
    }), 200


@terms_bp.route("/api/terms/history", methods=["GET"])
@require_auth
def my_acceptance_history():
    """List all T&C versions this user has accepted."""
    user_id = request.user["user_id"]
    result  = db.get_user_acceptance_history(user_id)
    records = []
    for row in (result.data or []):
        tv = row.get("terms_versions") or {}
        records.append({
            "accepted_at": row["accepted_at"],
            "version":     tv.get("version", "?"),
            "title":       tv.get("title",   "?"),
            "ip_address":  row.get("ip_address", ""),
        })
    return jsonify({"history": records}), 200


# ════════════════════════════════════════════════════════════════
# ADMIN ENDPOINTS
# ════════════════════════════════════════════════════════════════

@admin_terms_bp.route("/api/admin/terms", methods=["GET"])
@require_admin
def list_terms_versions():
    """List all T&C versions with stats."""
    result = db.get_all_terms_versions()
    versions = []
    for t in (result.data or []):
        stats = db.get_terms_acceptance_stats(t["id"])
        versions.append({
            "id":          t["id"],
            "version":     t["version"],
            "title":       t["title"],
            "summary":     t.get("summary", ""),
            "is_current":  t["is_current"],
            "created_at":  t["created_at"],
            "effective_at": t["effective_at"],
            "accepted_count": stats["accepted"],
            "pending_count":  stats["pending"],
            "total_users":    stats["total_users"],
        })
    return jsonify({"versions": versions}), 200


@admin_terms_bp.route("/api/admin/terms/publish", methods=["POST"])
@require_admin
def publish_terms():
    """
    Publish a new T&C version. This immediately:
    - Creates a new version record
    - Sets it as the current (active) version
    - All users will be required to accept on next login
    """
    data = request.get_json() or {}

    version  = data.get("version", "").strip()
    title    = data.get("title",   "").strip()
    content  = data.get("content", "").strip()
    summary  = data.get("summary", "").strip()
    eff_date = data.get("effective_at", datetime.now(timezone.utc).isoformat())

    if not version or not title or not content:
        return jsonify({"error": "version, title, and content are required"}), 400

    # Validate version string format
    import re
    if not re.match(r'^\d+\.\d+(\.\d+)?$', version):
        return jsonify({"error": "Version must be in format like 1.0 or 2.1.3"}), 400

    terms_data = {
        "version":      version,
        "title":        title,
        "content":      content,
        "summary":      summary,
        "published_by": request.user["user_id"],
        "effective_at": eff_date,
    }

    result = db.publish_new_terms(terms_data)
    if not result.data:
        return jsonify({"error": "Failed to publish terms"}), 500

    published = result.data[0]
    db.log_activity(request.user["user_id"], f"admin_terms_published:v{version}")

    logger.info(f"Admin {request.user['email']} published T&C v{version}")

    # Optionally send notification email to all users
    notify = data.get("send_email_notification", False)
    if notify:
        try:
            _notify_users_of_new_terms(version, title, summary)
        except Exception as e:
            logger.error(f"Failed to send T&C notification emails: {e}")

    return jsonify({
        "message":    f"Terms v{version} published successfully. All users must re-accept.",
        "id":         published["id"],
        "version":    version,
        "is_current": True,
        "email_sent": notify,
    }), 201


@admin_terms_bp.route("/api/admin/terms/<terms_id>", methods=["PUT"])
@require_admin
def update_terms(terms_id):
    """Update the content of a terms version (in-place edit)."""
    data = request.get_json() or {}
    allowed = {k: v for k, v in data.items()
               if k in ("title", "content", "summary", "effective_at")}
    if not allowed:
        return jsonify({"error": "No valid fields to update"}), 400

    db.update_terms_version(terms_id, allowed)
    db.log_activity(request.user["user_id"], f"admin_terms_updated:{terms_id}")
    return jsonify({"message": "Terms updated"}), 200


@admin_terms_bp.route("/api/admin/terms/<terms_id>/activate", methods=["POST"])
@require_admin
def activate_terms_version(terms_id):
    """Roll back or forward to a specific version."""
    terms = db.get_terms_by_id(terms_id)
    if not terms:
        return jsonify({"error": "Terms version not found"}), 404

    db.set_terms_as_current(terms_id)
    db.log_activity(request.user["user_id"], f"admin_terms_activated:v{terms['version']}")
    return jsonify({
        "message":  f"v{terms['version']} is now the active Terms version. All users must re-accept.",
        "version":  terms["version"],
    }), 200


@admin_terms_bp.route("/api/admin/terms/<terms_id>/stats", methods=["GET"])
@require_admin
def terms_stats(terms_id):
    """Acceptance stats for a specific version."""
    terms = db.get_terms_by_id(terms_id)
    if not terms:
        return jsonify({"error": "Terms version not found"}), 404

    stats = db.get_terms_acceptance_stats(terms_id)

    # Get list of users who accepted
    from services.supabase_client import get_admin_client
    accepted_users = (get_admin_client()
                      .table("user_terms_acceptance")
                      .select("accepted_at, ip_address, users(username, email)")
                      .eq("terms_version_id", terms_id)
                      .order("accepted_at", desc=True)
                      .execute())

    users_list = []
    for row in (accepted_users.data or []):
        u = row.get("users") or {}
        users_list.append({
            "username":    u.get("username", "?"),
            "email":       u.get("email", "?"),
            "accepted_at": row["accepted_at"],
            "ip":          row.get("ip_address", ""),
        })

    return jsonify({
        "version":     terms["version"],
        "title":       terms["title"],
        "is_current":  terms["is_current"],
        "stats":       stats,
        "accepted_users": users_list,
    }), 200


# ─── Helper ──────────────────────────────────────────────────────────────────

def _notify_users_of_new_terms(version: str, title: str, summary: str):
    """Send email notification to all users about new T&C."""
    from services.email_service import send_policy_notice
    result = db.get_all_users()
    for user in (result.data or []):
        send_policy_notice(
            to_email    = user["email"],
            username    = user["username"],
            subject     = f"📋 LintVertex Terms Updated — Please Review v{version}",
            policy_title= f"{title} — Version {version}",
            body_html   = f"<p>We've updated our Terms and Conditions. You'll be asked to review and accept the new terms the next time you log in.</p>"
                          + (f"<p><strong>What changed:</strong> {summary}</p>" if summary else ""),
            effective_date = "",
            tag_label   = "Terms Update",
            tag_type    = "orange",
        )
