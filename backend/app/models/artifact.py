"""Versioned per-project artifacts (table created in M7 for the Advisor).

M7 writes `advisor_review` rows (structured data in `payload`, rendered
markdown in `content_md`); M8 adds the other kinds using the same table plus
`claims_flags` (regex-flagged suspicious performance claims — see
`services/generation/claims_guard.py`; empty for `advisor_review`, which
critiques ideas rather than reporting measured results).
Regeneration appends a new version — earlier versions are never overwritten.
`content_md`/`payload` are generated from private text: never in logs.
"""

import enum
from typing import Any

from sqlalchemy import Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin


class ArtifactKind(enum.Enum):
    readme = "readme"
    resume_bullets = "resume_bullets"
    portfolio_desc = "portfolio_desc"
    interview_answer = "interview_answer"
    tech_questions = "tech_questions"
    advisor_review = "advisor_review"


class Artifact(Base, CreatedAtMixin):
    __tablename__ = "artifacts"
    __table_args__ = (Index("ix_artifacts_project_kind", "project_id", "kind"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[ArtifactKind] = mapped_column(
        Enum(ArtifactKind, name="artifact_kind", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    content_md: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(16), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    claims_flags: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
