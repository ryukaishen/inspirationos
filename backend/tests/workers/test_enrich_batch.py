"""run_enrich_batch: consent re-check, oEmbed -> OG fallback, caching, and
the circuit breaker — against real Postgres; httpx is entirely intercepted
by respx, so no real network calls happen anywhere in this suite.

The worker uses its own connection (`get_sessionmaker()`), bypassing any
per-test transaction, so fixtures here create *really-committed* rows via a
raw `Session(pg_engine)` and clean them up explicitly afterward — the same
pattern `tests/workers/test_import_scan.py` uses for the same reason.
"""

from collections.abc import Callable, Generator
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
import respx
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from app.config import get_config
from app.models.app_settings import AppSettings
from app.models.enrichment_attempt import EnrichmentAttempt, EnrichmentSource, EnrichmentStatus
from app.models.item import Item, ItemStatus, ItemType
from app.models.job import Job, JobKind, JobStatus
from app.workers.jobs import run_enrich_batch

pytestmark = pytest.mark.integration

OEMBED_URL = "https://api.instagram.com/oembed/"


@pytest.fixture
def enabled_settings(pg_engine: Engine) -> Generator[None, None, None]:
    """Real, truly-committed consent. Restored to its prior value after."""
    with Session(pg_engine) as session:
        settings = session.get(AppSettings, 1)
        assert settings is not None
        original_enabled = settings.enrichment_enabled
        original_consent_at = settings.enrichment_consent_at
        settings.enrichment_enabled = True
        settings.enrichment_consent_at = datetime.now(UTC)
        session.commit()
    yield
    with Session(pg_engine) as session:
        settings = session.get(AppSettings, 1)
        assert settings is not None
        settings.enrichment_enabled = original_enabled
        settings.enrichment_consent_at = original_consent_at
        session.commit()


@pytest.fixture
def make_items(pg_engine: Engine) -> Generator[Callable[[int], list[int]], None, None]:
    created: list[int] = []

    def _make(count: int) -> list[int]:
        marker = uuid4().hex[:8]
        with Session(pg_engine, expire_on_commit=False) as session:
            items = [
                Item(
                    url_raw=f"https://www.instagram.com/reel/WRK{marker}{i}/",
                    url_canonical=f"https://www.instagram.com/reel/WRK{marker}{i}/",
                    item_type=ItemType.reel,
                    status=ItemStatus.needs_context,
                )
                for i in range(count)
            ]
            session.add_all(items)
            session.commit()
            ids = [item.id for item in items]
        created.extend(ids)
        return ids

    yield _make
    with Session(pg_engine) as session:
        session.execute(delete(EnrichmentAttempt).where(EnrichmentAttempt.item_id.in_(created)))
        session.execute(delete(Item).where(Item.id.in_(created)))
        session.commit()


@pytest.fixture
def make_job(pg_engine: Engine) -> Generator[Callable[[list[int]], int], None, None]:
    created: list[int] = []

    def _make(item_ids: list[int]) -> int:
        with Session(pg_engine, expire_on_commit=False) as session:
            job = Job(
                kind=JobKind.enrich_batch,
                status=JobStatus.queued,
                total=len(item_ids),
                payload={"item_ids": item_ids},
            )
            session.add(job)
            session.commit()
            job_id = job.id
        created.append(job_id)
        return job_id

    yield _make
    with Session(pg_engine) as session:
        for job_id in created:
            row = session.get(Job, job_id)
            if row is not None:
                session.delete(row)
        session.commit()


def _reload_item(pg_engine: Engine, item_id: int) -> Item:
    with Session(pg_engine) as session:
        item = session.get(Item, item_id)
        assert item is not None
        session.expunge(item)
        return item


def _reload_job(pg_engine: Engine, job_id: int) -> Job:
    with Session(pg_engine) as session:
        job = session.get(Job, job_id)
        assert job is not None
        session.expunge(job)
        return job


def _attempts_for(pg_engine: Engine, item_id: int) -> list[EnrichmentAttempt]:
    with Session(pg_engine) as session:
        rows = list(
            session.scalars(
                select(EnrichmentAttempt)
                .where(EnrichmentAttempt.item_id == item_id)
                .order_by(EnrichmentAttempt.id)
            ).all()
        )
        for row in rows:
            session.expunge(row)
        return rows


@respx.mock
def test_enrich_batch_success_via_oembed(
    enabled_settings: None,
    make_items: Callable[[int], list[int]],
    make_job: Callable[[list[int]], int],
    pg_engine: Engine,
) -> None:
    item_id = make_items(1)[0]
    job_id = make_job([item_id])
    respx.get(OEMBED_URL).mock(
        return_value=httpx.Response(200, json={"title": "A reel", "author_name": "creator1"})
    )

    run_enrich_batch(job_id, [item_id])

    item = _reload_item(pg_engine, item_id)
    assert item.enriched_title == "A reel"
    assert item.enriched_author == "creator1"
    assert item.enriched_source is EnrichmentSource.oembed

    attempts = _attempts_for(pg_engine, item_id)
    assert len(attempts) == 1
    assert attempts[0].source is EnrichmentSource.oembed
    assert attempts[0].status is EnrichmentStatus.success

    job = _reload_job(pg_engine, job_id)
    assert job.status is JobStatus.succeeded


@respx.mock
def test_enrich_batch_falls_back_to_og_when_oembed_not_found(
    enabled_settings: None,
    make_items: Callable[[int], list[int]],
    make_job: Callable[[list[int]], int],
    pg_engine: Engine,
) -> None:
    item_id = make_items(1)[0]
    job_id = make_job([item_id])
    item_url = _reload_item(pg_engine, item_id).url_raw
    respx.get(OEMBED_URL).mock(return_value=httpx.Response(404))
    respx.get(item_url).mock(
        return_value=httpx.Response(
            200,
            html=(
                '<html><head><meta property="og:title" content="OG title">'
                '<meta property="og:description" content="OG caption"></head></html>'
            ),
        )
    )

    run_enrich_batch(job_id, [item_id])

    updated = _reload_item(pg_engine, item_id)
    assert updated.enriched_title == "OG title"
    assert updated.enriched_caption == "OG caption"
    assert updated.enriched_source is EnrichmentSource.og

    attempts = _attempts_for(pg_engine, item_id)
    assert [a.source for a in attempts] == [EnrichmentSource.oembed, EnrichmentSource.og]
    assert [a.status for a in attempts] == [EnrichmentStatus.not_found, EnrichmentStatus.success]


@respx.mock
def test_enrich_batch_makes_zero_requests_when_consent_is_missing(
    make_items: Callable[[int], list[int]],
    make_job: Callable[[list[int]], int],
    pg_engine: Engine,
) -> None:
    # Explicitly force the disabled baseline rather than trust ambient state.
    with Session(pg_engine) as session:
        settings = session.get(AppSettings, 1)
        assert settings is not None
        settings.enrichment_enabled = False
        settings.enrichment_consent_at = None
        session.commit()

    item_id = make_items(1)[0]
    job_id = make_job([item_id])

    with pytest.raises(PermissionError):
        run_enrich_batch(job_id, [item_id])

    assert len(respx.calls) == 0
    job = _reload_job(pg_engine, job_id)
    assert job.status is JobStatus.failed
    assert job.error == "PermissionError"


@respx.mock
def test_cached_success_is_never_refetched(
    enabled_settings: None,
    make_items: Callable[[int], list[int]],
    make_job: Callable[[list[int]], int],
    pg_engine: Engine,
) -> None:
    item_id = make_items(1)[0]
    route = respx.get(OEMBED_URL).mock(
        return_value=httpx.Response(200, json={"title": "cached title"})
    )

    first_job = make_job([item_id])
    run_enrich_batch(first_job, [item_id])
    assert route.call_count == 1

    second_job = make_job([item_id])
    run_enrich_batch(second_job, [item_id])
    assert route.call_count == 1  # cached success: never re-fetched

    assert len(_attempts_for(pg_engine, item_id)) == 1


def test_enrich_batch_rerun_of_finished_job_is_noop(
    enabled_settings: None,
    make_items: Callable[[int], list[int]],
    make_job: Callable[[list[int]], int],
    pg_engine: Engine,
) -> None:
    item_id = make_items(1)[0]
    job_id = make_job([item_id])
    with respx.mock:
        respx.get(OEMBED_URL).mock(return_value=httpx.Response(200, json={"title": "x"}))
        run_enrich_batch(job_id, [item_id])
    first = _reload_job(pg_engine, job_id)

    with respx.mock:
        run_enrich_batch(job_id, [item_id])  # already succeeded: no-op, zero calls
        assert len(respx.calls) == 0
    second = _reload_job(pg_engine, job_id)

    assert second.finished_at == first.finished_at


@respx.mock
def test_circuit_breaker_stops_further_requests_after_consecutive_blocks(
    enabled_settings: None,
    make_items: Callable[[int], list[int]],
    make_job: Callable[[list[int]], int],
    pg_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENRICHMENT_CIRCUIT_BREAKER_THRESHOLD", "2")
    get_config.cache_clear()
    try:
        item_ids = make_items(2)
        job_id = make_job(item_ids)
        respx.get(OEMBED_URL).mock(return_value=httpx.Response(403))
        for item_id in item_ids:
            item_url = _reload_item(pg_engine, item_id).url_raw
            respx.get(item_url).mock(return_value=httpx.Response(403))

        run_enrich_batch(job_id, item_ids)

        # item 1: oembed blocked (count=1), og blocked (count=2) -> breaker trips.
        assert len(respx.calls) == 2

        attempts_1 = _attempts_for(pg_engine, item_ids[0])
        assert [a.status for a in attempts_1] == [
            EnrichmentStatus.blocked,
            EnrichmentStatus.blocked,
        ]

        # item 2: breaker already open -> both sources recorded disabled, zero calls.
        attempts_2 = _attempts_for(pg_engine, item_ids[1])
        assert [a.status for a in attempts_2] == [
            EnrichmentStatus.disabled,
            EnrichmentStatus.disabled,
        ]
    finally:
        get_config.cache_clear()
