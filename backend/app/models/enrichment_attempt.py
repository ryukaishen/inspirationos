import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class EnrichmentSource(enum.Enum):
    oembed = "oembed"
    og = "og"


class EnrichmentStatus(enum.Enum):
    success = "success"
    blocked = "blocked"
    not_found = "not_found"
    error = "error"
    disabled = "disabled"


class EnrichmentAttempt(Base):
    """Full audit trail of every oEmbed/OpenGraph fetch attempt.

    One row per attempted source per item per run — never skipped, never
    overwritten. Caching (skip a source once it has a `success`/`not_found`
    row) is a query over this table, not a mutation of it. `error` is the
    exception class name only, never message text.
    """

    __tablename__ = "enrichment_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=False)
    source: Mapped[EnrichmentSource] = mapped_column(
        Enum(
            EnrichmentSource,
            name="enrichment_source",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )
    status: Mapped[EnrichmentStatus] = mapped_column(
        Enum(
            EnrichmentStatus,
            name="enrichment_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )
    http_status: Mapped[int | None] = mapped_column(Integer)
    fetched_title: Mapped[str | None] = mapped_column(Text)
    fetched_caption: Mapped[str | None] = mapped_column(Text)
    fetched_author: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
