"""Career artifacts and export bundles for Milestone 8

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-20

Purely additive: `artifacts.claims_flags` (regex-flagged suspicious
performance claims, defaulting to an empty list — see
`services/generation/claims_guard.py`) and a new `exports` table for the
Markdown/JSON export job. The `artifact_kind` enum already carries all five
career-artifact kinds and `job_kind` already carries `generate_artifact`/
`export_bundle` (both since migration 0001/0007) — no enum changes to either.
`exports.format` is a new `export_bundle_format` enum, distinct from the
Instagram-import `export_format` enum (json/html_detected) added in 0002.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EXPORT_BUNDLE_FORMATS = ("markdown", "json")

JSONB_EMPTY_LIST = sa.text("'[]'::jsonb")


def upgrade() -> None:
    op.add_column(
        "artifacts",
        sa.Column(
            "claims_flags", postgresql.JSONB(), nullable=False, server_default=JSONB_EMPTY_LIST
        ),
    )

    op.create_table(
        "exports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "job_id",
            sa.Integer(),
            sa.ForeignKey("jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "format",
            postgresql.ENUM(*EXPORT_BUNDLE_FORMATS, name="export_bundle_format"),
            nullable=False,
        ),
        sa.Column("storage_key", sa.String(255), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("exports")
    op.execute("DROP TYPE IF EXISTS export_bundle_format")
    op.drop_column("artifacts", "claims_flags")
