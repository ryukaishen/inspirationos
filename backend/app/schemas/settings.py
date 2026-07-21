from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.app_settings import AiProvider


class SettingsRead(BaseModel):
    """Settings singleton: enrichment consent (M5) + AI provider/budget (M6)
    + scoring weights (M7).

    API keys are deliberately absent — they live in the environment only and
    never pass through the API or the DB.
    """

    model_config = ConfigDict(from_attributes=True)

    enrichment_enabled: bool
    enrichment_consent_at: datetime | None
    ai_provider: AiProvider
    model_overrides: dict[str, str]
    monthly_budget_usd: float | None
    scoring_weights: dict[str, float]


class ScoringWeightsUpdateRequest(BaseModel):
    """Full replace of the weights mapping. Keys must be known scoring
    dimensions (validated against services/generation/scoring.py); missing
    keys default to 1.0 at read time."""

    scoring_weights: dict[str, float]


class EnrichmentToggleRequest(BaseModel):
    enrichment_enabled: bool


class ModelOverrides(BaseModel):
    """Optional per-tier model name overrides for the active provider."""

    model_config = ConfigDict(extra="forbid")

    generation: str | None = Field(default=None, min_length=1, max_length=128)
    fast: str | None = Field(default=None, min_length=1, max_length=128)


class AiSettingsUpdateRequest(BaseModel):
    """Partial update: only fields present in the request body are applied.
    `monthly_budget_usd: null` clears the override (env default applies)."""

    ai_provider: AiProvider | None = None
    model_overrides: ModelOverrides | None = None
    monthly_budget_usd: float | None = Field(default=None, ge=0)
