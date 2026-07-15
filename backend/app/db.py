"""Synchronous SQLAlchemy engine and session factory.

Sync (not async) by design: RQ workers are synchronous, the app has a single
user, and the frontend polls — an async stack would add complexity without a
concurrency need.
"""

from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_config


@lru_cache
def get_engine() -> Engine:
    return create_engine(
        get_config().database_url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 5},
    )


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_db_session() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a request-scoped session."""
    with get_sessionmaker()() as session:
        yield session
