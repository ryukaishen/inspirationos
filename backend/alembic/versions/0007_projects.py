"""Project workspace tables for Milestone 7

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-19

Purely additive: `career_profile` (singleton, seeded empty so GET always has a
row), `projects`, `project_milestones`, and `artifacts` (created now because
the Advisor writes versioned `advisor_review` rows; M8 reuses the table for
the other kinds). The `generate_projects`/`generate_artifact` job kinds have
existed in the `job_kind` enum since migration 0001 — no enum changes here.
Milestone/artifact FKs cascade on project deletion (the M9 deletion flow
removes a project with its milestones and artifacts).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROJECT_STATUSES = ("idea", "shortlisted", "planned", "in_progress", "completed", "archived")
MILESTONE_STATUSES = ("todo", "doing", "done")
ARTIFACT_KINDS = (
    "readme",
    "resume_bullets",
    "portfolio_desc",
    "interview_answer",
    "tech_questions",
    "advisor_review",
)

JSONB_EMPTY = sa.text("'{}'::jsonb")
JSONB_EMPTY_LIST = sa.text("'[]'::jsonb")
TEXT_ARRAY_EMPTY = sa.text("'{}'::text[]")
INT_ARRAY_EMPTY = sa.text("'{}'::integer[]")


def upgrade() -> None:
    op.create_table(
        "career_profile",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("background_md", sa.Text(), nullable=True),
        sa.Column("skills", postgresql.JSONB(), nullable=False, server_default=JSONB_EMPTY_LIST),
        sa.Column(
            "target_domains",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=TEXT_ARRAY_EMPTY,
        ),
        sa.Column("experience_level", sa.String(64), nullable=True),
        sa.Column("constraints", postgresql.JSONB(), nullable=False, server_default=JSONB_EMPTY),
        sa.Column("interests_md", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    # Seed the singleton so GET /api/career-profile always has a row.
    op.execute("INSERT INTO career_profile (id) VALUES (1)")

    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("one_liner", sa.Text(), nullable=False),
        sa.Column("summary_md", sa.Text(), nullable=False),
        sa.Column(
            "domains",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=TEXT_ARRAY_EMPTY,
        ),
        sa.Column("difficulty", sa.String(32), nullable=True),
        sa.Column("duration_estimate", sa.String(128), nullable=True),
        sa.Column("datasets", postgresql.JSONB(), nullable=False, server_default=JSONB_EMPTY_LIST),
        sa.Column(
            "tech_stack", postgresql.JSONB(), nullable=False, server_default=JSONB_EMPTY_LIST
        ),
        sa.Column(
            "skills_demonstrated",
            postgresql.JSONB(),
            nullable=False,
            server_default=JSONB_EMPTY_LIST,
        ),
        sa.Column("risks", postgresql.JSONB(), nullable=False, server_default=JSONB_EMPTY_LIST),
        sa.Column("scores", postgresql.JSONB(), nullable=False, server_default=JSONB_EMPTY),
        sa.Column(
            "status",
            postgresql.ENUM(*PROJECT_STATUSES, name="project_status"),
            nullable=False,
            server_default="idea",
        ),
        sa.Column("source", postgresql.JSONB(), nullable=False, server_default=JSONB_EMPTY),
        sa.Column(
            "parent_project_ids",
            postgresql.ARRAY(sa.Integer()),
            nullable=False,
            server_default=INT_ARRAY_EMPTY,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_table(
        "project_milestones",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "status",
            postgresql.ENUM(*MILESTONE_STATUSES, name="milestone_status"),
            nullable=False,
            server_default="todo",
        ),
        sa.Column("target_date", sa.Date(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_project_milestones_project_id", "project_milestones", ["project_id"])

    op.create_table(
        "artifacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", postgresql.ENUM(*ARTIFACT_KINDS, name="artifact_kind"), nullable=False),
        sa.Column("content_md", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("prompt_version", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_artifacts_project_kind", "artifacts", ["project_id", "kind"])


def downgrade() -> None:
    op.drop_table("artifacts")
    op.drop_table("project_milestones")
    op.drop_table("projects")
    op.drop_table("career_profile")
    op.execute("DROP TYPE IF EXISTS artifact_kind")
    op.execute("DROP TYPE IF EXISTS milestone_status")
    op.execute("DROP TYPE IF EXISTS project_status")
