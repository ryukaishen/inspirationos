"""Generation jobs (M7) against real Postgres with mock providers only.

Every worker call is wrapped in a respx guard asserting the offline path
makes **zero** HTTP requests. Workers use their own sessions, so fixtures
create really-committed rows and clean up explicitly (same pattern as
test_analysis_jobs.py). Assertions scope to per-run unique marker tokens so a
long-lived dev database can never bleed in.
"""

import json
from collections.abc import Callable, Generator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import respx
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from app.models.ai_request import AiRequest, AiRequestStatus
from app.models.analysis import Cluster, ClusterRun, ClusterRunStatus, ItemCluster
from app.models.app_settings import AppSettings
from app.models.artifact import Artifact, ArtifactKind
from app.models.item import Item, ItemStatus, ItemType
from app.models.job import Job, JobKind, JobStatus
from app.models.project import MilestoneStatus, Project, ProjectMilestone, ProjectStatus
from app.services.ai.budget import BudgetExceededError
from app.services.ai.mock_provider import MockProvider
from app.services.ai.provider import RawGeneration
from app.services.analysis.topics import GroundingError
from app.services.generation.projects import NoEligibleItemsError
from app.services.generation.scoring import SCORE_DIMENSIONS
from app.workers.jobs import (
    run_advisor_review,
    run_combine_projects,
    run_generate_projects,
    run_regenerate_project,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def make_items(pg_engine: Engine) -> Generator[Callable[..., list[int]], None, None]:
    created: list[int] = []

    def _make(texts: list[str | None], **overrides: Any) -> list[int]:
        marker = uuid4().hex[:8]
        base_time = datetime(2026, 7, 1, tzinfo=UTC)
        with Session(pg_engine, expire_on_commit=False) as session:
            items = [
                Item(
                    url_raw=f"https://www.instagram.com/reel/GEN{marker}{index}/",
                    url_canonical=f"https://www.instagram.com/reel/GEN{marker}{index}/",
                    item_type=ItemType.reel,
                    status=ItemStatus.new if text else ItemStatus.needs_context,
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
        session.execute(delete(ItemCluster).where(ItemCluster.item_id.in_(created)))
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
def make_cluster_run(
    pg_engine: Engine,
) -> Generator[Callable[[list[list[int]]], tuple[int, list[int]]], None, None]:
    """Creates a succeeded cluster run with the given member-id groups —
    generation needs clusters to exist, not the clustering algorithm."""
    created_runs: list[int] = []

    def _make(member_groups: list[list[int]]) -> tuple[int, list[int]]:
        with Session(pg_engine, expire_on_commit=False) as session:
            run = ClusterRun(
                method="agglomerative_cosine",
                params={},
                embedding_model="mock-test",
                status=ClusterRunStatus.succeeded,
            )
            session.add(run)
            session.flush()
            cluster_ids: list[int] = []
            for index, member_ids in enumerate(member_groups):
                cluster = Cluster(
                    run_id=run.id,
                    label=f"Test cluster {index}",
                    description_md="Synthetic test cluster.",
                    size=len(member_ids),
                )
                session.add(cluster)
                session.flush()
                session.add_all(
                    ItemCluster(item_id=member_id, cluster_id=cluster.id)
                    for member_id in member_ids
                )
                cluster_ids.append(cluster.id)
            session.commit()
            created_runs.append(run.id)
            return run.id, cluster_ids

    yield _make
    with Session(pg_engine) as session:
        session.execute(delete(ClusterRun).where(ClusterRun.id.in_(created_runs)))
        session.commit()


@pytest.fixture
def track_projects(pg_engine: Engine) -> Generator[Callable[[], list[int]], None, None]:
    """Diff-tracks worker-created projects; deleting a project cascades its
    milestones and artifacts at the DB level."""
    with Session(pg_engine) as session:
        before = set(session.scalars(select(Project.id)))

    def _new_ids() -> list[int]:
        with Session(pg_engine) as session:
            return sorted(set(session.scalars(select(Project.id))) - before)

    yield _new_ids
    with Session(pg_engine) as session:
        new_ids = set(session.scalars(select(Project.id))) - before
        if new_ids:
            session.execute(delete(Project).where(Project.id.in_(new_ids)))
            session.commit()


@pytest.fixture
def make_project(pg_engine: Engine) -> Generator[Callable[..., int], None, None]:
    created: list[int] = []

    def _make(**overrides: Any) -> int:
        marker = uuid4().hex[:8]
        fields: dict[str, Any] = {
            "title": f"Seed project {marker}",
            "one_liner": f"Seeded one-liner {marker}",
            "summary_md": f"Seeded summary {marker}",
            "domains": ["data science"],
            "difficulty": "intermediate",
            "duration_estimate": "4 weeks",
            "datasets": [],
            "tech_stack": ["python"],
            "skills_demonstrated": ["modeling"],
            "risks": [],
            "scores": {
                dimension: {"score": 5.0, "rationale": "seeded"} for dimension in SCORE_DIMENSIONS
            },
            "source": {
                "item_ids": [],
                "cluster_ids": [],
                "prompt_version": "v1",
                "provider": "mock",
                "model": "mock-llm-v1",
            },
        }
        fields.update(overrides)
        with Session(pg_engine, expire_on_commit=False) as session:
            project = Project(**fields)
            session.add(project)
            session.commit()
            created.append(project.id)
            return project.id

    yield _make
    with Session(pg_engine) as session:
        session.execute(delete(Project).where(Project.id.in_(created)))
        session.commit()


def _job(pg_engine: Engine, job_id: int) -> Job:
    with Session(pg_engine) as session:
        job = session.get(Job, job_id)
        assert job is not None
        return job


def _themed_texts(marker: str) -> list[str | None]:
    return [
        f"sourdough{marker} starter{marker} feeding schedule",
        f"sourdough{marker} starter{marker} scoring patterns",
        f"bouldering{marker} grip{marker} strength training",
        f"bouldering{marker} grip{marker} footwork drills",
        None,  # textless: must never reach the provider or a source citation
    ]


class RecordingMockProvider(MockProvider):
    """MockProvider that records every context it was shown."""

    def __init__(self) -> None:
        self.contexts: list[dict[str, Any]] = []

    def generate_raw(self, **kwargs: Any) -> RawGeneration:
        self.contexts.append(kwargs["context"])
        return super().generate_raw(**kwargs)


class UngroundedProvider(MockProvider):
    """Valid schema output that cites an item_id it was never given."""

    def generate_raw(self, **kwargs: Any) -> RawGeneration:
        raw = super().generate_raw(**kwargs)
        data = json.loads(raw.text)
        data["ideas"][0]["source_item_ids"] = [999_999_999]
        return replace(raw, text=json.dumps(data))


# --- generate_projects --------------------------------------------------------


def test_generate_projects_creates_grounded_projects_offline(
    pg_engine: Engine,
    make_items: Callable[..., list[int]],
    make_job: Callable[[JobKind], int],
    track_projects: Callable[[], list[int]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = RecordingMockProvider()
    monkeypatch.setattr("app.workers.jobs.get_llm_provider", lambda settings, config: recorder)
    marker = uuid4().hex[:6]
    item_ids = make_items(_themed_texts(marker))
    eligible_ids, textless_id = set(item_ids[:4]), item_ids[4]
    job_id = make_job(JobKind.generate_projects)

    with respx.mock:  # zero HTTP calls allowed
        run_generate_projects(job_id, item_ids=item_ids, count=2)

    # The anti-hallucination gate: the textless item never reached the provider.
    [context] = recorder.contexts
    assert {entry["item_id"] for entry in context["items"]} == eligible_ids
    assert textless_id not in {entry["item_id"] for entry in context["items"]}

    new_ids = track_projects()
    assert len(new_ids) == 2
    with Session(pg_engine) as session:
        for project_id in new_ids:
            project = session.get(Project, project_id)
            assert project is not None
            assert project.status is ProjectStatus.idea
            assert project.title
            assert project.summary_md
            # Server-verified grounding: every cited id is a real eligible item.
            cited = set(project.source["item_ids"])
            assert cited and cited <= eligible_ids
            assert textless_id not in cited
            assert project.source["provider"] == "mock"
            assert project.source["model"] == "mock-llm-v1"
            assert project.source["prompt_version"] == "v1"
            for dimension in SCORE_DIMENSIONS:
                entry = project.scores[dimension]
                assert 0.0 <= entry["score"] <= 10.0
                assert entry["rationale"]

        requests = list(session.scalars(select(AiRequest).where(AiRequest.job_id == job_id)))
        assert len(requests) == 1
        request = requests[0]
        assert request.status is AiRequestStatus.success
        assert request.task == "generate_projects"
        assert float(request.est_cost_usd) == 0.0
        # Content-free audit: the marker appears in every fixture text but in
        # no ai_requests column.
        assert marker not in request.model
        assert marker not in request.task
        assert marker not in request.provider

        job = session.get(Job, job_id)
        assert job is not None
        assert job.status is JobStatus.succeeded
        assert job.progress == job.total == 3  # 1 call + 2 persisted ideas


def test_generate_projects_from_clusters_expands_members(
    pg_engine: Engine,
    make_items: Callable[..., list[int]],
    make_job: Callable[[JobKind], int],
    make_cluster_run: Callable[[list[list[int]]], tuple[int, list[int]]],
    track_projects: Callable[[], list[int]],
) -> None:
    marker = uuid4().hex[:6]
    item_ids = make_items(_themed_texts(marker))
    _, cluster_ids = make_cluster_run([item_ids[0:2], item_ids[2:4]])
    job_id = make_job(JobKind.generate_projects)

    with respx.mock:
        run_generate_projects(job_id, cluster_ids=cluster_ids, count=1)

    [project_id] = track_projects()
    with Session(pg_engine) as session:
        project = session.get(Project, project_id)
        assert project is not None
        # Cited items come from the cluster members; cited clusters are the
        # requested ones.
        assert set(project.source["item_ids"]) <= set(item_ids[:4])
        assert set(project.source["cluster_ids"]) == set(cluster_ids)
    assert _job(pg_engine, job_id).status is JobStatus.succeeded


def test_generate_projects_ungrounded_citation_fails_job_with_no_writes(
    pg_engine: Engine,
    make_items: Callable[..., list[int]],
    make_job: Callable[[JobKind], int],
    track_projects: Callable[[], list[int]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.workers.jobs.get_llm_provider", lambda settings, config: UngroundedProvider()
    )
    marker = uuid4().hex[:6]
    item_ids = make_items(_themed_texts(marker))
    job_id = make_job(JobKind.generate_projects)

    with respx.mock, pytest.raises(GroundingError):
        run_generate_projects(job_id, item_ids=item_ids, count=2)

    job = _job(pg_engine, job_id)
    assert job.status is JobStatus.failed
    # Redacted: class name only — no ids, no generated text.
    assert job.error == "GroundingError"
    assert track_projects() == []  # the whole batch was rejected


def test_generate_projects_with_no_eligible_items_fails_cleanly(
    pg_engine: Engine,
    make_items: Callable[..., list[int]],
    make_job: Callable[[JobKind], int],
    track_projects: Callable[[], list[int]],
) -> None:
    item_ids = make_items([None, None])
    job_id = make_job(JobKind.generate_projects)

    with respx.mock, pytest.raises(NoEligibleItemsError):
        run_generate_projects(job_id, item_ids=item_ids)

    job = _job(pg_engine, job_id)
    assert job.status is JobStatus.failed
    assert job.error == "NoEligibleItemsError"
    assert track_projects() == []
    with Session(pg_engine) as session:
        # Failed before any provider call — nothing to audit.
        assert (
            session.scalar(select(AiRequest.id).where(AiRequest.job_id == job_id).limit(1)) is None
        )


@pytest.fixture
def exhausted_budget(pg_engine: Engine) -> Generator[None, None, None]:
    """Cap $5 with $10 already spent this month — the pre-call budget check
    must abort before any provider call."""
    with Session(pg_engine, expire_on_commit=False) as session:
        settings = session.get(AppSettings, 1)
        assert settings is not None
        original = settings.monthly_budget_usd
        settings.monthly_budget_usd = 5.0
        seed = AiRequest(
            provider="budget-seed",
            model="seed",
            task="seed",
            prompt_tokens=1,
            completion_tokens=1,
            est_cost_usd=10.0,
            latency_ms=1,
            status=AiRequestStatus.success,
        )
        session.add(seed)
        session.commit()
        seed_id = seed.id
    yield
    with Session(pg_engine) as session:
        settings = session.get(AppSettings, 1)
        assert settings is not None
        settings.monthly_budget_usd = original
        session.execute(delete(AiRequest).where(AiRequest.id == seed_id))
        session.commit()


def test_generate_projects_budget_abort_is_clean(
    pg_engine: Engine,
    make_items: Callable[..., list[int]],
    make_job: Callable[[JobKind], int],
    track_projects: Callable[[], list[int]],
    exhausted_budget: None,
) -> None:
    marker = uuid4().hex[:6]
    item_ids = make_items(_themed_texts(marker))
    job_id = make_job(JobKind.generate_projects)

    with respx.mock, pytest.raises(BudgetExceededError):
        run_generate_projects(job_id, item_ids=item_ids)

    job = _job(pg_engine, job_id)
    assert job.status is JobStatus.failed
    assert job.error == "BudgetExceededError"
    assert track_projects() == []


def test_finished_generate_job_is_a_noop(
    pg_engine: Engine,
    make_items: Callable[..., list[int]],
    make_job: Callable[[JobKind], int],
    track_projects: Callable[[], list[int]],
) -> None:
    item_ids = make_items([f"idempotent{uuid4().hex[:6]} text"])
    job_id = make_job(JobKind.generate_projects)
    with Session(pg_engine) as session:
        job = session.get(Job, job_id)
        assert job is not None
        job.status = JobStatus.succeeded
        session.commit()

    with respx.mock:
        run_generate_projects(job_id, item_ids=item_ids)

    assert track_projects() == []  # finished job re-run writes nothing


# --- combine ------------------------------------------------------------------


def test_combine_creates_child_with_both_parent_ids(
    pg_engine: Engine,
    make_project: Callable[..., int],
    make_job: Callable[[JobKind], int],
    track_projects: Callable[[], list[int]],
) -> None:
    parent_a = make_project(
        source={
            "item_ids": [101, 102],
            "cluster_ids": [7],
            "prompt_version": "v1",
            "provider": "mock",
            "model": "mock-llm-v1",
        }
    )
    parent_b = make_project(
        source={
            "item_ids": [102, 103],
            "cluster_ids": [8],
            "prompt_version": "v1",
            "provider": "mock",
            "model": "mock-llm-v1",
        }
    )
    job_id = make_job(JobKind.generate_projects)

    with respx.mock:
        run_combine_projects(job_id, parent_project_ids=[parent_a, parent_b])

    # The parents themselves were created inside this test, so exclude them
    # from the worker-created diff.
    [child_id] = [pid for pid in track_projects() if pid not in {parent_a, parent_b}]
    with Session(pg_engine) as session:
        child = session.get(Project, child_id)
        assert child is not None
        assert child.parent_project_ids == [parent_a, parent_b]
        # Provenance is the union of the parents'.
        assert child.source["item_ids"] == [101, 102, 103]
        assert child.source["cluster_ids"] == [7, 8]
        assert child.status is ProjectStatus.idea
        for dimension in SCORE_DIMENSIONS:
            assert child.scores[dimension]["rationale"]
    assert _job(pg_engine, job_id).status is JobStatus.succeeded


def test_combine_with_missing_parent_fails_cleanly(
    pg_engine: Engine,
    make_project: Callable[..., int],
    make_job: Callable[[JobKind], int],
    track_projects: Callable[[], list[int]],
) -> None:
    parent = make_project()
    job_id = make_job(JobKind.generate_projects)

    with respx.mock, pytest.raises(ValueError, match="exactly two"):
        run_combine_projects(job_id, parent_project_ids=[parent, 999_999_999])

    job = _job(pg_engine, job_id)
    assert job.status is JobStatus.failed
    assert job.error == "ValueError"
    assert [pid for pid in track_projects() if pid != parent] == []


# --- advisor ------------------------------------------------------------------


def test_advisor_review_is_versioned_with_all_five_sections(
    pg_engine: Engine,
    make_project: Callable[..., int],
    make_job: Callable[[JobKind], int],
) -> None:
    project_id = make_project()

    with respx.mock:
        run_advisor_review(make_job(JobKind.generate_artifact), project_id=project_id)

    def _reviews(session: Session) -> list[Artifact]:
        return list(
            session.scalars(
                select(Artifact)
                .where(
                    Artifact.project_id == project_id,
                    Artifact.kind == ArtifactKind.advisor_review,
                )
                .order_by(Artifact.version)
            )
        )

    with Session(pg_engine) as session:
        [first] = _reviews(session)
        assert first.version == 1
        payload = first.payload
        assert payload is not None
        assert payload["commonality"]["verdict"] in {"very_common", "common", "uncommon", "novel"}
        assert payload["commonality"]["reasoning"]
        assert payload["comparative_strength"]
        assert payload["recruiter_impact"]
        assert payload["prerequisites"]
        assert payload["week_by_week"]
        assert "## Week-by-week plan" in first.content_md
        first_id = first.id

    # Regeneration appends v2 and keeps v1 untouched.
    with respx.mock:
        run_advisor_review(make_job(JobKind.generate_artifact), project_id=project_id)

    with Session(pg_engine) as session:
        reviews = _reviews(session)
        assert [review.version for review in reviews] == [1, 2]
        assert reviews[0].id == first_id


def test_advisor_review_for_missing_project_fails_cleanly(
    pg_engine: Engine,
    make_job: Callable[[JobKind], int],
) -> None:
    job_id = make_job(JobKind.generate_artifact)
    with respx.mock, pytest.raises(ValueError):
        run_advisor_review(job_id, project_id=999_999_999)
    job = _job(pg_engine, job_id)
    assert job.status is JobStatus.failed
    assert job.error == "ValueError"


# --- regenerate ---------------------------------------------------------------


def test_regenerate_replaces_generated_fields_and_preserves_user_state(
    pg_engine: Engine,
    make_items: Callable[..., list[int]],
    make_project: Callable[..., int],
    make_job: Callable[[JobKind], int],
) -> None:
    marker = uuid4().hex[:6]
    item_ids = make_items(_themed_texts(marker))
    project_id = make_project(
        title="User Edited Title",
        status=ProjectStatus.shortlisted,
        source={
            "item_ids": item_ids[:4],
            "cluster_ids": [],
            "prompt_version": "v1",
            "provider": "mock",
            "model": "mock-llm-v1",
        },
    )
    with Session(pg_engine, expire_on_commit=False) as session:
        milestone = ProjectMilestone(
            project_id=project_id, title="Week 1 setup", status=MilestoneStatus.todo
        )
        session.add(milestone)
        session.commit()
        milestone_id = milestone.id

    job_id = make_job(JobKind.generate_projects)
    with respx.mock:
        run_regenerate_project(job_id, project_id=project_id)

    with Session(pg_engine) as session:
        project = session.get(Project, project_id)
        assert project is not None
        # Generated fields replaced from the fresh (mock) generation…
        assert project.title != "User Edited Title"
        assert marker in project.title.lower()
        assert set(project.source["item_ids"]) <= set(item_ids[:4])
        # …while user-owned state survives.
        assert project.status is ProjectStatus.shortlisted
        kept = session.get(ProjectMilestone, milestone_id)
        assert kept is not None
        assert kept.title == "Week 1 setup"
    assert _job(pg_engine, job_id).status is JobStatus.succeeded
