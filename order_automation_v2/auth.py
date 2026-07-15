import hashlib
import hmac
import os
import threading
import time

from itsdangerous import BadData, URLSafeSerializer

from config import DASHBOARD_USERS, SESSION_SECRET_KEY

ITERATIONS = 600_000

_serializer = URLSafeSerializer(SESSION_SECRET_KEY, salt="dashboard-session")

# Precomputed once so verify_password() can always run one PBKDF2 pass even
# for a username that doesn't exist - otherwise an unknown username returns
# instantly (no hashing) while a known one takes ~200ms, letting an attacker
# discover valid usernames purely from response timing.
_DUMMY_SALT = bytes(16)
_DUMMY_HASH = hashlib.pbkdf2_hmac("sha256", b"", _DUMMY_SALT, ITERATIONS).hex()

_rate_lock = threading.Lock()
_failed_attempts: dict[str, list[float]] = {}
MAX_ATTEMPTS = 5
WINDOW_SECONDS = 300


def hash_password(password: str, salt_hex: str | None = None) -> str:
    """Returns 'salt_hex$hash_hex' for storing in DASHBOARD_USERS. Pass no
    salt_hex to generate a new random salt (for provisioning a new account)."""
    salt = bytes.fromhex(salt_hex) if salt_hex else os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(username: str, password: str) -> bool:
    salt_hex, expected_hash = DASHBOARD_USERS.get(username, (_DUMMY_SALT.hex(), _DUMMY_HASH))
    computed = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), ITERATIONS
    ).hex()
    return hmac.compare_digest(computed, expected_hash) and username in DASHBOARD_USERS


def check_rate_limit(username: str) -> bool:
    """Returns False if this username has already hit MAX_ATTEMPTS failed
    logins within WINDOW_SECONDS. Per-username, not per-IP, because a
    Cloudflare-tunneled request arrives looking like it's from 127.0.0.1."""
    now = time.time()
    with _rate_lock:
        attempts = [t for t in _failed_attempts.get(username, []) if now - t < WINDOW_SECONDS]
        _failed_attempts[username] = attempts
        return len(attempts) < MAX_ATTEMPTS


def record_failed_attempt(username: str) -> None:
    with _rate_lock:
        _failed_attempts.setdefault(username, []).append(time.time())


def clear_failed_attempts(username: str) -> None:
    with _rate_lock:
        _failed_attempts.pop(username, None)


def sign_session(username: str) -> str:
    return _serializer.dumps(username)


def verify_session(token: str) -> str | None:
    """Returns the username if the token is a validly-signed session for a
    user that still exists in DASHBOARD_USERS, else None. No expiry check -
    session length is enforced by the cookie itself having no Max-Age/Expires
    (browser-session-only), not by anything checked here."""
    try:
        username = _serializer.loads(token)
    except BadData:
        return None
    return username if username in DASHBOARD_USERS else None
