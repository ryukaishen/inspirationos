"""initial schema: pgvector extension, users, settings (seeded singleton), jobs

Revision ID: 0001
Revises:
Create Date: 2026-07-14

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JOB_KINDS = (
    "demo",
    "import_scan",
    "import_extract",
    "enrich_batch",
    "embed_batch",
    "cluster",
    "topics",
    "generate_projects",
    "generate_artifact",
    "export_bundle",
    "delete_data",
)
JOB_STATUSES = ("queued", "running", "succeeded", "failed", "cancelled")
AI_PROVIDERS = ("anthropic", "openai", "mock")

JSONB_EMPTY = sa.text("'{}'::jsonb")


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_table(
        "settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("enrichment_enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("enrichment_consent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("enrichment_rate_limit", sa.Integer(), nullable=True),
        sa.Column(
            "ai_provider",
            sa.Enum(*AI_PROVIDERS, name="ai_provider"),
            nullable=False,
            server_default="mock",
        ),
        sa.Column(
            "model_overrides", postgresql.JSONB(), nullable=False, server_default=JSONB_EMPTY
        ),
        sa.Column("monthly_budget_usd", sa.Numeric(8, 2), nullable=True),
        sa.Column(
            "scoring_weights", postgresql.JSONB(), nullable=False, server_default=JSONB_EMPTY
        ),
        sa.Column("review_prefs", postgresql.JSONB(), nullable=False, server_default=JSONB_EMPTY),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rq_job_id", sa.String(64), nullable=True),
        sa.Column("kind", sa.Enum(*JOB_KINDS, name="job_kind"), nullable=False),
        sa.Column(
            "status",
            sa.Enum(*JOB_STATUSES, name="job_status"),
            nullable=False,
            server_default="queued",
        ),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default=JSONB_EMPTY),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )

    # settings is a singleton table — seed the one row
    op.execute(
        "INSERT INTO settings (id, enrichment_enabled, ai_provider) VALUES (1, false, 'mock')"
    )


def downgrade() -> None:
    op.drop_table("jobs")
    op.drop_table("settings")
    op.drop_table("users")
    op.execute("DROP TYPE IF EXISTS job_status")
    op.execute("DROP TYPE IF EXISTS job_kind")
    op.execute("DROP TYPE IF EXISTS ai_provider")
