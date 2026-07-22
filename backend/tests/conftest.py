"""Shared fixtures.

Service-dependent fixtures skip with an explicit message when Postgres/Redis
are unreachable locally; CI always runs them (service containers), so skips
can't hide failures.
"""

import os

# httpx's TestClient talks plain http://testserver via Python's stdlib
# http.cookiejar, which (unlike a real browser) has no "localhost is a
# secure context" exception and silently drops Secure-flagged cookies. Must
# be set before the first `get_config()` call (module import alone doesn't
# trigger one) — real dev/prod are unaffected, since AppConfig.session_cookie_secure
# defaults to True there.
os.environ.setdefault("SESSION_COOKIE_SECURE", "false")

from collections.abc import Generator
from pathlib import Path

import pytest
from alembic.config import Config as AlembicConfig
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from alembic import command
from app.config import get_config
from app.db import get_db_session
from app.main import app
from app.models.user import User
from app.redis_client import get_redis
from app.services.auth.passwords import hash_password

BACKEND_DIR = Path(__file__).resolve().parents[1]

CSRF_HEADERS = {"X-Requested-With": "XMLHttpRequest"}
TEST_USER_EMAIL = "test@example.com"
TEST_USER_PASSWORD = "correct-horse-battery-staple"

SKIP_PG = "PostgreSQL unreachable at DATABASE_URL — integration test skipped (CI always runs it)"
SKIP_REDIS = "Redis unreachable at REDIS_URL — integration test skipped (CI always runs it)"


@pytest.fixture(scope="session")
def pg_engine() -> Generator[Engine, None, None]:
    engine = create_engine(
        get_config().database_url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 2},
    )
    try:
        with engine.connect():
            pass
    except Exception:
        pytest.skip(SKIP_PG)
    alembic_cfg = AlembicConfig(str(BACKEND_DIR / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.upgrade(alembic_cfg, "head")
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def redis_client() -> Generator[Redis, None, None]:
    client = Redis.from_url(get_config().redis_url, socket_connect_timeout=2, socket_timeout=2)
    try:
        client.ping()
    except Exception:
        pytest.skip(SKIP_REDIS)
    yield client
    client.close()


@pytest.fixture
def db_session(pg_engine: Engine) -> Generator[Session, None, None]:
    """Per-test outer transaction; session commits become savepoints, all rolled back."""
    connection = pg_engine.connect()
    transaction = connection.begin()
    session = Session(
        bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def test_user(db_session: Session) -> User:
    user = User(email=TEST_USER_EMAIL, password_hash=hash_password(TEST_USER_PASSWORD))
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def anon_client(db_session: Session, redis_client: Redis) -> Generator[TestClient, None, None]:
    """Unauthenticated TestClient (still carries the CSRF header) — for the
    auth-negative tests (login itself, route gating, rate limiting) only."""
    app.dependency_overrides[get_db_session] = lambda: db_session
    app.dependency_overrides[get_redis] = lambda: redis_client
    try:
        with TestClient(app) as test_client:
            test_client.headers.update(CSRF_HEADERS)
            yield test_client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def client(
    db_session: Session, redis_client: Redis, test_user: User
) -> Generator[TestClient, None, None]:
    """Pre-authenticated TestClient — a real session cookie plus the CSRF
    header are already set, so the M2-M8 test files (which all use this
    fixture) need zero changes now that M9 gates every non-auth route."""
    app.dependency_overrides[get_db_session] = lambda: db_session
    app.dependency_overrides[get_redis] = lambda: redis_client
    try:
        with TestClient(app) as test_client:
            test_client.headers.update(CSRF_HEADERS)
            login_response = test_client.post(
                "/api/auth/login",
                json={"email": TEST_USER_EMAIL, "password": TEST_USER_PASSWORD},
            )
            assert login_response.status_code == 200, login_response.text
            yield test_client
    finally:
        app.dependency_overrides.clear()
