"""Settings: the enrichment consent gate (M5), AI provider/model/budget (M6),
and scoring weights (M7; the career profile has its own router, career.py).

API keys are environment-only — they are never read from or written to the DB
and never appear in any request or response body.
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db_session
from app.models.app_settings import AppSettings
from app.schemas.settings import (
    AiSettingsUpdateRequest,
    EnrichmentToggleRequest,
    ScoringWeightsUpdateRequest,
    SettingsRead,
)
from app.services.generation.scoring import InvalidWeightsError, validate_weights

router = APIRouter(prefix="/settings", tags=["settings"])

SETTINGS_ID = 1
SETTINGS_NOT_FOUND_MESSAGE = "settings row not found"

DbSession = Annotated[Session, Depends(get_db_session)]


def _get_settings_or_404(db: Session) -> AppSettings:
    settings = db.get(AppSettings, SETTINGS_ID)
    if settings is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=SETTINGS_NOT_FOUND_MESSAGE
        )
    return settings


@router.get("", response_model=SettingsRead)
def get_settings(db: DbSession) -> AppSettings:
    return _get_settings_or_404(db)


@router.patch("/enrichment", response_model=SettingsRead)
def update_enrichment_settings(body: EnrichmentToggleRequest, db: DbSession) -> AppSettings:
    """Flips the toggle; enabling it for the first time (false -> true)
    stamps the consent timestamp. This endpoint never enqueues anything —
    enabling enrichment triggers zero outbound requests on its own, only an
    explicit Enrich action does."""
    settings = _get_settings_or_404(db)
    if body.enrichment_enabled and not settings.enrichment_enabled:
        settings.enrichment_consent_at = datetime.now(UTC)
    settings.enrichment_enabled = body.enrichment_enabled
    db.commit()
    return settings


@router.patch("/ai", response_model=SettingsRead)
def update_ai_settings(body: AiSettingsUpdateRequest, db: DbSession) -> AppSettings:
    """Provider / model-override / budget settings (M6). Partial update:
    only fields present in the body are applied. Switching provider is
    configuration-only — no job is enqueued and no network call happens."""
    settings = _get_settings_or_404(db)
    fields = body.model_dump(exclude_unset=True)
    if "ai_provider" in fields and body.ai_provider is not None:
        settings.ai_provider = body.ai_provider
    if "model_overrides" in fields:
        overrides = body.model_overrides
        settings.model_overrides = (
            {tier: name for tier, name in overrides.model_dump().items() if name}
            if overrides is not None
            else {}
        )
    if "monthly_budget_usd" in fields:
        settings.monthly_budget_usd = body.monthly_budget_usd
    db.commit()
    return settings


@router.patch("/scoring", response_model=SettingsRead)
def update_scoring_weights(body: ScoringWeightsUpdateRequest, db: DbSession) -> AppSettings:
    """Replace the scoring-weights mapping (M7). Changing weights re-ranks the
    project library instantly on the client — stored sub-scores never change
    and no generation job is enqueued here."""
    settings = _get_settings_or_404(db)
    try:
        settings.scoring_weights = validate_weights(body.scoring_weights)
    except InvalidWeightsError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_weights", "message": str(exc)},
        ) from exc
    db.commit()
    return settings
