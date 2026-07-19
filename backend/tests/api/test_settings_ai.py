"""AI settings API (M6): provider/model-override/budget round-trips.

All mutations happen inside the per-test savepoint, so the shared settings
singleton is untouched afterwards. API keys must never appear in any payload.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.app_settings import AiProvider, AppSettings

pytestmark = pytest.mark.integration


def test_get_settings_exposes_ai_fields_but_never_keys(client: TestClient) -> None:
    response = client.get("/api/settings")
    assert response.status_code == 200
    body = response.json()
    assert body["ai_provider"] in {"anthropic", "openai", "mock"}
    assert isinstance(body["model_overrides"], dict)
    assert "monthly_budget_usd" in body
    for forbidden in ("anthropic_api_key", "openai_api_key", "api_key"):
        assert forbidden not in body


def test_patch_ai_switches_provider_config_only(client: TestClient, db_session: Session) -> None:
    response = client.patch("/api/settings/ai", json={"ai_provider": "anthropic"})
    assert response.status_code == 200
    assert response.json()["ai_provider"] == "anthropic"
    settings = db_session.get(AppSettings, 1)
    assert settings is not None
    db_session.refresh(settings)
    assert settings.ai_provider is AiProvider.anthropic


def test_patch_ai_model_overrides_round_trip(client: TestClient) -> None:
    response = client.patch(
        "/api/settings/ai",
        json={"model_overrides": {"generation": "claude-custom", "fast": "claude-tiny"}},
    )
    assert response.status_code == 200
    assert response.json()["model_overrides"] == {
        "generation": "claude-custom",
        "fast": "claude-tiny",
    }
    # Clearing: explicit null resets to empty overrides.
    response = client.patch("/api/settings/ai", json={"model_overrides": None})
    assert response.status_code == 200
    assert response.json()["model_overrides"] == {}


def test_patch_ai_rejects_unknown_override_tier(client: TestClient) -> None:
    response = client.patch(
        "/api/settings/ai", json={"model_overrides": {"embedding": "not-a-tier"}}
    )
    assert response.status_code == 422


def test_patch_ai_budget_set_and_clear(client: TestClient) -> None:
    response = client.patch("/api/settings/ai", json={"monthly_budget_usd": 5})
    assert response.status_code == 200
    assert response.json()["monthly_budget_usd"] == 5.0
    response = client.patch("/api/settings/ai", json={"monthly_budget_usd": None})
    assert response.status_code == 200
    assert response.json()["monthly_budget_usd"] is None


def test_patch_ai_rejects_negative_budget_and_unknown_provider(client: TestClient) -> None:
    assert client.patch("/api/settings/ai", json={"monthly_budget_usd": -1}).status_code == 422
    assert client.patch("/api/settings/ai", json={"ai_provider": "gemini"}).status_code == 422


def test_patch_ai_partial_update_leaves_other_fields(client: TestClient) -> None:
    client.patch("/api/settings/ai", json={"model_overrides": {"fast": "kept-model"}})
    response = client.patch("/api/settings/ai", json={"monthly_budget_usd": 2})
    assert response.status_code == 200
    body = response.json()
    assert body["model_overrides"] == {"fast": "kept-model"}
    assert body["monthly_budget_usd"] == 2.0
