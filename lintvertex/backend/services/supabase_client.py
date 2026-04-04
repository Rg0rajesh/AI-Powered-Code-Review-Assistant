"""
LintVertex - Supabase Client Service
Handles all database operations with Row Level Security
"""
from supabase import create_client, Client
from config import Config

_client: Client = None

def get_client() -> Client:
    """Get or create Supabase client (singleton)"""
    global _client
    if _client is None:
        if not Config.SUPABASE_URL or not Config.SUPABASE_ANON_KEY:
            raise ValueError("Supabase URL and ANON KEY must be set in environment variables")
        _client = create_client(Config.SUPABASE_URL, Config.SUPABASE_ANON_KEY)
    return _client

def get_admin_client() -> Client:
    """Get admin Supabase client with service role key (bypasses RLS)"""
    if not Config.SUPABASE_URL or not Config.SUPABASE_SERVICE_ROLE_KEY:
        raise ValueError("Supabase SERVICE ROLE KEY must be set in environment variables")
    return create_client(Config.SUPABASE_URL, Config.SUPABASE_SERVICE_ROLE_KEY)


# ─── User Operations ─────────────────────────────────────────────────────────

def get_user_by_email(email: str):
    db = get_admin_client()
    result = db.table("users").select("*").eq("email", email).execute()
    return result.data[0] if result.data else None

def get_user_by_id(user_id: str):
    db = get_admin_client()
    result = db.table("users").select("*").eq("id", user_id).execute()
    return result.data[0] if result.data else None

def create_user(data: dict):
    db = get_admin_client()
    return db.table("users").insert(data).execute()

def update_user(user_id: str, data: dict):
    db = get_admin_client()
    return db.table("users").update(data).eq("id", user_id).execute()

def get_all_users():
    db = get_admin_client()
    return db.table("users").select("id, username, email, role, created_at").execute()


# ─── Code Analysis Operations ─────────────────────────────────────────────────

def save_analysis(data: dict):
    db = get_admin_client()
    return db.table("code_analysis").insert(data).execute()

def get_user_analyses(user_id: str, limit: int = 20):
    db = get_admin_client()
    return (db.table("code_analysis")
              .select("*")
              .eq("user_id", user_id)
              .order("created_at", desc=True)
              .limit(limit)
              .execute())

def get_analysis_by_id(analysis_id: str):
    db = get_admin_client()
    result = db.table("code_analysis").select("*").eq("id", analysis_id).execute()
    return result.data[0] if result.data else None

def delete_analysis(analysis_id: str, user_id: str):
    db = get_admin_client()
    return (db.table("code_analysis")
              .delete()
              .eq("id", analysis_id)
              .eq("user_id", user_id)
              .execute())

def get_all_analyses(limit: int = 50):
    db = get_admin_client()
    return (db.table("code_analysis")
              .select("*, users(username, email)")
              .order("created_at", desc=True)
              .limit(limit)
              .execute())


# ─── Room Operations ──────────────────────────────────────────────────────────

def create_room(data: dict):
    db = get_admin_client()
    return db.table("rooms").insert(data).execute()

def get_room_by_key(room_key: str):
    db = get_admin_client()
    result = db.table("rooms").select("*").eq("room_key", room_key).execute()
    return result.data[0] if result.data else None

def get_user_rooms(user_id: str):
    db = get_admin_client()
    return (db.table("room_members")
              .select("*, rooms(*)")
              .eq("user_id", user_id)
              .execute())

def join_room(room_id: str, user_id: str):
    db = get_admin_client()
    # Check if already joined
    existing = (db.table("room_members")
                  .select("id")
                  .eq("room_id", room_id)
                  .eq("user_id", user_id)
                  .execute())
    if existing.data:
        return existing
    return db.table("room_members").insert({"room_id": room_id, "user_id": user_id}).execute()

def get_room_messages(room_id: str, limit: int = 100):
    db = get_admin_client()
    return (db.table("room_messages")
              .select("*, users(username, profile_image)")
              .eq("room_id", room_id)
              .order("created_at", desc=False)
              .limit(limit)
              .execute())

def save_message(data: dict):
    db = get_admin_client()
    return db.table("room_messages").insert(data).execute()

def get_all_rooms():
    db = get_admin_client()
    return db.table("rooms").select("*, users(username)").order("created_at", desc=True).execute()


# ─── Feedback Operations ──────────────────────────────────────────────────────

def save_feedback(data: dict):
    db = get_admin_client()
    return db.table("feedback").insert(data).execute()

def get_all_feedback():
    db = get_admin_client()
    return (db.table("feedback")
              .select("*, users(username, email)")
              .order("created_at", desc=True)
              .execute())


# ─── Activity Log Operations ──────────────────────────────────────────────────

def log_activity(user_id: str, action: str):
    try:
        db = get_admin_client()
        db.table("activity_logs").insert({"user_id": user_id, "action": action}).execute()
    except Exception:
        pass  # Non-critical, don't fail on log errors

def get_activity_logs(limit: int = 100):
    db = get_admin_client()
    return (db.table("activity_logs")
              .select("*, users(username)")
              .order("timestamp", desc=True)
              .limit(limit)
              .execute())


# ─── Stats Operations ─────────────────────────────────────────────────────────

def get_platform_stats():
    db = get_admin_client()
    users_count = db.table("users").select("id", count="exact").execute()
    analyses_count = db.table("code_analysis").select("id", count="exact").execute()
    rooms_count = db.table("rooms").select("id", count="exact").execute()
    feedback_count = db.table("feedback").select("id", count="exact").execute()
    return {
        "total_users": users_count.count or 0,
        "total_analyses": analyses_count.count or 0,
        "total_rooms": rooms_count.count or 0,
        "total_feedback": feedback_count.count or 0,
    }


# ─── Password Reset OTP Operations ───────────────────────────────────────────

def upsert_otp_record(email_hash: str, otp_hash: str, expires_at: str, ip_address: str = None):
    """Insert or replace OTP record for an email (one active OTP at a time)."""
    db = get_admin_client()
    # Delete any existing record for this email first
    db.table("password_reset_otps").delete().eq("email_hash", email_hash).execute()
    # Insert fresh record
    return db.table("password_reset_otps").insert({
        "email_hash": email_hash,
        "otp_hash":   otp_hash,
        "expires_at": expires_at,
        "attempts":   0,
        "used":       False,
        "ip_address": ip_address,
    }).execute()

def get_otp_record(email_hash: str):
    """Fetch the current OTP record for an email."""
    db = get_admin_client()
    result = (db.table("password_reset_otps")
                .select("*")
                .eq("email_hash", email_hash)
                .execute())
    return result.data[0] if result.data else None

def increment_otp_attempts(record_id: str, new_attempts: int):
    """Increment the failed attempt counter."""
    db = get_admin_client()
    return db.table("password_reset_otps").update({"attempts": new_attempts}).eq("id", record_id).execute()

def mark_otp_used(record_id: str):
    """Mark OTP as used (single-use guarantee)."""
    db = get_admin_client()
    return db.table("password_reset_otps").update({"used": True}).eq("id", record_id).execute()

def delete_otp_record(email_hash: str):
    """Delete OTP record (on password reset completion or explicit invalidation)."""
    db = get_admin_client()
    return db.table("password_reset_otps").delete().eq("email_hash", email_hash).execute()

def get_otp_request_count(email_hash: str, since_iso: str) -> int:
    """Count how many OTP requests have been made for this email since a timestamp."""
    db = get_admin_client()
    # We track via activity_logs for the hourly cap
    result = (db.table("activity_logs")
                .select("id", count="exact")
                .eq("action", f"otp_requested:{email_hash[:8]}")
                .gte("timestamp", since_iso)
                .execute())
    return result.count or 0

def log_otp_request(user_id: str, email_hash: str):
    """Log an OTP request for rate-limit tracking."""
    log_activity(user_id, f"otp_requested:{email_hash[:8]}")


# ─── Password Reset Token Operations ─────────────────────────────────────────

def save_reset_token(token_hash: str, user_id: str, email: str, expires_at: str, ip_address: str = None):
    """Save a reset token to the database."""
    db = get_admin_client()
    # Invalidate any previous unused tokens for this user
    (db.table("password_reset_tokens")
       .update({"used": True})
       .eq("user_id", user_id)
       .eq("used", False)
       .execute())
    return db.table("password_reset_tokens").insert({
        "token_hash": token_hash,
        "user_id":    user_id,
        "email":      email,
        "expires_at": expires_at,
        "used":       False,
        "ip_address": ip_address,
    }).execute()

def get_reset_token_record(token_hash: str):
    """Fetch a reset token record by its hash."""
    db = get_admin_client()
    result = (db.table("password_reset_tokens")
                .select("*")
                .eq("token_hash", token_hash)
                .execute())
    return result.data[0] if result.data else None

def mark_reset_token_used(record_id: str):
    """Mark a reset token as used (single-use)."""
    db = get_admin_client()
    return db.table("password_reset_tokens").update({"used": True}).eq("id", record_id).execute()

def cleanup_expired_otp_records():
    """Remove expired OTP and reset token records (call periodically)."""
    from datetime import datetime, timezone
    db = get_admin_client()
    now_iso = datetime.now(timezone.utc).isoformat()
    db.table("password_reset_otps").delete().lt("expires_at", now_iso).execute()
    db.table("password_reset_tokens").delete().lt("expires_at", now_iso).eq("used", False).execute()


# ─── Terms & Conditions Operations ───────────────────────────────────────────

def get_current_terms():
    """Fetch the currently active T&C version."""
    db = get_admin_client()
    result = db.table("terms_versions").select("*").eq("is_current", True).execute()
    return result.data[0] if result.data else None

def get_terms_by_id(terms_id: str):
    db = get_admin_client()
    result = db.table("terms_versions").select("*").eq("id", terms_id).execute()
    return result.data[0] if result.data else None

def get_all_terms_versions():
    """All versions, newest first."""
    db = get_admin_client()
    return db.table("terms_versions").select("id, version, title, summary, is_current, created_at, effective_at").order("created_at", desc=True).execute()

def publish_new_terms(data: dict):
    """
    Create a new T&C version and make it current.
    Atomically unsets the old current flag first.
    """
    db = get_admin_client()
    # Unset current from all existing versions
    db.table("terms_versions").update({"is_current": False}).eq("is_current", True).execute()
    # Insert new version as current
    data["is_current"] = True
    return db.table("terms_versions").insert(data).execute()

def update_terms_version(terms_id: str, data: dict):
    """Update non-structural fields (title, summary) of a terms version."""
    db = get_admin_client()
    allowed = {k: v for k, v in data.items() if k in ("title", "content", "summary", "effective_at")}
    return db.table("terms_versions").update(allowed).eq("id", terms_id).execute()

def set_terms_as_current(terms_id: str):
    """Roll back / forward to a specific version."""
    db = get_admin_client()
    db.table("terms_versions").update({"is_current": False}).eq("is_current", True).execute()
    db.table("terms_versions").update({"is_current": True}).eq("id", terms_id).execute()

def has_user_accepted_terms(user_id: str, terms_version_id: str) -> bool:
    """Check if a specific user has accepted a specific T&C version."""
    db = get_admin_client()
    result = (db.table("user_terms_acceptance")
                .select("id")
                .eq("user_id", user_id)
                .eq("terms_version_id", terms_version_id)
                .execute())
    return bool(result.data)

def record_terms_acceptance(user_id: str, terms_version_id: str, ip: str, user_agent: str):
    """Record that a user accepted a specific T&C version."""
    db = get_admin_client()
    return db.table("user_terms_acceptance").upsert({
        "user_id": user_id,
        "terms_version_id": terms_version_id,
        "ip_address": ip,
        "user_agent": user_agent,
    }, on_conflict="user_id,terms_version_id").execute()

def get_user_acceptance_history(user_id: str):
    db = get_admin_client()
    return (db.table("user_terms_acceptance")
              .select("*, terms_versions(version, title, created_at)")
              .eq("user_id", user_id)
              .order("accepted_at", desc=True)
              .execute())

def get_terms_acceptance_stats(terms_version_id: str) -> dict:
    """How many users accepted a given version."""
    db = get_admin_client()
    accepted = db.table("user_terms_acceptance").select("id", count="exact").eq("terms_version_id", terms_version_id).execute()
    total    = db.table("users").select("id", count="exact").execute()
    return {
        "accepted": accepted.count or 0,
        "total_users": total.count or 0,
        "pending": max(0, (total.count or 0) - (accepted.count or 0)),
    }


# ─── Notification Operations ──────────────────────────────────────────────────

def create_notification(data: dict):
    """Create a notification (for one user or global)."""
    db = get_admin_client()
    return db.table("notifications").insert(data).execute()

def create_global_notification(data: dict):
    """Create a notification visible to ALL users."""
    data["is_global"] = True
    data["user_id"]   = None
    db = get_admin_client()
    return db.table("notifications").insert(data).execute()

def get_user_notifications(user_id: str, limit: int = 30) -> list:
    """
    Fetch notifications for a user:
    - Personal notifications (user_id = user_id)
    - Global notifications (is_global = true) not yet individually read
    Sorted newest first.
    """
    db = get_admin_client()

    # Get personal notifications
    personal = (db.table("notifications")
                  .select("*")
                  .eq("user_id", user_id)
                  .order("created_at", desc=True)
                  .limit(limit * 2) # Fetch more to allow for expiry filtering
                  .execute())

    # Get global notifications
    global_notifs = (db.table("notifications")
                       .select("*")
                       .eq("is_global", True)
                       .is_("user_id", "null")
                       .order("created_at", desc=True)
                       .limit(limit * 2)
                       .execute())

    # Get IDs the user has already read (global ones)
    read_result = (db.table("notification_reads")
                     .select("notification_id")
                     .eq("user_id", user_id)
                     .execute())
    read_ids = {r["notification_id"] for r in (read_result.data or [])}

    now_iso = _now_iso()

    # Filter by expiry in Python (safer than Postgrest .or_ for stability)
    def is_valid(n):
        exp = n.get("expires_at")
        return not exp or exp > now_iso

    # Merge and tag is_read
    all_notifs = []
    for n in (personal.data or []):
        if is_valid(n):
            all_notifs.append({**n, "is_read": n.get("is_read", False)})
    for n in (global_notifs.data or []):
        if is_valid(n):
            all_notifs.append({**n, "is_read": n["id"] in read_ids})

    # Sort by created_at desc
    all_notifs.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return all_notifs[:limit]

def get_unread_count(user_id: str) -> int:
    """Count unread notifications for a user."""
    notifs = get_user_notifications(user_id, limit=100)
    return sum(1 for n in notifs if not n.get("is_read"))

def mark_notification_read(notification_id: str, user_id: str):
    """Mark a single notification as read."""
    db = get_admin_client()
    # Check if personal or global
    n = db.table("notifications").select("is_global,user_id").eq("id", notification_id).execute()
    if not n.data:
        return

    notif = n.data[0]
    if notif.get("is_global"):
        # Insert a read record for global notifications
        db.table("notification_reads").upsert({
            "user_id": user_id,
            "notification_id": notification_id
        }, on_conflict="user_id,notification_id").execute()
    else:
        # Update is_read on personal notification
        db.table("notifications").update({"is_read": True}).eq("id", notification_id).eq("user_id", user_id).execute()

def mark_all_read(user_id: str):
    """Mark all notifications read for a user."""
    db = get_admin_client()
    # Personal notifications
    db.table("notifications").update({"is_read": True}).eq("user_id", user_id).execute()
    # Global notifications — insert read records for unread ones
    global_notifs = (db.table("notifications")
                       .select("id")
                       .eq("is_global", True)
                       .is_("user_id", "null")
                       .execute())
    for n in (global_notifs.data or []):
        db.table("notification_reads").upsert({
            "user_id": user_id,
            "notification_id": n["id"]
        }, on_conflict="user_id,notification_id").execute()

def delete_notification(notification_id: str, admin_id: str = None):
    """Delete a notification (admin only)."""
    db = get_admin_client()
    return db.table("notifications").delete().eq("id", notification_id).execute()

def get_all_notifications_admin(limit: int = 100) -> list:
    """Admin: get all notifications."""
    db = get_admin_client()
    result = (db.table("notifications")
                .select("*, users!notifications_created_by_fkey(username)")
                .order("created_at", desc=True)
                .limit(limit)
                .execute())
    return result.data or []

def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
