"""full-text search index for Milestone 4 (inspiration inbox)

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-18

Purely additive: one GIN expression index over the concatenation of
share_text/adjacent_text/context_note, so `GET /api/items?search=...` can use
Postgres full-text search. The expression must stay textually identical to
`app.api.items._fts_document()` for the planner to use this index.

Uses `coalesce(...) || ' ' || coalesce(...)` rather than `concat(...)`:
`concat()` is not IMMUTABLE-eligible for a Postgres expression index (fails
with "functions in index expression must be marked IMMUTABLE"), whereas the
`||` concatenation operator over `coalesce`-defaulted text is.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX_NAME = "ix_items_fts"
FTS_EXPRESSION = (
    "to_tsvector('english', coalesce(share_text, '') || ' ' || "
    "coalesce(adjacent_text, '') || ' ' || coalesce(context_note, ''))"
)


def upgrade() -> None:
    op.execute(f"CREATE INDEX {INDEX_NAME} ON items USING GIN ({FTS_EXPRESSION})")


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {INDEX_NAME}")
