from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin


class Message(Base, CreatedAtMixin):
    """One export message, persisted **only for user-selected conversations**.

    Contains private content (`text`, `share_text`) — these fields must never
    appear in logs, error strings, or job payloads (see PRIVACY_SECURITY.md).
    """

    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_conversation_sent", "conversation_id", "sent_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), nullable=False)
    sender_name: Mapped[str] = mapped_column(Text, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    text: Mapped[str | None] = mapped_column(Text)
    share_link: Mapped[str | None] = mapped_column(Text)
    share_text: Mapped[str | None] = mapped_column(Text)
