"""parser tables for Milestone 3: conversations, messages, items, duplicate_groups

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-17

Purely additive — no existing table changes, no data backfill. The circular
FK pair (items.duplicate_group_id ↔ duplicate_groups.canonical_item_id) is
resolved by adding the canonical-item constraint after both tables exist.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ITEM_TYPES = ("reel", "post", "tv", "story", "external", "unknown")
ITEM_STATUSES = ("new", "needs_context", "reviewed", "archived", "ignored")
DUPLICATE_REASONS = ("same_shortcode", "same_canonical_url", "near_text")

JSONB_EMPTY_LIST = sa.text("'[]'::jsonb")


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("import_id", sa.Integer(), sa.ForeignKey("imports.id"), nullable=False),
        sa.Column("thread_path", sa.String(512), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column(
            "participant_names",
            postgresql.JSONB(),
            nullable=False,
            server_default=JSONB_EMPTY_LIST,
        ),
        sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("link_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_self_dm_candidate", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_selected", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("first_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("import_id", "thread_path", name="uq_conversations_import_thread"),
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "conversation_id", sa.Integer(), sa.ForeignKey("conversations.id"), nullable=False
        ),
        sa.Column("sender_name", sa.Text(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("share_link", sa.Text(), nullable=True),
        sa.Column("share_text", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_messages_conversation_sent", "messages", ["conversation_id", "sent_at"])

    # canonical_item_id FK is added after items exists (circular reference).
    op.create_table(
        "duplicate_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("canonical_item_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Enum(*DUPLICATE_REASONS, name="duplicate_reason"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_table(
        "items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(32), nullable=False, server_default="instagram"),
        sa.Column("import_id", sa.Integer(), sa.ForeignKey("imports.id"), nullable=True),
        sa.Column(
            "conversation_id", sa.Integer(), sa.ForeignKey("conversations.id"), nullable=True
        ),
        sa.Column("message_id", sa.Integer(), sa.ForeignKey("messages.id"), nullable=True),
        sa.Column("url_raw", sa.Text(), nullable=False),
        sa.Column("url_canonical", sa.Text(), nullable=False),
        sa.Column("shortcode", sa.String(64), nullable=True),
        sa.Column("item_type", sa.Enum(*ITEM_TYPES, name="item_type"), nullable=False),
        sa.Column("shared_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("share_text", sa.Text(), nullable=True),
        sa.Column("adjacent_text", sa.Text(), nullable=True),
        sa.Column("enriched_title", sa.Text(), nullable=True),
        sa.Column("enriched_caption", sa.Text(), nullable=True),
        sa.Column("enriched_author", sa.Text(), nullable=True),
        sa.Column("context_note", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(*ITEM_STATUSES, name="item_status"),
            nullable=False,
            server_default="new",
        ),
        sa.Column(
            "tags",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "duplicate_group_id",
            sa.Integer(),
            sa.ForeignKey("duplicate_groups.id"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_items_import_id", "items", ["import_id"])
    op.create_index("ix_items_conversation_id", "items", ["conversation_id"])
    # Non-unique on purpose: repeat shares are separate rows grouped via
    # duplicate_groups; the uniqueness invariant lives on (message, canonical URL).
    op.create_index(
        "ix_items_shortcode",
        "items",
        ["shortcode"],
        postgresql_where=sa.text("shortcode IS NOT NULL"),
    )
    op.create_index(
        "uq_items_message_url",
        "items",
        ["message_id", "url_canonical"],
        unique=True,
        postgresql_where=sa.text("message_id IS NOT NULL"),
    )

    op.create_foreign_key(
        "fk_duplicate_groups_canonical_item",
        "duplicate_groups",
        "items",
        ["canonical_item_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_duplicate_groups_canonical_item", "duplicate_groups", type_="foreignkey")
    op.drop_table("items")
    op.drop_table("duplicate_groups")
    op.drop_table("messages")
    op.drop_table("conversations")
    op.execute("DROP TYPE IF EXISTS item_type")
    op.execute("DROP TYPE IF EXISTS item_status")
    op.execute("DROP TYPE IF EXISTS duplicate_reason")
