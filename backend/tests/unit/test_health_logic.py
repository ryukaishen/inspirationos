"""Health endpoint status logic — no services needed (checks are monkeypatched)."""

import pytest
from fastapi.testclient import TestClient

from app.api import health as health_module
from app.main import app


def _get_health(monkeypatch: pytest.MonkeyPatch, db_ok: bool, redis_ok: bool) -> tuple[int, dict]:
    monkeypatch.setattr(health_module, "check_db", lambda: db_ok)
    monkeypatch.setattr(health_module, "check_redis", lambda: redis_ok)
    with TestClient(app) as client:
        response = client.get("/api/health")
    return response.status_code, response.json()


def test_ok_when_both_healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    status_code, body = _get_health(monkeypatch, db_ok=True, redis_ok=True)
    assert status_code == 200
    assert body == {"status": "ok", "db": "healthy", "redis": "healthy"}


def test_degraded_when_db_down(monkeypatch: pytest.MonkeyPatch) -> None:
    status_code, body = _get_health(monkeypatch, db_ok=False, redis_ok=True)
    assert status_code == 503
    assert body == {"status": "degraded", "db": "unreachable", "redis": "healthy"}


def test_degraded_when_redis_down(monkeypatch: pytest.MonkeyPatch) -> None:
    status_code, body = _get_health(monkeypatch, db_ok=True, redis_ok=False)
    assert status_code == 503
    assert body == {"status": "degraded", "db": "healthy", "redis": "unreachable"}
