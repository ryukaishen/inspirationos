"""Shared fixtures.

Service-dependent fixtures skip with an explicit message when Postgres/Redis
are unreachable locally; CI always runs them (service containers), so skips
can't hide failures.
"""

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
from app.redis_client import get_redis

BACKEND_DIR = Path(__file__).resolve().parents[1]

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
def client(db_session: Session, redis_client: Redis) -> Generator[TestClient, None, None]:
    app.dependency_overrides[get_db_session] = lambda: db_session
    app.dependency_overrides[get_redis] = lambda: redis_client
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
