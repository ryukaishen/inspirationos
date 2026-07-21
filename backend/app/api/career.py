"""Career profile (M7): the singleton grounding context for generation.

Seeded empty by migration 0007 so GET always has a row; PUT replaces the
editable fields wholesale (it's one small form, not a partial patch surface).
The profile is private user data — it flows into prompt contexts only, never
into logs or ai_requests.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db_session
from app.models.career_profile import CareerProfile
from app.schemas.career import CareerProfileRead, CareerProfileUpdate
from app.services.generation.projects import CAREER_PROFILE_ID

router = APIRouter(prefix="/career-profile", tags=["career"])

PROFILE_NOT_FOUND_MESSAGE = "career profile row not found"

DbSession = Annotated[Session, Depends(get_db_session)]


def _get_profile_or_404(db: Session) -> CareerProfile:
    profile = db.get(CareerProfile, CAREER_PROFILE_ID)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=PROFILE_NOT_FOUND_MESSAGE)
    return profile


@router.get("", response_model=CareerProfileRead)
def get_career_profile(db: DbSession) -> CareerProfile:
    return _get_profile_or_404(db)


@router.put("", response_model=CareerProfileRead)
def update_career_profile(body: CareerProfileUpdate, db: DbSession) -> CareerProfile:
    profile = _get_profile_or_404(db)
    profile.background_md = body.background_md
    profile.skills = list(body.skills)
    profile.target_domains = list(body.target_domains)
    profile.experience_level = body.experience_level
    profile.constraints = dict(body.constraints)
    profile.interests_md = body.interests_md
    db.commit()
    return profile
