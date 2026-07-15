"""/api/health against real Postgres and Redis."""

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


def test_health_reports_ok_with_live_services(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "healthy", "redis": "healthy"}
