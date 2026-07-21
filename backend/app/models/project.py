"""Project workspace tables (M7): generated projects and roadmap milestones.

`scores` holds the five fixed sub-scores (0-10, each with a one-line
rationale); the final score is computed at read time from
`settings.scoring_weights` and is never stored. `source` records provenance
(item_ids/cluster_ids verified server-side at generation time, plus
prompt_version/provider/model). `parent_project_ids` links a combined idea to
both parents. Generated text fields derive from private message text — never
in logs, errors, or job payloads.
"""

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import Date, Enum, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UpdatedAtMixin


class ProjectStatus(enum.Enum):
    idea = "idea"
    shortlisted = "shortlisted"
    planned = "planned"
    in_progress = "in_progress"
    completed = "completed"
    archived = "archived"


class Project(Base, CreatedAtMixin, UpdatedAtMixin):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    one_liner: Mapped[str] = mapped_column(Text, nullable=False)
    summary_md: Mapped[str] = mapped_column(Text, nullable=False)
    domains: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default=text("'{}'::text[]")
    )
    difficulty: Mapped[str | None] = mapped_column(String(32))
    duration_estimate: Mapped[str | None] = mapped_column(String(128))
    datasets: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    tech_stack: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    skills_demonstrated: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    risks: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    scores: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    status: Mapped[ProjectStatus] = mapped_column(
        Enum(ProjectStatus, name="project_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=ProjectStatus.idea,
        server_default="idea",
    )
    source: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    parent_project_ids: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), nullable=False, default=list, server_default=text("'{}'::integer[]")
    )


class MilestoneStatus(enum.Enum):
    todo = "todo"
    doing = "doing"
    done = "done"


class ProjectMilestone(Base, CreatedAtMixin, UpdatedAtMixin):
    """One roadmap step; `sort_order` is contiguous 0..n per project and is
    rewritten wholesale by the reorder endpoint."""

    __tablename__ = "project_milestones"
    __table_args__ = (Index("ix_project_milestones_project_id", "project_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    status: Mapped[MilestoneStatus] = mapped_column(
        Enum(
            MilestoneStatus, name="milestone_status", values_callable=lambda e: [m.value for m in e]
        ),
        nullable=False,
        default=MilestoneStatus.todo,
        server_default="todo",
    )
    target_date: Mapped[datetime | None] = mapped_column(Date)
