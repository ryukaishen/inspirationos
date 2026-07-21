"""Fabricated-claims guard (M8): pure unit tests, no services."""

import pytest

from app.services.generation.claims_guard import find_claims


def test_flags_the_seeded_achieved_accuracy_claim() -> None:
    flags = find_claims("Our model achieved 97% accuracy on the validation set.")
    assert flags
    assert any("97%" in flag for flag in flags)


def test_flags_reduced_latency_by_percent() -> None:
    flags = find_claims("This service reduced inference latency by 40%.")
    assert any("reduc" in flag.lower() for flag in flags)


def test_flags_bare_percent_metric_phrase() -> None:
    flags = find_claims("The pipeline runs at 92% precision in production.")
    assert any("92%" in flag for flag in flags)


def test_does_not_flag_hedged_target_language() -> None:
    assert find_claims("This project targets 95% accuracy as a stretch goal.") == []


def test_does_not_flag_plain_planning_text() -> None:
    assert find_claims("Planned architecture uses PostgreSQL and FastAPI.") == []


def test_empty_text_returns_no_flags() -> None:
    assert find_claims("") == []


def test_deduplicates_repeated_claims() -> None:
    flags = find_claims("We achieved 97% accuracy. Later, we achieved 97% accuracy again.")
    assert flags.count("achieved 97%") == 1


@pytest.mark.parametrize(
    "text",
    [
        "We plan to reach up to 90% coverage eventually.",
        "The estimated throughput goal is roughly 80% of capacity.",
    ],
)
def test_hedged_achievement_verbs_are_not_flagged(text: str) -> None:
    assert find_claims(text) == []
