"""Login/logout/session behavior (M9) against real Postgres + Redis."""

import pytest
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy.orm import Session

from app.config import get_config
from app.db import get_db_session
from app.main import app
from app.models.user import User
from app.redis_client import get_redis
from tests.conftest import TEST_USER_EMAIL, TEST_USER_PASSWORD

pytestmark = pytest.mark.integration

CSRF_HEADERS = {"X-Requested-With": "XMLHttpRequest"}


@pytest.fixture(autouse=True)
def _reset_login_rate_limit(redis_client: Redis) -> None:
    """The rate limiter lives in real Redis, which — unlike Postgres's
    per-test savepoint — is never rolled back between tests; without this,
    a deliberately-tripped limiter in one test leaks into the next."""
    for key in redis_client.scan_iter(match="login_attempts:*"):
        redis_client.delete(key)


def test_login_succeeds_and_sets_session_cookie(anon_client: TestClient, test_user: User) -> None:
    response = anon_client.post(
        "/api/auth/login",
        json={"email": TEST_USER_EMAIL, "password": TEST_USER_PASSWORD},
        headers=CSRF_HEADERS,
    )
    assert response.status_code == 200
    assert response.json() == {"id": test_user.id, "email": TEST_USER_EMAIL}
    assert "session_id" in anon_client.cookies


def test_login_rejects_wrong_password(anon_client: TestClient, test_user: User) -> None:
    response = anon_client.post(
        "/api/auth/login",
        json={"email": TEST_USER_EMAIL, "password": "not-the-password"},
        headers=CSRF_HEADERS,
    )
    assert response.status_code == 401
    assert "session_id" not in anon_client.cookies


def test_login_rejects_unknown_email(anon_client: TestClient) -> None:
    response = anon_client.post(
        "/api/auth/login",
        json={"email": "nobody@example.com", "password": "whatever"},
        headers=CSRF_HEADERS,
    )
    assert response.status_code == 401


def test_login_requires_csrf_header(anon_client: TestClient, test_user: User) -> None:
    # anon_client carries a default CSRF header (useful for every other
    # negative-auth test); this test needs a client without one, but reuses
    # anon_client's already-active dependency overrides on `app`.
    with TestClient(app) as headerless_client:
        response = headerless_client.post(
            "/api/auth/login", json={"email": TEST_USER_EMAIL, "password": TEST_USER_PASSWORD}
        )
    assert response.status_code == 403


def test_login_rate_limited_after_repeated_failures(
    anon_client: TestClient, test_user: User
) -> None:
    max_attempts = get_config().login_rate_limit_attempts
    for _ in range(max_attempts):
        response = anon_client.post(
            "/api/auth/login",
            json={"email": TEST_USER_EMAIL, "password": "wrong"},
            headers=CSRF_HEADERS,
        )
        assert response.status_code == 401
    limited = anon_client.post(
        "/api/auth/login",
        json={"email": TEST_USER_EMAIL, "password": "wrong"},
        headers=CSRF_HEADERS,
    )
    assert limited.status_code == 429
    # Even the *correct* password is blocked while the window is open.
    still_limited = anon_client.post(
        "/api/auth/login",
        json={"email": TEST_USER_EMAIL, "password": TEST_USER_PASSWORD},
        headers=CSRF_HEADERS,
    )
    assert still_limited.status_code == 429


def test_me_requires_session(anon_client: TestClient) -> None:
    response = anon_client.get("/api/auth/me")
    assert response.status_code == 401


def test_me_returns_current_user(client: TestClient, test_user: User) -> None:
    response = client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.json()["email"] == TEST_USER_EMAIL


def test_logout_revokes_session_immediately(client: TestClient) -> None:
    assert client.get("/api/auth/me").status_code == 200
    logout_response = client.post("/api/auth/logout", headers=CSRF_HEADERS)
    assert logout_response.status_code == 204
    assert client.get("/api/auth/me").status_code == 401


def test_logout_without_a_session_is_a_noop(anon_client: TestClient) -> None:
    response = anon_client.post("/api/auth/logout", headers=CSRF_HEADERS)
    assert response.status_code == 204


def test_session_survives_a_fresh_app_instance(
    db_session: Session, redis_client: Redis, test_user: User
) -> None:
    """Sessions live in Redis, not in-process state — a brand new TestClient
    (standing in for a restarted backend process) sharing only the Redis
    connection must still resolve a session created before it existed."""
    app.dependency_overrides[get_db_session] = lambda: db_session
    app.dependency_overrides[get_redis] = lambda: redis_client
    try:
        with TestClient(app) as first_client:
            first_client.headers.update(CSRF_HEADERS)
            login = first_client.post(
                "/api/auth/login",
                json={"email": TEST_USER_EMAIL, "password": TEST_USER_PASSWORD},
            )
            assert login.status_code == 200
            cookie_value = first_client.cookies["session_id"]

        with TestClient(app) as second_client:
            second_client.cookies.set("session_id", cookie_value)
            response = second_client.get("/api/auth/me")
            assert response.status_code == 200
            assert response.json()["email"] == TEST_USER_EMAIL
    finally:
        app.dependency_overrides.clear()
