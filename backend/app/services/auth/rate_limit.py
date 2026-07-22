"""Login rate limiting (M9): a fixed-window counter in Redis, keyed by
client IP. Single-user app, so IP is the practical brute-force signal (the
account email is effectively public — limiting by IP is what actually slows
down a guesser). Counter resets on a successful login for that IP.
"""

from __future__ import annotations

from redis import Redis

_REDIS_KEY_PREFIX = "login_attempts:"


def _redis_key(client_ip: str) -> str:
    return f"{_REDIS_KEY_PREFIX}{client_ip}"


def register_failed_attempt(redis: Redis, client_ip: str, *, window_seconds: int) -> int:
    """Increments and returns the new attempt count within the current window."""
    key = _redis_key(client_ip)
    count = redis.incr(key)
    if count == 1:
        redis.expire(key, window_seconds)
    return int(count)


def is_rate_limited(redis: Redis, client_ip: str, *, max_attempts: int) -> bool:
    raw_count = redis.get(_redis_key(client_ip))
    return raw_count is not None and int(raw_count) >= max_attempts


def reset_attempts(redis: Redis, client_ip: str) -> None:
    redis.delete(_redis_key(client_ip))
