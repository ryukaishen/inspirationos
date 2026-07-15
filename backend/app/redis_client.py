"""Shared Redis client (sessions later, RQ job queues now)."""

from functools import lru_cache

from redis import Redis

from app.config import get_config


@lru_cache
def get_redis_client() -> Redis:
    return Redis.from_url(
        get_config().redis_url,
        socket_connect_timeout=5,
        socket_timeout=5,
    )


def get_redis() -> Redis:
    """FastAPI dependency; separate from get_redis_client so tests can override it."""
    return get_redis_client()
