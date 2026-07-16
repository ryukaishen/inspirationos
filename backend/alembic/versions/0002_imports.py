"""imports table for Milestone 2 (secure upload pipeline)

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-15

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

IMPORT_STATUSES = (
    "uploaded",
    "scanning",
    "scanned",
    "extracting",
    "extracted",
    "failed",
    "deleted",
)
EXPORT_FORMATS = ("json", "html_detected")


def upgrade() -> None:
    op.create_table(
        "imports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(32), nullable=False, server_default="instagram"),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("storage_key", sa.String(255), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("checksum_sha256", sa.String(64), nullable=False),
        sa.Column("export_format", sa.Enum(*EXPORT_FORMATS, name="export_format"), nullable=False),
        sa.Column(
            "status",
            sa.Enum(*IMPORT_STATUSES, name="import_status"),
            nullable=False,
            server_default="uploaded",
        ),
        sa.Column(
            "counts", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    # Authoritative checksum dedupe: only "active" rows participate, so failed
    # rejections and deleted imports never block a legitimate re-upload.
    op.create_index(
        "uq_imports_checksum_active",
        "imports",
        ["checksum_sha256"],
        unique=True,
        postgresql_where=sa.text("status NOT IN ('failed', 'deleted')"),
    )


def downgrade() -> None:
    op.drop_index("uq_imports_checksum_active", table_name="imports")
    op.drop_table("imports")
    op.execute("DROP TYPE IF EXISTS import_status")
    op.execute("DROP TYPE IF EXISTS export_format")
