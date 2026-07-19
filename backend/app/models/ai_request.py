"""Per-LLM-call audit rows (M6): cost observability without content.

Content-free by construction — this table has no text/prompt/response columns
at all, so the "never log message content" rule cannot be violated here. One
row per provider call, including repair retries and failures.
"""

import enum

from sqlalchemy import Enum, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin


class AiRequestStatus(enum.Enum):
    success = "success"
    invalid_output = "invalid_output"
    error = "error"


class AiRequest(Base, CreatedAtMixin):
    __tablename__ = "ai_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"))
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    task: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    est_cost_usd: Mapped[float] = mapped_column(Numeric(10, 6), nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[AiRequestStatus] = mapped_column(
        Enum(
            AiRequestStatus,
            name="ai_request_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )
