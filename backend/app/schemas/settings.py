from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SettingsRead(BaseModel):
    """Enrichment-only view of the settings singleton — ai_provider,
    scoring_weights, etc. are out of scope until M6/M7 add their own UI."""

    model_config = ConfigDict(from_attributes=True)

    enrichment_enabled: bool
    enrichment_consent_at: datetime | None


class EnrichmentToggleRequest(BaseModel):
    enrichment_enabled: bool
