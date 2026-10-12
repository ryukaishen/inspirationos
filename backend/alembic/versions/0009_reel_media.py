"""Reel media extraction: transcript + on-screen text

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-12

Additive: `items.transcript` (speech-to-text of the reel's audio) and
`items.visual_text` (on-screen text/diagrams read from sampled frames), both
filled by the operator-run `transcribe-reels` CLI (services/media/). Adds the
`ytdlp` value to `enrichment_source` so captions/authors fetched alongside the
media are labeled by source and audited in `enrichment_attempts`.

The full-text index is rebuilt to cover the new text plus `enriched_caption`;
the expression must stay textually identical to `app.api.items._fts_document()`.

Downgrade drops the columns and restores the 0004 index. Postgres cannot drop
an enum value, so `ytdlp` stays in `enrichment_source` after a downgrade
(harmless: no column can reference it without the code that writes it).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX_NAME = "ix_items_fts"
OLD_FTS_EXPRESSION = (
    "to_tsvector('english', coalesce(share_text, '') || ' ' || "
    "coalesce(adjacent_text, '') || ' ' || coalesce(context_note, ''))"
)
NEW_FTS_EXPRESSION = (
    "to_tsvector('english', coalesce(share_text, '') || ' ' || "
    "coalesce(adjacent_text, '') || ' ' || coalesce(context_note, '') || ' ' || "
    "coalesce(enriched_caption, '') || ' ' || coalesce(transcript, '') || ' ' || "
    "coalesce(visual_text, ''))"
)


def upgrade() -> None:
    op.execute("ALTER TYPE enrichment_source ADD VALUE IF NOT EXISTS 'ytdlp'")
    op.add_column("items", sa.Column("transcript", sa.Text(), nullable=True))
    op.add_column("items", sa.Column("visual_text", sa.Text(), nullable=True))
    op.execute(f"DROP INDEX IF EXISTS {INDEX_NAME}")
    op.execute(f"CREATE INDEX {INDEX_NAME} ON items USING GIN ({NEW_FTS_EXPRESSION})")


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {INDEX_NAME}")
    op.drop_column("items", "visual_text")
    op.drop_column("items", "transcript")
    op.execute(f"CREATE INDEX {INDEX_NAME} ON items USING GIN ({OLD_FTS_EXPRESSION})")
