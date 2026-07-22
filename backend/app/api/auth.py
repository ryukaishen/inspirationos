"""Single-user auth (M9): login/logout/me. Sessions are server-side Redis
records delivered via an httpOnly, Secure, SameSite=Strict cookie — see
services/auth/sessions.py. Rate limiting is keyed by the immediate client IP;
in production only Caddy is internet-facing and every request reaches this
backend via the frontend container, so this is effectively a global brake on
login attempts rather than a per-attacker one — an acceptable tradeoff for a
single-user deployment.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.config import get_config
from app.db import get_db_session
from app.models.user import User
from app.redis_client import get_redis
from app.schemas.auth import LoginRequest, UserRead
from app.services.auth.passwords import verify_password
from app.services.auth.rate_limit import is_rate_limited, register_failed_attempt, reset_attempts
from app.services.auth.sessions import SESSION_COOKIE_NAME, create_session, delete_session

router = APIRouter(prefix="/auth", tags=["auth"])

INVALID_CREDENTIALS_MESSAGE = "invalid email or password"
RATE_LIMITED_MESSAGE = "too many login attempts — try again later"

DbSession = Annotated[Session, Depends(get_db_session)]
RedisDep = Annotated[Redis, Depends(get_redis)]


def _client_ip(request: Request) -> str:
    return request.client.host if request.client is not None else "unknown"


def _set_session_cookie(
    response: Response, cookie_value: str, ttl_seconds: int, *, secure: bool
) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=cookie_value,
        max_age=ttl_seconds,
        httponly=True,
        secure=secure,
        samesite="strict",
        path="/",
    )


@router.post("/login", response_model=UserRead)
def login(
    body: LoginRequest, request: Request, response: Response, db: DbSession, redis: RedisDep
) -> User:
    config = get_config()
    client_ip = _client_ip(request)
    if is_rate_limited(redis, client_ip, max_attempts=config.login_rate_limit_attempts):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=RATE_LIMITED_MESSAGE
        )

    user = db.scalar(select(User).where(User.email == body.email))
    if user is None or not verify_password(body.password, user.password_hash):
        register_failed_attempt(
            redis, client_ip, window_seconds=config.login_rate_limit_window_seconds
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=INVALID_CREDENTIALS_MESSAGE
        )

    reset_attempts(redis, client_ip)
    cookie_value = create_session(
        redis,
        user_id=user.id,
        secret_key=config.secret_key,
        ttl_seconds=config.session_ttl_seconds,
    )
    _set_session_cookie(
        response,
        cookie_value,
        config.session_ttl_seconds,
        secure=config.session_cookie_secure,
    )
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, redis: RedisDep) -> None:
    """Idempotent: logging out with no session (or an already-gone one) is a
    no-op, not an error."""
    cookie_value = request.cookies.get(SESSION_COOKIE_NAME)
    if cookie_value is not None:
        delete_session(redis, cookie_value)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")


@router.get("/me", response_model=UserRead)
def me(user: Annotated[User, Depends(get_current_user)]) -> User:
    return user
