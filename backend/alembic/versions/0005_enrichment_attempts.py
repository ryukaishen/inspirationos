"""enrichment_attempts table + items.enriched_source for Milestone 5

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-19

Purely additive: a new audit table for oEmbed/OpenGraph fetch attempts, plus
one nullable column on items recording which source produced the current
enriched_* fields (so the UI can label them "via oEmbed"/"via OpenGraph"
without joining enrichment_attempts on every inbox render). The partial index
on (item_id, source) WHERE status IN ('success','not_found') backs the
"never re-fetch a cached result" lookup in services/enrichment/.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENRICHMENT_SOURCES = ("oembed", "og")
ENRICHMENT_STATUSES = ("success", "blocked", "not_found", "error", "disabled")


def upgrade() -> None:
    bind = op.get_bind()
    # Reused by both items.enriched_source and enrichment_attempts.source —
    # create the type once, reference it with create_type=False afterward.
    # The dialect-specific postgresql.ENUM (not the generic sa.Enum) is
    # required here: a generic sa.Enum's create_type=False is not reliably
    # honored when the same type name is reused across a separate
    # add_column and create_table in one migration (confirmed against a
    # live database — the generic Enum re-issues CREATE TYPE and fails with
    # "already exists").
    source_enum = postgresql.ENUM(*ENRICHMENT_SOURCES, name="enrichment_source")
    source_enum.create(bind, checkfirst=True)

    op.add_column(
        "items",
        sa.Column(
            "enriched_source",
            postgresql.ENUM(*ENRICHMENT_SOURCES, name="enrichment_source", create_type=False),
            nullable=True,
        ),
    )

    op.create_table(
        "enrichment_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("item_id", sa.Integer(), sa.ForeignKey("items.id"), nullable=False),
        sa.Column(
            "source",
            postgresql.ENUM(*ENRICHMENT_SOURCES, name="enrichment_source", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(*ENRICHMENT_STATUSES, name="enrichment_status"),
            nullable=False,
        ),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("fetched_title", sa.Text(), nullable=True),
        sa.Column("fetched_caption", sa.Text(), nullable=True),
        sa.Column("fetched_author", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "attempted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_enrichment_attempts_item_id", "enrichment_attempts", ["item_id"])
    op.create_index(
        "ix_enrichment_attempts_item_source_cached",
        "enrichment_attempts",
        ["item_id", "source"],
        postgresql_where=sa.text("status IN ('success', 'not_found')"),
    )


def downgrade() -> None:
    op.drop_table("enrichment_attempts")
    op.drop_column("items", "enriched_source")
    op.execute("DROP TYPE IF EXISTS enrichment_status")
    op.execute("DROP TYPE IF EXISTS enrichment_source")
