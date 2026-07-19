"""Analysis jobs (M6) against real Postgres with mock providers only.

A respx guard wraps the full embed → cluster → topics pipeline, asserting the
offline path makes **zero** HTTP requests. Workers use their own sessions
(`get_sessionmaker()`), so fixtures create really-committed rows and clean up
explicitly (same pattern as test_enrich_batch.py). Cluster/topic assertions
use per-run unique marker tokens so a long-lived dev database can never bleed
into memberships.
"""

from collections.abc import Callable, Generator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import respx
from sqlalchemy import Engine, delete, select, update
from sqlalchemy.orm import Session

from app.config import get_config
from app.models.ai_request import AiRequest, AiRequestStatus
from app.models.analysis import Cluster, ClusterRun, ClusterRunStatus, ItemCluster, ItemTopic
from app.models.app_settings import AppSettings
from app.models.item import DuplicateGroup, DuplicateReason, Item, ItemStatus, ItemType
from app.models.job import Job, JobKind, JobStatus
from app.services.ai.budget import BudgetExceededError
from app.services.ai.mock_provider import MockProvider
from app.services.ai.provider import RawGeneration
from app.services.ai.structured import StructuredOutputError
from app.services.analysis.embeddings import EMBEDDING_DIM, MOCK_EMBEDDING_MODEL
from app.workers.jobs import run_cluster, run_embed_batch, run_topics

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def mock_embeddings_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    """Deterministic offline embeddings for every test in this module."""
    monkeypatch.setenv("EMBEDDING_PROVIDER", "mock")
    get_config.cache_clear()
    yield
    get_config.cache_clear()


@pytest.fixture
def make_items(pg_engine: Engine) -> Generator[Callable[..., list[int]], None, None]:
    created: list[int] = []

    def _make(texts: list[str | None], **overrides: Any) -> list[int]:
        marker = uuid4().hex[:8]
        base_time = datetime(2026, 7, 1, tzinfo=UTC)
        with Session(pg_engine, expire_on_commit=False) as session:
            items = [
                Item(
                    url_raw=f"https://www.instagram.com/reel/ANA{marker}{index}/",
                    url_canonical=f"https://www.instagram.com/reel/ANA{marker}{index}/",
                    item_type=ItemType.reel,
                    status=ItemStatus.new,
                    share_text=text,
                    shared_at=base_time + timedelta(minutes=index),
                    **overrides,
                )
                for index, text in enumerate(texts)
            ]
            session.add_all(items)
            session.commit()
            ids = [item.id for item in items]
        created.extend(ids)
        return ids

    yield _make
    with Session(pg_engine) as session:
        session.execute(delete(ItemTopic).where(ItemTopic.item_id.in_(created)))
        session.execute(delete(ItemCluster).where(ItemCluster.item_id.in_(created)))
        group_ids = set(
            session.scalars(
                select(DuplicateGroup.id).where(DuplicateGroup.canonical_item_id.in_(created))
            )
        )
        if group_ids:
            session.execute(
                update(Item)
                .where(Item.duplicate_group_id.in_(group_ids))
                .values(duplicate_group_id=None)
                .execution_options(synchronize_session=False)
            )
            session.execute(delete(DuplicateGroup).where(DuplicateGroup.id.in_(group_ids)))
        session.execute(delete(Item).where(Item.id.in_(created)))
        session.commit()


@pytest.fixture
def make_job(pg_engine: Engine) -> Generator[Callable[[JobKind], int], None, None]:
    created: list[int] = []

    def _make(kind: JobKind) -> int:
        with Session(pg_engine, expire_on_commit=False) as session:
            job = Job(kind=kind, status=JobStatus.queued)
            session.add(job)
            session.commit()
            created.append(job.id)
            return job.id

    yield _make
    with Session(pg_engine) as session:
        session.execute(delete(AiRequest).where(AiRequest.job_id.in_(created)))
        session.execute(delete(Job).where(Job.id.in_(created)))
        session.commit()


@pytest.fixture
def track_cluster_runs(pg_engine: Engine) -> Generator[Callable[[], list[int]], None, None]:
    """Deletes every cluster run created while the test ran (cascades clusters
    and memberships via FK)."""
    with Session(pg_engine) as session:
        before = set(session.scalars(select(ClusterRun.id)))

    def _new_run_ids() -> list[int]:
        with Session(pg_engine) as session:
            return sorted(set(session.scalars(select(ClusterRun.id))) - before)

    yield _new_run_ids
    with Session(pg_engine) as session:
        new_ids = set(session.scalars(select(ClusterRun.id))) - before
        if new_ids:
            session.execute(delete(ClusterRun).where(ClusterRun.id.in_(new_ids)))
            session.commit()


def _job(pg_engine: Engine, job_id: int) -> Job:
    with Session(pg_engine) as session:
        job = session.get(Job, job_id)
        assert job is not None
        return job


def _themed_texts(marker: str) -> list[str | None]:
    pasta = [
        f"pasta{marker} sauce{marker} tomato{marker} dinner",
        f"pasta{marker} sauce{marker} tomato{marker} recipe",
        f"pasta{marker} sauce{marker} tomato{marker} cooking",
    ]
    gym = [
        f"gym{marker} workout{marker} legs{marker} squat",
        f"gym{marker} workout{marker} legs{marker} training",
        f"gym{marker} workout{marker} legs{marker} routine",
    ]
    outlier = f"quantitative{marker} finance{marker} modeling{marker} paper"
    return [*pasta, *gym, outlier]


# --- embed_batch --------------------------------------------------------------


def test_embed_batch_embeds_texts_skips_textless_and_is_idempotent(
    pg_engine: Engine,
    make_items: Callable[..., list[int]],
    make_job: Callable[[JobKind], int],
) -> None:
    item_ids = make_items(["some pasta text", "some gym text", None])

    with respx.mock:  # zero HTTP calls allowed
        run_embed_batch(make_job(JobKind.embed_batch), item_ids=item_ids)

    with Session(pg_engine) as session:
        items = [session.get(Item, item_id) for item_id in item_ids]
        assert items[0] is not None and items[0].embedding is not None
        assert len(list(items[0].embedding)) == EMBEDDING_DIM
        assert items[0].embedding_model == MOCK_EMBEDDING_MODEL
        assert items[1] is not None and items[1].embedding is not None
        # No text at all -> never embedded, never enters semantic analysis.
        assert items[2] is not None and items[2].embedding is None

    first_job = _job(pg_engine, make_job(JobKind.embed_batch))
    # Fresh job over the same ids: everything already embedded -> no work.
    run_embed_batch(first_job.id, item_ids=item_ids)
    rerun = _job(pg_engine, first_job.id)
    assert rerun.status is JobStatus.succeeded
    assert rerun.total == 0


# --- cluster ------------------------------------------------------------------


def test_cluster_job_produces_deterministic_versioned_memberships(
    pg_engine: Engine,
    make_items: Callable[..., list[int]],
    make_job: Callable[[JobKind], int],
    track_cluster_runs: Callable[[], list[int]],
) -> None:
    marker = uuid4().hex[:6]
    item_ids = make_items(_themed_texts(marker))
    pasta_ids, gym_ids, outlier_id = set(item_ids[0:3]), set(item_ids[3:6]), item_ids[6]

    with respx.mock:
        run_embed_batch(make_job(JobKind.embed_batch), item_ids=item_ids)
        run_cluster(make_job(JobKind.cluster))

    run_ids = track_cluster_runs()
    assert len(run_ids) == 1
    with Session(pg_engine) as session:
        run = session.get(ClusterRun, run_ids[0])
        assert run is not None
        assert run.status is ClusterRunStatus.succeeded
        assert run.method == "agglomerative_cosine"
        assert run.embedding_model == MOCK_EMBEDDING_MODEL
        assert run.params["min_cluster_size"] == 2

        rows = session.execute(
            select(ItemCluster.item_id, ItemCluster.cluster_id)
            .join(Cluster, Cluster.id == ItemCluster.cluster_id)
            .where(Cluster.run_id == run.id, ItemCluster.item_id.in_(item_ids))
        ).all()
        cluster_by_item = dict(rows)
        # Exact memberships: one cluster per theme, outlier unclustered.
        assert {cluster_by_item[item_id] for item_id in pasta_ids} == {
            cluster_by_item[next(iter(pasta_ids))]
        }
        assert {cluster_by_item[item_id] for item_id in gym_ids} == {
            cluster_by_item[next(iter(gym_ids))]
        }
        assert cluster_by_item[next(iter(pasta_ids))] != cluster_by_item[next(iter(gym_ids))]
        assert outlier_id not in cluster_by_item

        sizes = dict(
            session.execute(
                select(Cluster.id, Cluster.size).where(
                    Cluster.id.in_(set(cluster_by_item.values()))
                )
            ).all()
        )
        assert sizes[cluster_by_item[next(iter(pasta_ids))]] == 3

    # Re-running clusters again: a NEW versioned run, previous one retained.
    with respx.mock:
        run_cluster(make_job(JobKind.cluster))
    assert len(track_cluster_runs()) == 2


def test_cluster_job_rebuilds_near_text_groups_and_keeps_exact_groups(
    pg_engine: Engine,
    make_items: Callable[..., list[int]],
    make_job: Callable[[JobKind], int],
    track_cluster_runs: Callable[[], list[int]],
) -> None:
    marker = uuid4().hex[:6]
    # Two items with identical vocabulary but different URLs (so no exact
    # dupe), plus one distinct item.
    near_a, near_b, distinct = make_items(
        [
            f"amazing{marker} croissant{marker} lamination{marker} tutorial",
            f"AMAZING{marker} croissant{marker} — lamination{marker} tutorial!",
            f"woodworking{marker} dovetail{marker} joinery{marker} basics",
        ]
    )
    # A pre-existing exact duplicate group that must never be touched.
    exact_members = make_items(["exact dupe text", "exact dupe text"])
    with Session(pg_engine, expire_on_commit=False) as session:
        exact_group = DuplicateGroup(
            canonical_item_id=exact_members[0], reason=DuplicateReason.same_shortcode
        )
        session.add(exact_group)
        session.flush()
        session.execute(
            update(Item).where(Item.id.in_(exact_members)).values(duplicate_group_id=exact_group.id)
        )
        session.commit()
        exact_group_id = exact_group.id

    all_ids = [near_a, near_b, distinct, *exact_members]
    with respx.mock:
        run_embed_batch(make_job(JobKind.embed_batch), item_ids=all_ids)
        run_cluster(make_job(JobKind.cluster))

    def _near_group_of(session: Session, item_id: int) -> int | None:
        item = session.get(Item, item_id)
        assert item is not None
        return item.duplicate_group_id

    with Session(pg_engine) as session:
        group_a, group_b = _near_group_of(session, near_a), _near_group_of(session, near_b)
        assert group_a is not None and group_a == group_b
        group = session.get(DuplicateGroup, group_a)
        assert group is not None
        assert group.reason is DuplicateReason.near_text
        # Canonical = earliest share (near_a was created first).
        assert group.canonical_item_id == near_a
        assert _near_group_of(session, distinct) is None
        # Exact group untouched — members already grouped never enter
        # near-dedupe, even with identical texts.
        for member_id in exact_members:
            assert _near_group_of(session, member_id) == exact_group_id
        first_near_group_id = group_a

    # Re-run converges: still exactly one near_text group over the pair.
    with respx.mock:
        run_cluster(make_job(JobKind.cluster))
    with Session(pg_engine) as session:
        group_a, group_b = _near_group_of(session, near_a), _near_group_of(session, near_b)
        assert group_a is not None and group_a == group_b
        rebuilt = session.get(DuplicateGroup, group_a)
        assert rebuilt is not None and rebuilt.reason is DuplicateReason.near_text
        assert rebuilt.id != first_near_group_id  # rebuilt from scratch
        stale = session.get(DuplicateGroup, first_near_group_id)
        assert stale is None


# --- topics -------------------------------------------------------------------


def _run_full_pipeline(
    make_items: Callable[..., list[int]],
    make_job: Callable[[JobKind], int],
    marker: str,
) -> list[int]:
    item_ids = make_items(_themed_texts(marker))
    with respx.mock:
        run_embed_batch(make_job(JobKind.embed_batch), item_ids=item_ids)
        run_cluster(make_job(JobKind.cluster))
    return item_ids


def test_topics_job_labels_clusters_and_assigns_topics_offline(
    pg_engine: Engine,
    make_items: Callable[..., list[int]],
    make_job: Callable[[JobKind], int],
    track_cluster_runs: Callable[[], list[int]],
) -> None:
    marker = uuid4().hex[:6]
    item_ids = _run_full_pipeline(make_items, make_job, marker)
    [run_id] = track_cluster_runs()
    topics_job_id = make_job(JobKind.topics)

    with respx.mock:  # the full offline pipeline made zero HTTP calls
        run_topics(topics_job_id, cluster_run_id=run_id)

    with Session(pg_engine) as session:
        clusters = list(session.scalars(select(Cluster).where(Cluster.run_id == run_id)))
        assert len(clusters) == 2
        for cluster in clusters:
            assert cluster.label
            assert cluster.description_md
        labels = {cluster.label for cluster in clusters}
        assert any(f"Pasta{marker}".title() in label for label in labels)

        assigned = session.execute(
            select(ItemTopic.item_id, ItemTopic.confidence).where(ItemTopic.item_id.in_(item_ids))
        ).all()
        clustered_ids = set(item_ids[:6])
        assert {item_id for item_id, _ in assigned} == clustered_ids
        assert all(0.0 <= confidence <= 1.0 for _, confidence in assigned)

        requests = list(session.scalars(select(AiRequest).where(AiRequest.job_id == topics_job_id)))
        # 2 clusters x (label + topics) = 4 calls, all successful mock calls.
        assert len(requests) == 4
        assert {request.task for request in requests} == {"cluster_label", "topic_extraction"}
        for request in requests:
            assert request.status is AiRequestStatus.success
            assert request.provider == "mock"
            assert request.prompt_tokens > 0
            assert float(request.est_cost_usd) == 0.0
            # Content-free audit: no item text in any string column (the
            # marker appears in every fixture text).
            assert marker not in request.model
            assert marker not in request.task
            assert marker not in request.provider

        job = session.get(Job, topics_job_id)
        assert job is not None
        assert job.status is JobStatus.succeeded
        assert job.progress == 2


def test_topics_rerun_preserves_user_edits_and_never_duplicates(
    pg_engine: Engine,
    make_items: Callable[..., list[int]],
    make_job: Callable[[JobKind], int],
    track_cluster_runs: Callable[[], list[int]],
) -> None:
    marker = uuid4().hex[:6]
    item_ids = _run_full_pipeline(make_items, make_job, marker)
    [run_id] = track_cluster_runs()
    with respx.mock:
        run_topics(make_job(JobKind.topics), cluster_run_id=run_id)

    with Session(pg_engine, expire_on_commit=False) as session:
        cluster = session.scalars(select(Cluster).where(Cluster.run_id == run_id)).first()
        assert cluster is not None
        cluster.label = "My Custom Label"
        cluster.description_md = "My custom description."
        session.commit()
        edited_cluster_id = cluster.id
        before_topic_rows = session.execute(
            select(ItemTopic.item_id, ItemTopic.topic_id).where(ItemTopic.item_id.in_(item_ids))
        ).all()

    with respx.mock:
        run_topics(make_job(JobKind.topics), cluster_run_id=run_id)

    with Session(pg_engine) as session:
        edited = session.get(Cluster, edited_cluster_id)
        assert edited is not None
        assert edited.label == "My Custom Label"
        assert edited.description_md == "My custom description."
        after_topic_rows = session.execute(
            select(ItemTopic.item_id, ItemTopic.topic_id).where(ItemTopic.item_id.in_(item_ids))
        ).all()
        assert sorted(after_topic_rows) == sorted(before_topic_rows)


class CostlyMockProvider(MockProvider):
    """Valid outputs, but each call reports enough completion tokens to cost
    ~$2.50 at the conservative default pricing."""

    name = "costly-test"

    def generate_raw(self, **kwargs: Any) -> RawGeneration:
        return replace(super().generate_raw(**kwargs), completion_tokens=100_000)


@pytest.fixture
def small_budget(pg_engine: Engine) -> Generator[None, None, None]:
    with Session(pg_engine) as session:
        settings = session.get(AppSettings, 1)
        assert settings is not None
        original = settings.monthly_budget_usd
        settings.monthly_budget_usd = 5.0
        session.commit()
    yield
    with Session(pg_engine) as session:
        settings = session.get(AppSettings, 1)
        assert settings is not None
        settings.monthly_budget_usd = original
        session.commit()


def test_budget_cap_aborts_topics_batch_mid_way_cleanly(
    pg_engine: Engine,
    make_items: Callable[..., list[int]],
    make_job: Callable[[JobKind], int],
    track_cluster_runs: Callable[[], list[int]],
    small_budget: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Keep the token budget out of the way so only the USD cap trips.
    monkeypatch.setenv("AI_JOB_TOKEN_BUDGET", "100000000")
    get_config.cache_clear()
    monkeypatch.setattr(
        "app.workers.jobs.get_llm_provider", lambda settings, config: CostlyMockProvider()
    )
    marker = uuid4().hex[:6]
    _run_full_pipeline(make_items, make_job, marker)
    [run_id] = track_cluster_runs()
    topics_job_id = make_job(JobKind.topics)

    # Calls cost ~$2.50 each against a $5 cap: cluster 1 completes (label +
    # topics = $5), then the check before cluster 2 aborts.
    with pytest.raises(BudgetExceededError):
        run_topics(topics_job_id, cluster_run_id=run_id)

    with Session(pg_engine) as session:
        job = session.get(Job, topics_job_id)
        assert job is not None
        assert job.status is JobStatus.failed
        assert job.error == "BudgetExceededError"
        assert job.progress == 1  # first cluster finished cleanly

        clusters = list(
            session.scalars(select(Cluster).where(Cluster.run_id == run_id).order_by(Cluster.id))
        )
        assert clusters[0].label is not None  # completed cluster kept
        assert clusters[1].label is None  # aborted before cluster 2

        requests = list(session.scalars(select(AiRequest).where(AiRequest.job_id == topics_job_id)))
        assert len(requests) == 2  # label + topics for cluster 1 only
        assert all(float(request.est_cost_usd) > 0 for request in requests)


class AlwaysMalformedProvider(MockProvider):
    name = "malformed-test"

    def generate_raw(self, **kwargs: Any) -> RawGeneration:
        return RawGeneration(
            text="this is not json at all", prompt_tokens=10, completion_tokens=5, latency_ms=1
        )


def test_double_malformed_output_fails_job_with_redacted_error(
    pg_engine: Engine,
    make_items: Callable[..., list[int]],
    make_job: Callable[[JobKind], int],
    track_cluster_runs: Callable[[], list[int]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.workers.jobs.get_llm_provider", lambda settings, config: AlwaysMalformedProvider()
    )
    marker = uuid4().hex[:6]
    _run_full_pipeline(make_items, make_job, marker)
    [run_id] = track_cluster_runs()
    topics_job_id = make_job(JobKind.topics)

    with pytest.raises(StructuredOutputError):
        run_topics(topics_job_id, cluster_run_id=run_id)

    with Session(pg_engine) as session:
        job = session.get(Job, topics_job_id)
        assert job is not None
        assert job.status is JobStatus.failed
        # Redacted: exception class name only, no output/content fragments.
        assert job.error == "StructuredOutputError"
        requests = list(session.scalars(select(AiRequest).where(AiRequest.job_id == topics_job_id)))
        assert len(requests) == 2  # initial + repair, both audited
        assert all(request.status is AiRequestStatus.invalid_output for request in requests)


def test_topics_without_a_valid_cluster_run_fails_cleanly(
    pg_engine: Engine,
    make_job: Callable[[JobKind], int],
) -> None:
    # Point the job at an explicit nonexistent run (a long-lived dev DB may
    # legitimately hold succeeded runs, so the "latest" path isn't assertable).
    topics_job_id = make_job(JobKind.topics)
    with pytest.raises(ValueError):
        run_topics(topics_job_id, cluster_run_id=999_999_999)
    job = _job(pg_engine, topics_job_id)
    assert job.status is JobStatus.failed
    assert job.error == "ValueError"
