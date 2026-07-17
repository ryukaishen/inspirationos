import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UpdatedAtMixin


class ItemType(enum.Enum):
    reel = "reel"
    post = "post"
    tv = "tv"
    story = "story"
    external = "external"
    unknown = "unknown"


class ItemStatus(enum.Enum):
    new = "new"
    needs_context = "needs_context"
    reviewed = "reviewed"
    archived = "archived"
    ignored = "ignored"


class DuplicateReason(enum.Enum):
    same_shortcode = "same_shortcode"
    same_canonical_url = "same_canonical_url"
    near_text = "near_text"  # embedding-similarity groups arrive with M6


class DuplicateGroup(Base, CreatedAtMixin):
    """Group of items that are the same underlying content, shared repeatedly.

    Exact groups (same shortcode / canonical URL) are rebuilt by every extract
    run; `near_text` groups come from M6 embedding similarity. The canonical
    item is the earliest share.
    """

    __tablename__ = "duplicate_groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    # use_alter breaks the circular FK with items.duplicate_group_id.
    canonical_item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", use_alter=True, name="fk_duplicate_groups_canonical_item"),
        nullable=False,
    )
    reason: Mapped[DuplicateReason] = mapped_column(
        Enum(
            DuplicateReason, name="duplicate_reason", values_callable=lambda e: [m.value for m in e]
        ),
        nullable=False,
    )


class Item(Base, CreatedAtMixin, UpdatedAtMixin):
    """Core inspiration entity: one link occurrence extracted from a message.

    Repeat shares stay separate rows (a "shared again" signal) linked through
    `duplicate_group_id`, so the shortcode index is deliberately non-unique;
    the uniqueness invariant is one item per (message, canonical URL).
    Source FKs are nullable because M9 raw-import deletion may null them while
    keeping the derived item. `share_text`/`adjacent_text`/`context_note` are
    private content — never in logs, errors, or job payloads.
    `embedding`/`embedding_model` columns arrive with M6.
    """

    __tablename__ = "items"
    __table_args__ = (
        Index("ix_items_import_id", "import_id"),
        Index("ix_items_conversation_id", "conversation_id"),
        Index("ix_items_shortcode", "shortcode", postgresql_where=text("shortcode IS NOT NULL")),
        Index(
            "uq_items_message_url",
            "message_id",
            "url_canonical",
            unique=True,
            postgresql_where=text("message_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, default="instagram", server_default="instagram"
    )
    import_id: Mapped[int | None] = mapped_column(ForeignKey("imports.id"))
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id"))
    message_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id"))
    url_raw: Mapped[str] = mapped_column(Text, nullable=False)
    url_canonical: Mapped[str] = mapped_column(Text, nullable=False)
    shortcode: Mapped[str | None] = mapped_column(String(64))
    item_type: Mapped[ItemType] = mapped_column(
        Enum(ItemType, name="item_type", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    shared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    share_text: Mapped[str | None] = mapped_column(Text)
    adjacent_text: Mapped[str | None] = mapped_column(Text)
    enriched_title: Mapped[str | None] = mapped_column(Text)
    enriched_caption: Mapped[str | None] = mapped_column(Text)
    enriched_author: Mapped[str | None] = mapped_column(Text)
    context_note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ItemStatus] = mapped_column(
        Enum(ItemStatus, name="item_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=ItemStatus.new,
        server_default="new",
    )
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default=text("'{}'::text[]")
    )
    duplicate_group_id: Mapped[int | None] = mapped_column(ForeignKey("duplicate_groups.id"))
