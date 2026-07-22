"""Server-side sessions in Redis (M9): revocable on logout, survive a
backend process restart (Redis is a separate process), sliding TTL.

The cookie value is `{token}.{signature}` — an HMAC-SHA256 of the random
token, keyed by `AppConfig.secret_key`. This is tamper-evidence only (a
forged token still needs a Redis hit to resolve to a user); the actual
capability lives in Redis, not in the signature, so revocation is immediate.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from redis import Redis

SESSION_COOKIE_NAME = "session_id"
_REDIS_KEY_PREFIX = "session:"
_TOKEN_BYTES = 32


def _sign(token: str, secret_key: str) -> str:
    return hmac.new(secret_key.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()


def _redis_key(token: str) -> str:
    return f"{_REDIS_KEY_PREFIX}{token}"


def create_session(redis: Redis, *, user_id: int, secret_key: str, ttl_seconds: int) -> str:
    """Returns the signed cookie value; stores `token -> user_id` in Redis."""
    token = secrets.token_urlsafe(_TOKEN_BYTES)
    redis.set(_redis_key(token), str(user_id), ex=ttl_seconds)
    return f"{token}.{_sign(token, secret_key)}"


def resolve_session(
    redis: Redis, cookie_value: str, *, secret_key: str, ttl_seconds: int
) -> int | None:
    """Verifies the signature, then looks up the token in Redis. Extends the
    TTL on every successful resolution (sliding expiry). Returns the user id,
    or None if the cookie is malformed, forged, or the session has expired."""
    token, _, signature = cookie_value.partition(".")
    if not token or not signature:
        return None
    expected = _sign(token, secret_key)
    if not hmac.compare_digest(expected, signature):
        return None
    key = _redis_key(token)
    raw_user_id = redis.get(key)
    if raw_user_id is None:
        return None
    redis.expire(key, ttl_seconds)
    return int(raw_user_id)


def delete_session(redis: Redis, cookie_value: str) -> None:
    """Idempotent: deleting an already-gone or malformed session is a no-op."""
    token, _, _ = cookie_value.partition(".")
    if token:
        redis.delete(_redis_key(token))
