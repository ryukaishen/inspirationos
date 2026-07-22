"""Cross-cutting request dependencies (M9): session auth and the CSRF-header
check. Applied at the router level in `app/api/__init__.py`, not per-route,
so gating coverage is provable by construction rather than by remembering to
annotate every new endpoint.
"""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from redis import Redis
from sqlalchemy.orm import Session

from app.config import get_config
from app.db import get_db_session
from app.models.user import User
from app.redis_client import get_redis
from app.services.auth.sessions import SESSION_COOKIE_NAME, resolve_session

UNAUTHENTICATED_MESSAGE = "authentication required"
MISSING_CSRF_HEADER_MESSAGE = "missing required header"
CSRF_HEADER_NAME = "x-requested-with"
CSRF_HEADER_VALUE = "XMLHttpRequest"
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _unauthenticated() -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=UNAUTHENTICATED_MESSAGE)


def get_current_user(
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> User:
    cookie_value = request.cookies.get(SESSION_COOKIE_NAME)
    if cookie_value is None:
        raise _unauthenticated()
    config = get_config()
    user_id = resolve_session(
        redis,
        cookie_value,
        secret_key=config.secret_key,
        ttl_seconds=config.session_ttl_seconds,
    )
    if user_id is None:
        raise _unauthenticated()
    user = db.get(User, user_id)
    if user is None:
        raise _unauthenticated()
    return user


def require_csrf_header(request: Request) -> None:
    """Defense-in-depth alongside SameSite=Strict: every mutating /api
    request must carry a header a cross-site form/link can never set."""
    if request.method in _SAFE_METHODS:
        return
    if request.headers.get(CSRF_HEADER_NAME) != CSRF_HEADER_VALUE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=MISSING_CSRF_HEADER_MESSAGE
        )
