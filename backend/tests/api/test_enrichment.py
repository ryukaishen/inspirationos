"""Enrichment API: the consent gate, per-item/selection/group Enrich
triggers, and duplicate-group-aware bulk notes.

Against real Postgres + Redis. Settings mutations here all go through
`client` (dependency-injected into the test's own rolled-back transaction),
so no manual restore is needed — contrast with
tests/workers/test_enrich_batch.py, which calls the worker function directly
against a separately-committed connection and must restore the settings
singleton itself.
"""

from collections.abc import Generator
from uuid import uuid4

import pytest
import respx
from fastapi.testclient import TestClient
from redis import Redis
from rq import Queue
from sqlalchemy.orm import Session

from app.models.app_settings import AppSettings
from app.models.item import DuplicateGroup, DuplicateReason, Item, ItemStatus, ItemType
from app.models.job import Job, JobKind
from app.queues import QUEUE_ENRICHMENT

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def clean_enrichment_queue(redis_client: Redis) -> Generator[None, None, None]:
    """Enqueued enrich-batch payloads must never leak to a real worker."""
    yield
    Queue(QUEUE_ENRICHMENT, connection=redis_client).empty()


@pytest.fixture
def settings_row(db_session: Session) -> AppSettings:
    """Known baseline (disabled, no consent) regardless of ambient state."""
    settings = db_session.get(AppSettings, 1)
    assert settings is not None
    settings.enrichment_enabled = False
    settings.enrichment_consent_at = None
    db_session.commit()
    return settings


@pytest.fixture
def two_items(db_session: Session) -> list[int]:
    marker = uuid4().hex[:8]
    items = [
        Item(
            url_raw=f"https://www.instagram.com/reel/ENR{marker}{i}/",
            url_canonical=f"https://www.instagram.com/reel/ENR{marker}{i}/",
            item_type=ItemType.reel,
            status=ItemStatus.needs_context,
        )
        for i in range(2)
    ]
    db_session.add_all(items)
    db_session.commit()
    return [item.id for item in items]


@pytest.fixture
def duplicate_group(db_session: Session) -> tuple[int, list[int]]:
    """A canonical item plus two more members of the same duplicate group."""
    marker = uuid4().hex[:8]
    canonical = Item(
        url_raw=f"https://www.instagram.com/reel/GRP{marker}/",
        url_canonical=f"https://www.instagram.com/reel/GRP{marker}/",
        shortcode=f"GRP{marker}",
        item_type=ItemType.reel,
        status=ItemStatus.new,
    )
    db_session.add(canonical)
    db_session.flush()
    group = DuplicateGroup(canonical_item_id=canonical.id, reason=DuplicateReason.same_shortcode)
    db_session.add(group)
    db_session.flush()
    canonical.duplicate_group_id = group.id
    members = [
        Item(
            url_raw=canonical.url_raw,
            url_canonical=canonical.url_canonical,
            shortcode=canonical.shortcode,
            item_type=ItemType.reel,
            status=ItemStatus.new,
            duplicate_group_id=group.id,
        )
        for _ in range(2)
    ]
    db_session.add_all(members)
    db_session.commit()
    all_ids = [canonical.id, *(m.id for m in members)]
    return group.id, all_ids


# --- settings ----------------------------------------------------------------


def test_get_settings_reflects_current_state(settings_row: AppSettings, client: TestClient) -> None:
    response = client.get("/api/settings")
    assert response.status_code == 200
    body = response.json()
    assert body["enrichment_enabled"] is False
    assert body["enrichment_consent_at"] is None


def test_enabling_stamps_consent_and_disabling_keeps_it(
    settings_row: AppSettings, client: TestClient
) -> None:
    first = client.patch("/api/settings/enrichment", json={"enrichment_enabled": True})
    assert first.status_code == 200
    consent_at = first.json()["enrichment_consent_at"]
    assert consent_at is not None

    # already enabled: re-enabling must not restamp consent
    second = client.patch("/api/settings/enrichment", json={"enrichment_enabled": True})
    assert second.json()["enrichment_consent_at"] == consent_at

    # disabling flips the flag but keeps the historical consent timestamp
    third = client.patch("/api/settings/enrichment", json={"enrichment_enabled": False})
    assert third.json()["enrichment_enabled"] is False
    assert third.json()["enrichment_consent_at"] == consent_at


# --- enrich trigger: the consent gate ----------------------------------------


@respx.mock
def test_enrich_is_forbidden_and_makes_zero_requests_when_disabled(
    settings_row: AppSettings, two_items: list[int], client: TestClient
) -> None:
    response = client.post("/api/items/enrich", json={"item_ids": two_items})
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "enrichment_disabled"
    assert len(respx.calls) == 0


def test_toggling_enrichment_alone_enqueues_nothing(
    settings_row: AppSettings, client: TestClient, redis_client: Redis
) -> None:
    client.patch("/api/settings/enrichment", json={"enrichment_enabled": True})
    assert Queue(QUEUE_ENRICHMENT, connection=redis_client).count == 0


def test_enrich_requires_at_least_one_target(settings_row: AppSettings, client: TestClient) -> None:
    client.patch("/api/settings/enrichment", json={"enrichment_enabled": True})
    response = client.post("/api/items/enrich", json={"item_ids": []})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "no_op"


def test_enrich_enqueues_a_job_when_enabled(
    settings_row: AppSettings, two_items: list[int], client: TestClient, db_session: Session
) -> None:
    client.patch("/api/settings/enrichment", json={"enrichment_enabled": True})
    response = client.post("/api/items/enrich", json={"item_ids": two_items})
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    assert job_id
    # A real dev-stack worker may race to dequeue this immediately, so assert
    # against the persisted job row rather than the transient queue length.
    job = db_session.get(Job, job_id)
    assert job is not None
    assert job.kind is JobKind.enrich_batch
    assert sorted(job.payload["item_ids"]) == sorted(two_items)


def test_enrich_expands_a_duplicate_group_to_every_member(
    settings_row: AppSettings,
    duplicate_group: tuple[int, list[int]],
    client: TestClient,
    db_session: Session,
) -> None:
    group_id, all_ids = duplicate_group
    client.patch("/api/settings/enrichment", json={"enrichment_enabled": True})
    response = client.post("/api/items/enrich", json={"duplicate_group_ids": [group_id]})
    assert response.status_code == 202
    job = db_session.get(Job, response.json()["job_id"])
    assert job is not None
    assert sorted(job.payload["item_ids"]) == sorted(all_ids)


# --- bulk update: notes over duplicate groups --------------------------------


def test_bulk_note_applies_to_every_member_of_a_duplicate_group(
    duplicate_group: tuple[int, list[int]], client: TestClient, db_session: Session
) -> None:
    group_id, all_ids = duplicate_group
    response = client.post(
        "/api/items/bulk",
        json={"item_ids": [], "duplicate_group_ids": [group_id], "context_note": "same reel"},
    )
    assert response.status_code == 200
    assert response.json()["updated"] == len(all_ids)

    for item_id in all_ids:
        item = db_session.get(Item, item_id)
        assert item is not None
        assert item.context_note == "same reel"


def test_bulk_requires_a_target_even_with_an_action(client: TestClient) -> None:
    response = client.post("/api/items/bulk", json={"item_ids": [], "status": "reviewed"})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "no_op"
