"""
LintVertex - OTP Service (Database-backed)
All OTP records and reset tokens persisted in Supabase.
No in-memory state — survives server restarts, works across multiple workers.
"""
import time
import hashlib
import hmac
import secrets
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────
OTP_LENGTH            = 6
OTP_EXPIRY_SECS       = 300        # 5 minutes
MAX_OTP_ATTEMPTS      = 5
OTP_RESEND_SECS       = 60         # cooldown between resends
MAX_REQUESTS_PER_HOUR = 5          # per email per hour
RESET_TOKEN_EXPIRY    = 600        # 10 minutes


# ── Exceptions ────────────────────────────────────────────────
class OTPError(Exception): pass

class OTPRateLimited(OTPError):
    def __init__(self, retry_after: int):
        self.retry_after = retry_after

class OTPExpired(OTPError): pass
class OTPAlreadyUsed(OTPError): pass

class OTPInvalid(OTPError):
    def __init__(self, attempts_left: int):
        self.attempts_left = attempts_left


# ── Helpers ───────────────────────────────────────────────────
def _email_hash(email: str) -> str:
    """SHA-256 of lowercased email — used as DB lookup key."""
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()

def _otp_hash(email: str, otp: str) -> str:
    """SHA-256 of 'email:otp' — what we store in DB."""
    return hashlib.sha256(f"{email.strip().lower()}:{otp}".encode()).hexdigest()

def _token_hash(token: str) -> str:
    """SHA-256 of the reset token — stored in DB, plain sent to user."""
    return hashlib.sha256(token.encode()).hexdigest()

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _iso_from_epoch(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()

def _expires_iso(seconds_from_now: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds_from_now)).isoformat()


# ════════════════════════════════════════════════════════════════
# OTP GENERATION  (Step 1)
# ════════════════════════════════════════════════════════════════

def generate_otp(email: str, user_id: str, ip_address: str = None) -> str:
    """
    Generate a 6-digit OTP, persist its hash in Supabase, return plain OTP.
    Enforces:
      - 60s resend cooldown  (checked via existing DB record's created_at)
      - Max 5 requests/hour  (checked via activity_logs)
    """
    import services.supabase_client as db

    email_key = _email_hash(email)
    now       = time.time()

    # ── Resend cooldown: check last OTP record ─────────────────
    existing = db.get_otp_record(email_key)
    if existing:
        created = datetime.fromisoformat(
            existing["created_at"].replace("Z", "+00:00")
        ).timestamp()
        wait = OTP_RESEND_SECS - (now - created)
        if wait > 0:
            raise OTPRateLimited(retry_after=int(wait))

    # ── Hourly cap: count via activity_logs ───────────────────
    hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    count = db.get_otp_request_count(email_key, hour_ago)
    if count >= MAX_REQUESTS_PER_HOUR:
        raise OTPRateLimited(retry_after=3600)

    # ── Generate and hash OTP ─────────────────────────────────
    otp_plain = "".join([str(secrets.randbelow(10)) for _ in range(OTP_LENGTH)])
    otp_hashed  = _otp_hash(email, otp_plain)
    expires_iso = _expires_iso(OTP_EXPIRY_SECS)

    # ── Persist to Supabase ───────────────────────────────────
    db.upsert_otp_record(
        email_hash  = email_key,
        otp_hash    = otp_hashed,
        expires_at  = expires_iso,
        ip_address  = ip_address,
    )

    # Log request for hourly cap tracking
    db.log_otp_request(user_id, email_key)

    logger.info(f"OTP generated → DB. email_hash={email_key[:8]}... expires={expires_iso}")
    return otp_plain


# ════════════════════════════════════════════════════════════════
# OTP VERIFICATION  (Step 2)
# ════════════════════════════════════════════════════════════════

def verify_otp(email: str, otp_input: str) -> bool:
    """
    Verify OTP against DB record.
    Raises OTPExpired / OTPAlreadyUsed / OTPInvalid on failure.
    On success: marks record as used in DB.
    """
    import services.supabase_client as db

    email_key = _email_hash(email)
    record    = db.get_otp_record(email_key)

    if not record:
        raise OTPExpired()

    # ── Expiry check ──────────────────────────────────────────
    expires_at = datetime.fromisoformat(
        record["expires_at"].replace("Z", "+00:00")
    )
    if datetime.now(timezone.utc) > expires_at:
        db.delete_otp_record(email_key)   # Clean up expired record
        raise OTPExpired()

    # ── Already used ──────────────────────────────────────────
    if record["used"]:
        raise OTPAlreadyUsed()

    # ── Attempt limit ─────────────────────────────────────────
    if record["attempts"] >= MAX_OTP_ATTEMPTS:
        db.delete_otp_record(email_key)
        raise OTPInvalid(attempts_left=0)

    # ── Constant-time hash comparison ─────────────────────────
    otp_clean    = otp_input.strip().replace(" ", "")
    input_hash   = _otp_hash(email, otp_clean)
    is_valid     = hmac.compare_digest(input_hash, record["otp_hash"])

    if not is_valid:
        new_attempts = record["attempts"] + 1
        db.increment_otp_attempts(record["id"], new_attempts)
        attempts_left = MAX_OTP_ATTEMPTS - new_attempts

        if attempts_left <= 0:
            db.delete_otp_record(email_key)

        logger.warning(f"OTP mismatch. email_hash={email_key[:8]}... attempts_left={attempts_left}")
        raise OTPInvalid(attempts_left=attempts_left)

    # ✅ Mark as used in DB
    db.mark_otp_used(record["id"])
    logger.info(f"OTP verified ✓. email_hash={email_key[:8]}...")
    return True


# ════════════════════════════════════════════════════════════════
# RESET TOKEN  (Issued after OTP passes, used to set new password)
# ════════════════════════════════════════════════════════════════

def create_reset_token(email: str, user_id: str, ip_address: str = None) -> str:
    """
    Generate a cryptographically secure reset token, store its hash in Supabase.
    Returns the plain token (only time it's available as plaintext).
    """
    import services.supabase_client as db

    token_plain  = secrets.token_urlsafe(40)
    token_hashed = _token_hash(token_plain)
    expires_iso  = _expires_iso(RESET_TOKEN_EXPIRY)

    db.save_reset_token(
        token_hash  = token_hashed,
        user_id     = user_id,
        email       = email,
        expires_at  = expires_iso,
        ip_address  = ip_address,
    )

    logger.info(f"Reset token created → DB. user_id={user_id} expires={expires_iso}")
    return token_plain


def verify_reset_token(token_plain: str) -> dict:
    """
    Look up a reset token by its hash.
    Returns the DB record on success.
    Raises ValueError on invalid / expired / used token.
    """
    import services.supabase_client as db

    token_hashed = _token_hash(token_plain)
    record       = db.get_reset_token_record(token_hashed)

    if not record:
        raise ValueError("invalid_token")

    if record["used"]:
        raise ValueError("token_used")

    expires_at = datetime.fromisoformat(
        record["expires_at"].replace("Z", "+00:00")
    )
    if datetime.now(timezone.utc) > expires_at:
        raise ValueError("token_expired")

    return record


def consume_reset_token(token_plain: str):
    """Mark a reset token as used (call after successful password reset)."""
    import services.supabase_client as db
    token_hashed = _token_hash(token_plain)
    record       = db.get_reset_token_record(token_hashed)
    if record:
        db.mark_reset_token_used(record["id"])


# ════════════════════════════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════════════════════════════

def invalidate_otp(email: str):
    """Explicitly delete any pending OTP for an email."""
    import services.supabase_client as db
    db.delete_otp_record(_email_hash(email))


def get_otp_status(email: str) -> dict:
    """Non-sensitive status info for frontend countdown timer."""
    import services.supabase_client as db
    record = db.get_otp_record(_email_hash(email))
    if not record:
        return {"exists": False, "resend_cooldown": 0}

    expires_at = datetime.fromisoformat(record["expires_at"].replace("Z", "+00:00"))
    remaining  = max(0, int((expires_at - datetime.now(timezone.utc)).total_seconds()))

    # Resend cooldown from created_at
    created    = datetime.fromisoformat(record["created_at"].replace("Z", "+00:00"))
    resend_wait = max(0, int(OTP_RESEND_SECS - (datetime.now(timezone.utc) - created).total_seconds()))

    return {
        "exists":        True,
        "expires_in":    remaining,
        "attempts_used": record["attempts"],
        "attempts_left": MAX_OTP_ATTEMPTS - record["attempts"],
        "used":          record["used"],
        "resend_cooldown": resend_wait,
    }
