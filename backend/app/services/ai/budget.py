"""Cost controls (M6): monthly USD cap + per-job token budget + cost estimates.

Checked before every provider call (see structured.py). Spend is the SUM of
`ai_requests.est_cost_usd` over the current UTC calendar month — the session's
autoflush means uncommitted rows from the running job count too, so a batch
cannot overshoot the cap between commits.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import AppConfig
from app.models.ai_request import AiRequest
from app.models.app_settings import AppSettings


class BudgetExceededError(Exception):
    """Monthly USD budget reached; the batch aborts cleanly."""


class JobTokenBudgetExceededError(Exception):
    """Per-job cumulative token budget reached; the batch aborts cleanly."""


# USD per million tokens (input, output). Estimates for observability and the
# budget guardrail — not a billing source of truth. Anthropic prices verified
# 2026-07-18 (Sonnet 5 standard rate); OpenAI prices are best-effort estimates.
PRICING_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-sonnet-5": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "gpt-5.2": (1.25, 10.0),
    "gpt-5-mini": (0.25, 2.0),
    "text-embedding-3-small": (0.02, 0.0),
}
# Unknown model: assume Opus-tier pricing so the cap errs on the safe side.
DEFAULT_PRICING_USD_PER_MTOK: tuple[float, float] = (5.0, 25.0)


def estimate_cost_usd(
    provider: str, model: str, prompt_tokens: int, completion_tokens: int
) -> float:
    if provider == "mock":
        return 0.0
    input_rate, output_rate = PRICING_USD_PER_MTOK.get(model, DEFAULT_PRICING_USD_PER_MTOK)
    return (prompt_tokens * input_rate + completion_tokens * output_rate) / 1_000_000


def month_start(now: datetime) -> datetime:
    now_utc = now.astimezone(UTC)
    return now_utc.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def monthly_spend_usd(session: Session, now: datetime | None = None) -> float:
    spent = session.scalar(
        select(func.coalesce(func.sum(AiRequest.est_cost_usd), 0)).where(
            AiRequest.created_at >= month_start(now or datetime.now(UTC))
        )
    )
    return float(spent or 0)


def effective_monthly_cap_usd(settings: AppSettings | None, config: AppConfig) -> float:
    if settings is not None and settings.monthly_budget_usd is not None:
        return float(settings.monthly_budget_usd)
    return config.ai_monthly_budget_usd


def check_monthly_budget(
    session: Session,
    settings: AppSettings | None,
    config: AppConfig,
    now: datetime | None = None,
) -> None:
    """Raises BudgetExceededError when this month's spend has reached the cap."""
    cap = effective_monthly_cap_usd(settings, config)
    if monthly_spend_usd(session, now) >= cap:
        raise BudgetExceededError(f"monthly AI budget of ${cap:.2f} reached")


class JobTokenTracker:
    """Cumulative token cap for one job run; constructed per job execution."""

    def __init__(self, budget_tokens: int) -> None:
        if budget_tokens <= 0:
            raise ValueError("budget_tokens must be positive")
        self._budget = budget_tokens
        self._used = 0

    @property
    def used(self) -> int:
        return self._used

    def record(self, prompt_tokens: int, completion_tokens: int) -> None:
        self._used += prompt_tokens + completion_tokens

    def check(self) -> None:
        if self._used >= self._budget:
            raise JobTokenBudgetExceededError(f"job token budget of {self._budget} tokens reached")
