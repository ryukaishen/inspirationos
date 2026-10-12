"""Pure enrichment policy: rate limiting, circuit breaking, response
classification, generation-eligibility, and needs_context auto-assignment.

No services needed — TokenBucket/CircuitBreaker take injectable clock/sleep,
and the needs_context wiring is exercised directly against
`build_item_drafts` with a hand-built ParsedThread (both plain dataclasses,
no ZIP fixture required) rather than via the shared fixture_builder ZIPs,
so this suite can't disturb their exact-count assertions elsewhere.
"""

from datetime import UTC, datetime

import pytest

from app.models.app_settings import AppSettings
from app.models.enrichment_attempt import EnrichmentStatus
from app.models.item import Item, ItemStatus
from app.services.enrichment.policy import (
    CircuitBreaker,
    TokenBucket,
    classify_response,
    consent_given,
    initial_status_for,
    is_eligible_for_generation,
)
from app.services.ingest.instagram.export_reader import ParsedMessage, ParsedThread
from app.services.ingest.instagram.parser import build_item_drafts

# --- TokenBucket -----------------------------------------------------------


def test_token_bucket_waits_for_the_computed_interval() -> None:
    now = [0.0]
    slept: list[float] = []

    def clock() -> float:
        return now[0]

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += seconds

    bucket = TokenBucket(60, capacity=1, clock=clock, sleep=sleep)
    bucket.acquire()  # bucket starts full: no wait
    bucket.acquire()  # one token/second: must wait ~1s for the next one
    assert slept == [pytest.approx(1.0)]


def test_token_bucket_does_not_sleep_while_capacity_remains() -> None:
    now = [0.0]
    slept: list[float] = []
    bucket = TokenBucket(60, capacity=5, clock=lambda: now[0], sleep=slept.append)
    for _ in range(5):
        bucket.acquire()
    assert slept == []


def test_token_bucket_rejects_non_positive_rate() -> None:
    with pytest.raises(ValueError, match="rate_per_minute"):
        TokenBucket(0)


# --- CircuitBreaker ----------------------------------------------------------


def test_circuit_breaker_trips_after_consecutive_blocked() -> None:
    breaker = CircuitBreaker(threshold=3)
    breaker.record(EnrichmentStatus.blocked)
    breaker.record(EnrichmentStatus.blocked)
    assert breaker.is_open is False
    breaker.record(EnrichmentStatus.blocked)
    assert breaker.is_open is True


def test_circuit_breaker_resets_on_non_blocked_result() -> None:
    breaker = CircuitBreaker(threshold=2)
    breaker.record(EnrichmentStatus.blocked)
    breaker.record(EnrichmentStatus.success)
    breaker.record(EnrichmentStatus.blocked)
    assert breaker.is_open is False


def test_circuit_breaker_rejects_non_positive_threshold() -> None:
    with pytest.raises(ValueError, match="threshold"):
        CircuitBreaker(0)


# --- classify_response --------------------------------------------------------


@pytest.mark.parametrize(
    ("http_status", "expected"),
    [
        (200, EnrichmentStatus.success),
        (404, EnrichmentStatus.not_found),
        (401, EnrichmentStatus.blocked),
        (403, EnrichmentStatus.blocked),
        (429, EnrichmentStatus.blocked),
        (999, EnrichmentStatus.blocked),
        (500, EnrichmentStatus.error),
    ],
)
def test_classify_response_by_http_status(http_status: int, expected: EnrichmentStatus) -> None:
    assert classify_response(http_status, None) is expected


def test_classify_response_exception_is_always_error() -> None:
    assert classify_response(None, RuntimeError("boom")) is EnrichmentStatus.error


# --- is_eligible_for_generation ------------------------------------------------


def _item(**overrides: str | None) -> Item:
    fields: dict[str, str | None] = {
        "share_text": None,
        "adjacent_text": None,
        "enriched_caption": None,
        "context_note": None,
        "transcript": None,
        "visual_text": None,
    }
    fields.update(overrides)
    return Item(**fields)  # type: ignore[arg-type]


def test_is_eligible_for_generation_requires_at_least_one_nonblank_field() -> None:
    assert is_eligible_for_generation(_item()) is False
    assert is_eligible_for_generation(_item(share_text="   ")) is False  # whitespace-only
    assert is_eligible_for_generation(_item(share_text="a caption")) is True
    assert is_eligible_for_generation(_item(adjacent_text="nearby context")) is True
    assert is_eligible_for_generation(_item(enriched_caption="from oembed")) is True
    assert is_eligible_for_generation(_item(context_note="user note")) is True
    assert is_eligible_for_generation(_item(transcript="spoken words")) is True
    assert is_eligible_for_generation(_item(visual_text="on-screen words")) is True
    assert is_eligible_for_generation(_item(transcript="  ", visual_text="")) is False


# --- initial_status_for (needs_context auto-assignment) -----------------------


@pytest.mark.parametrize(
    ("share_text", "adjacent_text", "expected"),
    [
        (None, None, ItemStatus.needs_context),
        ("", "   ", ItemStatus.needs_context),
        ("a caption", None, ItemStatus.new),
        (None, "nearby context", ItemStatus.new),
    ],
)
def test_initial_status_for(
    share_text: str | None, adjacent_text: str | None, expected: ItemStatus
) -> None:
    assert initial_status_for(share_text, adjacent_text) is expected


def test_build_item_drafts_marks_text_poor_item_needs_context() -> None:
    """Wiring check: a share with no share_text and no nearby same-sender
    text lands in needs_context straight out of the extract pipeline."""
    lone_message = ParsedMessage(
        sender_name="Friend",
        timestamp_ms=1_700_000_000_000,
        content=None,
        share_link="https://www.instagram.com/reel/BAREURL1/",
        share_text=None,
    )
    thread = ParsedThread(
        thread_path="inbox/friend",
        title="Friend",
        participant_names=("Owner", "Friend"),
        messages=(lone_message,),
    )
    drafts = build_item_drafts(thread, window_seconds=120)
    assert len(drafts) == 1
    assert drafts[0].status is ItemStatus.needs_context


def test_build_item_drafts_marks_item_with_share_text_new() -> None:
    message = ParsedMessage(
        sender_name="Friend",
        timestamp_ms=1_700_000_000_000,
        content=None,
        share_link="https://www.instagram.com/reel/HASCAPTION1/",
        share_text="check this out",
    )
    thread = ParsedThread(
        thread_path="inbox/friend",
        title="Friend",
        participant_names=("Owner", "Friend"),
        messages=(message,),
    )
    drafts = build_item_drafts(thread, window_seconds=120)
    assert drafts[0].status is ItemStatus.new


# --- consent_given -----------------------------------------------------------


def _settings(**overrides: object) -> AppSettings:
    fields: dict[str, object] = {"enrichment_enabled": False, "enrichment_consent_at": None}
    fields.update(overrides)
    return AppSettings(**fields)  # type: ignore[arg-type]


def test_consent_given_requires_enabled_and_a_consent_timestamp() -> None:
    assert consent_given(_settings()) is False
    assert consent_given(_settings(enrichment_enabled=True)) is False
    assert (
        consent_given(_settings(enrichment_enabled=True, enrichment_consent_at=datetime.now(UTC)))
        is True
    )
    assert (
        consent_given(_settings(enrichment_enabled=False, enrichment_consent_at=datetime.now(UTC)))
        is False
    )
