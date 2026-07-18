"""Settings: the enrichment consent gate.

Scoped to enrichment only for this milestone — ai_provider/scoring_weights/
career-profile settings arrive with M6/M7's own Settings UI.
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db_session
from app.models.app_settings import AppSettings
from app.schemas.settings import EnrichmentToggleRequest, SettingsRead

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
