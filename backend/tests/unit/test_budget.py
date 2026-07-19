"""Budget enforcement math (M6): month windows, caps, cost table, token
tracker. Pure unit tests — DB-backed spend summation is exercised in
tests/workers/test_analysis_jobs.py."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.config import AppConfig
from app.models.app_settings import AppSettings
from app.services.ai.budget import (
    DEFAULT_PRICING_USD_PER_MTOK,
    BudgetExceededError,
    JobTokenBudgetExceededError,
    JobTokenTracker,
    check_monthly_budget,
    effective_monthly_cap_usd,
    estimate_cost_usd,
    month_start,
)


def _config(**overrides: object) -> AppConfig:
    return AppConfig(_env_file=None, **overrides)  # type: ignore[arg-type]


class SpendSession:
    def __init__(self, spend: float) -> None:
        self._spend = spend

    def scalar(self, stmt: object) -> float:
        return self._spend


# --- month window ------------------------------------------------------------


def test_month_start_truncates_to_first_of_month_utc() -> None:
    now = datetime(2026, 7, 18, 13, 45, 12, tzinfo=UTC)
    assert month_start(now) == datetime(2026, 7, 1, tzinfo=UTC)


def test_month_start_converts_non_utc_timezones() -> None:
    # 2026-08-01T03:30+05:30 is still 2026-07-31 in UTC.
    now = datetime(2026, 8, 1, 3, 30, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    assert month_start(now) == datetime(2026, 7, 1, tzinfo=UTC)


# --- cost estimation ---------------------------------------------------------


def test_mock_provider_costs_nothing() -> None:
    assert estimate_cost_usd("mock", "mock-llm-v1", 1_000_000, 1_000_000) == 0.0


def test_known_model_pricing_math() -> None:
    # claude-haiku-4-5: $1 in / $5 out per MTok.
    cost = estimate_cost_usd("anthropic", "claude-haiku-4-5", 1_000_000, 200_000)
    assert cost == pytest.approx(1.0 + 1.0)


def test_unknown_model_uses_conservative_default() -> None:
    input_rate, output_rate = DEFAULT_PRICING_USD_PER_MTOK
    cost = estimate_cost_usd("anthropic", "some-future-model", 1_000_000, 0)
    assert cost == pytest.approx(input_rate)
    assert output_rate > input_rate


# --- monthly cap -------------------------------------------------------------


def test_effective_cap_prefers_db_settings_over_env() -> None:
    config = _config(ai_monthly_budget_usd=10.0)
    assert effective_monthly_cap_usd(None, config) == 10.0
    assert effective_monthly_cap_usd(AppSettings(monthly_budget_usd=3.5), config) == 3.5
    # NULL in the DB falls back to the env default.
    assert effective_monthly_cap_usd(AppSettings(monthly_budget_usd=None), config) == 10.0


def test_check_monthly_budget_allows_below_cap() -> None:
    check_monthly_budget(SpendSession(9.99), None, _config(ai_monthly_budget_usd=10.0))  # type: ignore[arg-type]


def test_check_monthly_budget_raises_at_cap() -> None:
    with pytest.raises(BudgetExceededError):
        check_monthly_budget(SpendSession(10.0), None, _config(ai_monthly_budget_usd=10.0))  # type: ignore[arg-type]


# --- per-job token budget ----------------------------------------------------


def test_token_tracker_trips_only_once_budget_is_reached() -> None:
    tracker = JobTokenTracker(1000)
    tracker.check()
    tracker.record(400, 100)
    tracker.check()  # 500 < 1000
    tracker.record(400, 100)
    with pytest.raises(JobTokenBudgetExceededError):
        tracker.check()  # 1000 >= 1000


def test_token_tracker_rejects_nonpositive_budget() -> None:
    with pytest.raises(ValueError):
        JobTokenTracker(0)
