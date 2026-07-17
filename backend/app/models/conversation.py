from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin


class Conversation(Base, CreatedAtMixin):
    """Summary of one export thread, persisted by the scan pass.

    Summaries only — message bodies become `messages` rows solely for
    conversations the user selects for extraction (two-pass privacy design).
    `thread_path` is derived from the ZIP entry names (`inbox/<dir>`), so it is
    identical across export layout variants and serves as the scan-idempotency
    upsert key together with `import_id`.
    """

    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("import_id", "thread_path", name="uq_conversations_import_thread"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    import_id: Mapped[int] = mapped_column(ForeignKey("imports.id"), nullable=False)
    thread_path: Mapped[str] = mapped_column(String(512), nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    participant_names: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    message_count: Mapped[int] = mapped_column(nullable=False, default=0)
    link_count: Mapped[int] = mapped_column(nullable=False, default=0)
    is_self_dm_candidate: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    is_selected: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    first_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
