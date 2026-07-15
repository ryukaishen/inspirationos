import enum
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, Numeric, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AiProvider(enum.Enum):
    anthropic = "anthropic"
    openai = "openai"
    mock = "mock"


class AppSettings(Base):
    """Singleton row (seeded by the initial migration).

    Consent timestamp records the explicit enrichment opt-in; enrichment is
    OFF by default and only ever enabled through the consent dialog (M5).
    """

    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    enrichment_enabled: Mapped[bool] = mapped_column(
        nullable=False, default=False, server_default="false"
    )
    enrichment_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enrichment_rate_limit: Mapped[int | None]
    ai_provider: Mapped[AiProvider] = mapped_column(
        Enum(AiProvider, name="ai_provider", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=AiProvider.mock,
    )
    model_overrides: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    monthly_budget_usd: Mapped[float | None] = mapped_column(Numeric(8, 2))
    scoring_weights: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    review_prefs: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
