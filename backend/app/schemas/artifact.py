"""Request/response schemas for the generic career-artifact endpoints (M8).

`CareerArtifactKind` restricts the `{kind}` path parameter to the five
career-artifact kinds — `advisor_review` keeps its own dedicated `/advisor`
endpoints (unchanged from M7), not this generic pair.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.artifact import ArtifactKind


class CareerArtifactKind(StrEnum):
    readme = "readme"
    resume_bullets = "resume_bullets"
    portfolio_desc = "portfolio_desc"
    interview_answer = "interview_answer"
    tech_questions = "tech_questions"


class ArtifactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    kind: ArtifactKind
    version: int
    content_md: str
    payload: dict[str, Any] | None
    claims_flags: list[str]
    provider: str
    model: str
    prompt_version: str
    created_at: datetime
