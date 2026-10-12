"""Pure enrichment policy: rate limiting, circuit breaking, response
classification, and the needs_context / generation-eligibility rules.

No network I/O and no database access here — everything is a plain function
or a small class with an injectable clock/sleep, so it is fully unit-testable
without services (see tests/unit/test_enrichment_policy.py).
"""

from __future__ import annotations

import time
from collections.abc import Callable

from app.models.app_settings import AppSettings
from app.models.enrichment_attempt import EnrichmentStatus
from app.models.item import Item, ItemStatus

_BLOCKED_HTTP_STATUSES = frozenset({401, 403, 429, 999})


class TokenBucket:
    """Token-bucket rate limiter.

    Tokens accrue continuously at `rate_per_minute`/60 per second, capped at
    `capacity` (default: one minute's worth). `acquire()` blocks via the
    injected `sleep` until a token is available. `clock`/`sleep` are
    injectable so tests assert the computed wait time without a real sleep.
    """

    def __init__(
        self,
        rate_per_minute: int,
        *,
        capacity: int | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if rate_per_minute <= 0:
            raise ValueError("rate_per_minute must be positive")
        self._rate_per_second = rate_per_minute / 60.0
        self._capacity = float(capacity if capacity is not None else max(1, rate_per_minute))
        self._clock = clock
        self._sleep = sleep
        self._tokens = self._capacity
        self._last_check = clock()

    def _refill(self) -> None:
        now = self._clock()
        elapsed = max(0.0, now - self._last_check)
        self._last_check = now
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate_per_second)

    def acquire(self) -> None:
        self._refill()
        if self._tokens < 1.0:
            wait_seconds = (1.0 - self._tokens) / self._rate_per_second
            self._sleep(wait_seconds)
            self._refill()
        self._tokens = max(0.0, self._tokens - 1.0)


class CircuitBreaker:
    """Trips after `threshold` consecutive `blocked` classifications.

    Scoped to a single call site (construct one per `run_enrich_batch`
    execution) — never persisted, so every new batch starts closed.
    """

    def __init__(self, threshold: int) -> None:
        if threshold <= 0:
            raise ValueError("threshold must be positive")
        self._threshold = threshold
        self._consecutive_blocked = 0

    @property
    def is_open(self) -> bool:
        return self._consecutive_blocked >= self._threshold

    def record(self, status: EnrichmentStatus) -> None:
        if status is EnrichmentStatus.blocked:
            self._consecutive_blocked += 1
        else:
            self._consecutive_blocked = 0


def classify_response(http_status: int | None, exc: Exception | None) -> EnrichmentStatus:
    """Maps one completed (post-retry) fetch outcome to an audit status.

    `exc` is the final exception after retries are exhausted; `http_status`
    is None whenever `exc` is set.
    """
    if exc is not None:
        return EnrichmentStatus.error
    if http_status == 200:
        return EnrichmentStatus.success
    if http_status == 404:
        return EnrichmentStatus.not_found
    if http_status in _BLOCKED_HTTP_STATUSES:
        return EnrichmentStatus.blocked
    return EnrichmentStatus.error


def is_eligible_for_generation(item: Item) -> bool:
    """Anti-hallucination gate (DATA_MODEL.md): an item may enter AI
    generation input only if it carries at least one non-blank text field."""
    candidates = (
        item.share_text,
        item.adjacent_text,
        item.enriched_caption,
        item.context_note,
        item.transcript,
        item.visual_text,
    )
    return any(text is not None and text.strip() for text in candidates)


def initial_status_for(share_text: str | None, adjacent_text: str | None) -> ItemStatus:
    """Status a freshly-extracted item starts at: `needs_context` when it
    carries no share/adjacent text at all, `new` otherwise."""
    has_share = share_text is not None and share_text.strip()
    has_adjacent = adjacent_text is not None and adjacent_text.strip()
    if has_share or has_adjacent:
        return ItemStatus.new
    return ItemStatus.needs_context


def consent_given(settings: AppSettings) -> bool:
    return bool(settings.enrichment_enabled) and settings.enrichment_consent_at is not None
