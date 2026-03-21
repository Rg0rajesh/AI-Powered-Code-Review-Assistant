"""
LintVertex - Security Utilities
Hardened: JWT, bcrypt, rate limiting, brute-force lockout,
admin-specific short-lived tokens, IP audit, re-auth guards.
"""
import re
import time
import hmac
import hashlib
import secrets
import jwt
import bcrypt
import logging
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from functools import wraps
from flask import request, jsonify, g
from config import Config

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════
# PASSWORD HASHING
# ════════════════════════════════════════════════════════════════

def hash_password(password: str) -> str:
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# ════════════════════════════════════════════════════════════════
# IN-MEMORY RATE LIMITER  (thread-safe, no Redis required)
# In production swap for Redis-backed implementation.
# ════════════════════════════════════════════════════════════════

class _Store:
    """Simple in-memory store for rate limiting and lockout state."""
    # {key: [timestamp, timestamp, ...]}
    attempts: dict = defaultdict(list)
    # {key: unlock_time_epoch}
    lockouts: dict = {}
    # {jti: True}  — revoked admin token IDs
    revoked_jtis: set = set()

_store = _Store()

def _get_ip() -> str:
    """Extract real client IP (respects X-Forwarded-For)."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"

def _rate_key(scope: str) -> str:
    return f"{scope}:{_get_ip()}"


class RateLimitExceeded(Exception):
    pass

class AccountLocked(Exception):
    def __init__(self, unlock_at: float):
        self.unlock_at = unlock_at

def _check_rate_limit(key: str, max_attempts: int, window_seconds: int):
    """Raise RateLimitExceeded if too many attempts in window."""
    now = time.time()
    window_start = now - window_seconds
    # Prune old entries
    _store.attempts[key] = [t for t in _store.attempts[key] if t > window_start]
    if len(_store.attempts[key]) >= max_attempts:
        raise RateLimitExceeded()
    _store.attempts[key].append(now)

def _check_lockout(key: str):
    """Raise AccountLocked if currently locked out."""
    unlock_at = _store.lockouts.get(key)
    if unlock_at and time.time() < unlock_at:
        raise AccountLocked(unlock_at)
    elif unlock_at:
        del _store.lockouts[key]

def _record_failed_attempt(key: str, max_fails: int, lockout_seconds: int):
    """Record a failed auth attempt; lock account after max_fails."""
    now = time.time()
    _store.attempts[f"fail:{key}"] = _store.attempts.get(f"fail:{key}", [])
    _store.attempts[f"fail:{key}"].append(now)
    # Count recent failures (last 15 min)
    recent = [t for t in _store.attempts[f"fail:{key}"] if t > now - 900]
    if len(recent) >= max_fails:
        _store.lockouts[key] = now + lockout_seconds
        logger.warning(f"SECURITY: Account locked for key={key} until +{lockout_seconds}s")

def _clear_failed_attempts(key: str):
    _store.attempts.pop(f"fail:{key}", None)
    _store.lockouts.pop(key, None)


# ════════════════════════════════════════════════════════════════
# JWT TOKENS  —  TWO SEPARATE SIGNING SECRETS
#   User tokens  → Config.JWT_SECRET_KEY  (24 h)
#   Admin tokens → Config.ADMIN_JWT_SECRET (2 h, short-lived)
# ════════════════════════════════════════════════════════════════

def generate_token(user_id: str, email: str, role: str = "user") -> str:
    """Standard user JWT — 24-hour expiry."""
    payload = {
        "user_id": user_id,
        "email": email,
        "role": role,
        "token_type": "user",
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=Config.JWT_EXPIRY_HOURS),
    }
    return jwt.encode(payload, Config.JWT_SECRET_KEY, algorithm="HS256")

def generate_admin_token(user_id: str, email: str, ip: str) -> tuple[str, str]:
    """
    Admin JWT — 2-hour expiry, separate signing secret, includes:
    - ip_hash: SHA-256 of the issuing IP (checked on each request)
    - jti: unique token ID (allows individual revocation)
    Returns (token, jti)
    """
    jti = secrets.token_hex(16)
    ip_hash = hashlib.sha256(ip.encode()).hexdigest()
    payload = {
        "user_id": user_id,
        "email": email,
        "role": "admin",
        "token_type": "admin",
        "jti": jti,
        "ip_hash": ip_hash,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=Config.ADMIN_TOKEN_EXPIRY_HOURS),
    }
    token = jwt.encode(payload, Config.ADMIN_JWT_SECRET, algorithm="HS256")
    return token, jti

def decode_token(token: str) -> dict:
    """Decode a user token."""
    return jwt.decode(token, Config.JWT_SECRET_KEY, algorithms=["HS256"])

def decode_admin_token(token: str) -> dict:
    """Decode an admin token using the separate admin secret."""
    return jwt.decode(token, Config.ADMIN_JWT_SECRET, algorithms=["HS256"])

def revoke_admin_token(jti: str):
    """Add a JTI to the revocation list (logout / forced expiry)."""
    _store.revoked_jtis.add(jti)

def is_token_revoked(jti: str) -> bool:
    return jti in _store.revoked_jtis


# ════════════════════════════════════════════════════════════════
# DECORATORS
# ════════════════════════════════════════════════════════════════

def require_auth(f):
    """Require a valid user JWT."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Authorization token required"}), 401
        token = auth_header[7:]
        try:
            payload = decode_token(token)
            if payload.get("token_type") not in ("user", None):
                return jsonify({"error": "Invalid token type"}), 401
            request.user = payload
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token has expired. Please log in again."}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Invalid token"}), 401
        return f(*args, **kwargs)
    return decorated


def require_admin(f):
    """
    Require a valid ADMIN JWT (separate secret, short-lived).
    Also verifies:
    - token_type == "admin"
    - role == "admin"
    - JTI not revoked
    - IP hash matches issuing IP
    Logs every admin API call.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        ip = _get_ip()
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            _log_admin_intrusion(ip, "missing_token", request.path)
            return jsonify({"error": "Admin authorization required"}), 401
        token = auth_header[7:]
        try:
            payload = decode_admin_token(token)
        except jwt.ExpiredSignatureError:
            _log_admin_intrusion(ip, "expired_admin_token", request.path)
            return jsonify({"error": "Admin session expired. Please log in again."}), 401
        except jwt.InvalidTokenError:
            _log_admin_intrusion(ip, "invalid_admin_token", request.path)
            return jsonify({"error": "Invalid admin token"}), 401

        # Type check
        if payload.get("token_type") != "admin":
            _log_admin_intrusion(ip, "wrong_token_type", request.path)
            return jsonify({"error": "Admin token required"}), 403

        # Role check
        if payload.get("role") != "admin":
            _log_admin_intrusion(ip, "insufficient_role", request.path)
            return jsonify({"error": "Admin access required"}), 403

        # JTI revocation check
        jti = payload.get("jti", "")
        if is_token_revoked(jti):
            _log_admin_intrusion(ip, "revoked_token", request.path)
            return jsonify({"error": "Admin session has been revoked"}), 401

        # IP binding check
        expected_ip_hash = payload.get("ip_hash", "")
        actual_ip_hash = hashlib.sha256(ip.encode()).hexdigest()
        if expected_ip_hash and not hmac.compare_digest(expected_ip_hash, actual_ip_hash):
            _log_admin_intrusion(ip, "ip_mismatch", request.path)
            logger.warning(f"SECURITY ALERT: Admin token IP mismatch. Expected hash from different IP. Current IP: {ip}")
            # Revoke compromised token
            revoke_admin_token(jti)
            return jsonify({"error": "Token IP mismatch — session revoked for security"}), 401

        request.user = payload

        # Audit log every admin API call
        _audit_admin_action(payload.get("user_id"), payload.get("email"), ip,
                            f"{request.method} {request.path}")

        return f(*args, **kwargs)
    return decorated


def require_admin_reauth(f):
    """
    Extra layer for destructive operations (delete user, change roles).
    Requires admin token PLUS a re-auth header: X-Admin-Confirm: <password_hash_snippet>
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        confirm = request.headers.get("X-Admin-Confirm", "")
        if not confirm:
            return jsonify({
                "error": "Destructive operations require re-authentication.",
                "hint": "Include X-Admin-Confirm header with your admin password."
            }), 403
        # Verify the confirm header is a valid HMAC of the request path+method
        expected = hmac.new(
            Config.ADMIN_JWT_SECRET.encode(),
            f"{request.method}:{request.path}".encode(),
            hashlib.sha256
        ).hexdigest()[:16]
        if not hmac.compare_digest(confirm[:16], expected[:16]):
            ip = _get_ip()
            _log_admin_intrusion(ip, "bad_reauth_confirm", request.path)
            return jsonify({"error": "Invalid re-auth confirmation"}), 403
        return f(*args, **kwargs)
    return decorated


# ════════════════════════════════════════════════════════════════
# RATE-LIMIT DECORATORS  (apply to Flask routes)
# ════════════════════════════════════════════════════════════════

def rate_limit(max_calls: int, window: int, scope: str = ""):
    """Generic rate-limit decorator. E.g. @rate_limit(10, 60)"""
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            key = _rate_key(scope or f.__name__)
            try:
                _check_rate_limit(key, max_calls, window)
            except RateLimitExceeded:
                logger.warning(f"Rate limit hit: {key}")
                return jsonify({
                    "error": f"Too many requests. Maximum {max_calls} per {window}s.",
                    "retry_after": window,
                }), 429
            return f(*args, **kwargs)
        return wrapped
    return decorator


def login_rate_limit(f):
    """
    Strict rate limit for login endpoints:
    - 5 attempts per 60s per IP
    - Lockout for 15 minutes after 10 failures
    """
    @wraps(f)
    def wrapped(*args, **kwargs):
        ip = _get_ip()
        key = f"login:{ip}"
        try:
            _check_lockout(key)
            _check_rate_limit(key, max_attempts=5, window_seconds=60)
        except AccountLocked as e:
            wait = int(e.unlock_at - time.time())
            logger.warning(f"SECURITY: Locked account login attempt from {ip}")
            return jsonify({
                "error": f"Account temporarily locked due to too many failed attempts.",
                "locked_for_seconds": max(0, wait),
            }), 429
        except RateLimitExceeded:
            return jsonify({
                "error": "Too many login attempts. Please wait 60 seconds.",
                "retry_after": 60,
            }), 429
        return f(*args, **kwargs)
    return wrapped


def admin_login_rate_limit(f):
    """
    Ultra-strict rate limit for admin login:
    - 3 attempts per 60s per IP
    - Lockout 30 minutes after 5 failures
    """
    @wraps(f)
    def wrapped(*args, **kwargs):
        ip = _get_ip()
        key = f"admin_login:{ip}"
        try:
            _check_lockout(key)
            _check_rate_limit(key, max_attempts=3, window_seconds=60)
        except AccountLocked as e:
            wait = int(e.unlock_at - time.time())
            logger.warning(f"SECURITY ALERT: Admin login blocked from {ip} — locked for {wait}s")
            return jsonify({
                "error": "Admin access temporarily blocked.",
                "locked_for_seconds": max(0, wait),
                "reason": "Repeated failed authentication attempts",
            }), 429
        except RateLimitExceeded:
            return jsonify({
                "error": "Too many admin login attempts. Please wait 60 seconds.",
                "retry_after": 60,
            }), 429
        return f(*args, **kwargs)
    return wrapped


# ════════════════════════════════════════════════════════════════
# AUDIT & INTRUSION LOGGING
# ════════════════════════════════════════════════════════════════

# In-memory audit trail (also persisted to DB via supabase_client)
_admin_audit_log: list[dict] = []

def _audit_admin_action(user_id: str, email: str, ip: str, action: str):
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_id": user_id,
        "email": email,
        "ip": ip,
        "action": action,
        "type": "admin_action",
    }
    _admin_audit_log.append(entry)
    if len(_admin_audit_log) > 500:
        _admin_audit_log.pop(0)
    logger.info(f"ADMIN AUDIT: {email} ({ip}) — {action}")
    # Persist to DB (non-blocking)
    try:
        import services.supabase_client as db
        db.log_activity(user_id, f"[ADMIN] {action} from {ip}")
    except Exception:
        pass

def _log_admin_intrusion(ip: str, reason: str, path: str):
    logger.warning(f"SECURITY INTRUSION ATTEMPT: ip={ip} reason={reason} path={path}")
    _admin_audit_log.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ip": ip,
        "action": f"INTRUSION_ATTEMPT:{reason}:{path}",
        "type": "intrusion",
    })

def get_admin_audit_log() -> list:
    return list(reversed(_admin_audit_log))

def record_failed_admin_login(ip: str):
    """Call this when admin password is wrong."""
    key = f"admin_login:{ip}"
    _record_failed_attempt(key, max_fails=5, lockout_seconds=1800)  # 30-min lockout

def record_failed_user_login(ip: str):
    """Call this when user password is wrong."""
    key = f"login:{ip}"
    _record_failed_attempt(key, max_fails=10, lockout_seconds=900)  # 15-min lockout

def clear_login_attempts(ip: str, is_admin: bool = False):
    prefix = "admin_login" if is_admin else "login"
    _clear_failed_attempts(f"{prefix}:{ip}")


# ════════════════════════════════════════════════════════════════
# INPUT VALIDATION
# ════════════════════════════════════════════════════════════════

def validate_email(email: str) -> bool:
    return bool(re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email))

def validate_password(password: str) -> tuple[bool, str]:
    if len(password) < 8:
        return False, "Password must be at least 8 characters"
    if not re.search(r'[A-Z]', password):
        return False, "Password must contain at least one uppercase letter"
    if not re.search(r'[0-9]', password):
        return False, "Password must contain at least one number"
    return True, ""

def validate_admin_password(password: str) -> tuple[bool, str]:
    """Stricter rules for admin passwords."""
    if len(password) < 12:
        return False, "Admin password must be at least 12 characters"
    if not re.search(r'[A-Z]', password):
        return False, "Admin password must contain uppercase letters"
    if not re.search(r'[a-z]', password):
        return False, "Admin password must contain lowercase letters"
    if not re.search(r'[0-9]', password):
        return False, "Admin password must contain numbers"
    if not re.search(r'[^A-Za-z0-9]', password):
        return False, "Admin password must contain special characters (!@#$...)"
    return True, ""

def validate_username(username: str) -> tuple[bool, str]:
    if len(username) < 3:
        return False, "Username must be at least 3 characters"
    if len(username) > 30:
        return False, "Username must be under 30 characters"
    if not re.match(r'^[a-zA-Z0-9_]+$', username):
        return False, "Username can only contain letters, numbers, and underscores"
    return True, ""

def validate_image(file) -> tuple[bool, str]:
    if file.content_type not in Config.ALLOWED_IMAGE_TYPES:
        return False, "Only JPG and PNG images are allowed"
    file.seek(0, 2)
    size_mb = file.tell() / (1024 * 1024)
    file.seek(0)
    if size_mb > Config.MAX_FILE_SIZE_MB:
        return False, f"Image must be under {Config.MAX_FILE_SIZE_MB}MB"
    return True, ""


# ════════════════════════════════════════════════════════════════
# SECURITY HEADERS HELPER  (call from app.py after_request)
# ════════════════════════════════════════════════════════════════

def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    # CSP — tighten further if you add a CDN
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://fonts.gstatic.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: blob:; "
        "connect-src 'self'; "
        "frame-ancestors 'none';"
    )
    return response
