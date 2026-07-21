"""Career profile singleton (M7): the grounding context for project generation.

One row (id=1, seeded empty by migration 0007) describing the user's
background, skills, target domains, and constraints. Serialized into every
generation/advisor prompt context — sent to the configured LLM provider only,
never logged and never stored in `ai_requests`.
"""

from typing import Any

from sqlalchemy import String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UpdatedAtMixin


class CareerProfile(Base, CreatedAtMixin, UpdatedAtMixin):
    __tablename__ = "career_profile"

    id: Mapped[int] = mapped_column(primary_key=True)
    background_md: Mapped[str | None] = mapped_column(Text)
    skills: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    target_domains: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default=text("'{}'::text[]")
    )
    experience_level: Mapped[str | None] = mapped_column(String(64))
    constraints: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    interests_md: Mapped[str | None] = mapped_column(Text)
