"""Project workspace API (M7): triggers, library, milestones, advisor reads,
career profile, and scoring-weights settings. Against real Postgres + Redis
through the dependency-injected rolled-back test transaction."""

from collections.abc import Generator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from redis import Redis
from rq import Queue
from sqlalchemy.orm import Session

from app.models.artifact import Artifact, ArtifactKind
from app.models.item import Item, ItemStatus, ItemType
from app.models.job import Job, JobKind
from app.models.project import Project, ProjectMilestone, ProjectStatus
from app.queues import QUEUE_AI
from app.services.generation.scoring import SCORE_DIMENSIONS

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def clean_ai_queue(redis_client: Redis) -> Generator[None, None, None]:
    """Enqueued generation payloads must never leak to a real worker."""
    yield
    Queue(QUEUE_AI, connection=redis_client).empty()


def _make_items(db_session: Session, texts: list[str | None]) -> list[int]:
    marker = uuid4().hex[:8]
    items = [
        Item(
            url_raw=f"https://www.instagram.com/reel/PRJ{marker}{index}/",
            url_canonical=f"https://www.instagram.com/reel/PRJ{marker}{index}/",
            item_type=ItemType.reel,
            status=ItemStatus.new if text else ItemStatus.needs_context,
            share_text=text,
        )
        for index, text in enumerate(texts)
    ]
    db_session.add_all(items)
    db_session.commit()
    return [item.id for item in items]


def _make_project(db_session: Session, **overrides: object) -> int:
    marker = uuid4().hex[:8]
    fields: dict = {
        "title": f"Library project {marker}",
        "one_liner": f"One-liner {marker}",
        "summary_md": f"Summary {marker}",
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
    project = Project(**fields)
    db_session.add(project)
    db_session.commit()
    return project.id


# --- generate -----------------------------------------------------------------


def test_generate_rejects_empty_selection(client: TestClient) -> None:
    response = client.post("/api/projects/generate", json={})
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "no_sources"


def test_generate_404s_unknown_cluster_and_item_ids(
    client: TestClient, db_session: Session
) -> None:
    response = client.post("/api/projects/generate", json={"cluster_ids": [999_999_999]})
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "unknown_clusters"

    response = client.post("/api/projects/generate", json={"item_ids": [999_999_999]})
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "unknown_items"


def test_generate_rejects_selection_with_no_eligible_text(
    client: TestClient, db_session: Session
) -> None:
    item_ids = _make_items(db_session, [None, None])
    response = client.post("/api/projects/generate", json={"item_ids": item_ids})
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "no_eligible_items"


def test_generate_accepts_and_creates_id_only_job(client: TestClient, db_session: Session) -> None:
    marker = uuid4().hex[:6]
    item_ids = _make_items(db_session, [f"climbing{marker} text", None])
    response = client.post("/api/projects/generate", json={"item_ids": item_ids, "count": 99})
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    job = db_session.get(Job, job_id)
    assert job is not None
    assert job.kind is JobKind.generate_projects
    # Payload carries IDs and scalars only — and the count is clamped.
    assert set(job.payload) == {"item_ids", "cluster_ids", "count"}
    assert job.payload["item_ids"] == item_ids
    assert job.payload["count"] == 10
    assert marker not in str(job.payload)


# --- combine ------------------------------------------------------------------


def test_combine_validates_parents(client: TestClient, db_session: Session) -> None:
    project_id = _make_project(db_session)

    response = client.post(
        "/api/projects/combine", json={"parent_project_ids": [project_id, project_id]}
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "bad_parents"

    response = client.post(
        "/api/projects/combine", json={"parent_project_ids": [project_id, 999_999_999]}
    )
    assert response.status_code == 404


def test_combine_accepts_two_existing_parents(client: TestClient, db_session: Session) -> None:
    parent_a = _make_project(db_session)
    parent_b = _make_project(db_session)
    response = client.post(
        "/api/projects/combine", json={"parent_project_ids": [parent_a, parent_b]}
    )
    assert response.status_code == 202
    job = db_session.get(Job, response.json()["job_id"])
    assert job is not None
    assert job.kind is JobKind.generate_projects
    assert job.payload == {"parent_project_ids": [parent_a, parent_b]}


# --- library reads + editing --------------------------------------------------


def test_list_projects_filters_by_status_and_domain(
    client: TestClient, db_session: Session
) -> None:
    idea_id = _make_project(db_session, domains=["data science"])
    planned_id = _make_project(db_session, status=ProjectStatus.planned, domains=["quant finance"])

    listed = client.get("/api/projects").json()
    listed_ids = {project["id"] for project in listed["projects"]}
    assert {idea_id, planned_id} <= listed_ids

    by_status = client.get("/api/projects", params={"status": "planned"}).json()
    by_status_ids = {project["id"] for project in by_status["projects"]}
    assert planned_id in by_status_ids
    assert idea_id not in by_status_ids

    by_domain = client.get("/api/projects", params={"domain": "quant finance"}).json()
    by_domain_ids = {project["id"] for project in by_domain["projects"]}
    assert planned_id in by_domain_ids
    assert idea_id not in by_domain_ids


def test_project_detail_includes_ordered_milestones(
    client: TestClient, db_session: Session
) -> None:
    project_id = _make_project(db_session)
    db_session.add_all(
        [
            ProjectMilestone(project_id=project_id, title="Second", sort_order=1),
            ProjectMilestone(project_id=project_id, title="First", sort_order=0),
        ]
    )
    db_session.commit()

    detail = client.get(f"/api/projects/{project_id}").json()
    assert [milestone["title"] for milestone in detail["milestones"]] == ["First", "Second"]
    for dimension in SCORE_DIMENSIONS:
        assert detail["scores"][dimension]["rationale"]

    assert client.get("/api/projects/999999999").status_code == 404


def test_patch_project_edits_fields_only_when_present(
    client: TestClient, db_session: Session
) -> None:
    project_id = _make_project(db_session)
    response = client.patch(
        f"/api/projects/{project_id}",
        json={"title": "Edited Title", "status": "shortlisted"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Edited Title"
    assert body["status"] == "shortlisted"
    # Untouched fields survive.
    assert body["tech_stack"] == ["python"]

    project = db_session.get(Project, project_id)
    assert project is not None
    assert project.title == "Edited Title"
    assert project.status is ProjectStatus.shortlisted


# --- milestones ---------------------------------------------------------------


def test_milestone_crud_and_reorder(client: TestClient, db_session: Session) -> None:
    project_id = _make_project(db_session)

    first = client.post(f"/api/projects/{project_id}/milestones", json={"title": "Set up repo"})
    second = client.post(
        f"/api/projects/{project_id}/milestones",
        json={"title": "Build baseline", "status": "doing"},
    )
    assert first.status_code == second.status_code == 201
    first_id, second_id = first.json()["id"], second.json()["id"]
    assert first.json()["sort_order"] == 0
    assert second.json()["sort_order"] == 1

    patched = client.patch(
        f"/api/projects/{project_id}/milestones/{first_id}",
        json={"status": "done", "target_date": "2026-08-01"},
    )
    assert patched.status_code == 200
    assert patched.json()["status"] == "done"
    assert patched.json()["target_date"] == "2026-08-01"

    reordered = client.put(
        f"/api/projects/{project_id}/milestones/order",
        json={"milestone_ids": [second_id, first_id]},
    )
    assert reordered.status_code == 200
    assert [milestone["id"] for milestone in reordered.json()] == [second_id, first_id]
    assert [milestone["sort_order"] for milestone in reordered.json()] == [0, 1]

    # Persisted: the detail view reflects the new order.
    detail = client.get(f"/api/projects/{project_id}").json()
    assert [milestone["id"] for milestone in detail["milestones"]] == [second_id, first_id]

    deleted = client.delete(f"/api/projects/{project_id}/milestones/{first_id}")
    assert deleted.status_code == 204
    assert db_session.get(ProjectMilestone, first_id) is None
    assert db_session.get(ProjectMilestone, second_id) is not None


def test_milestone_reorder_rejects_non_permutations(
    client: TestClient, db_session: Session
) -> None:
    project_id = _make_project(db_session)
    milestone = client.post(
        f"/api/projects/{project_id}/milestones", json={"title": "Only one"}
    ).json()

    for bad_ids in ([999_999_999], [milestone["id"], 999_999_999], [milestone["id"]] * 2):
        response = client.put(
            f"/api/projects/{project_id}/milestones/order", json={"milestone_ids": bad_ids}
        )
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "bad_order"


def test_milestone_of_other_project_is_not_reachable(
    client: TestClient, db_session: Session
) -> None:
    project_a = _make_project(db_session)
    project_b = _make_project(db_session)
    milestone = client.post(f"/api/projects/{project_a}/milestones", json={"title": "A's"}).json()

    response = client.patch(
        f"/api/projects/{project_b}/milestones/{milestone['id']}", json={"title": "hijack"}
    )
    assert response.status_code == 404


# --- advisor reads ------------------------------------------------------------


def test_advisor_versions_listed_newest_first(client: TestClient, db_session: Session) -> None:
    project_id = _make_project(db_session)
    assert client.get(f"/api/projects/{project_id}/advisor").json() == []

    for version in (1, 2):
        db_session.add(
            Artifact(
                project_id=project_id,
                kind=ArtifactKind.advisor_review,
                content_md=f"## Review v{version}",
                payload={"comparative_strength": f"v{version}"},
                provider="mock",
                model="mock-llm-v1",
                prompt_version="v1",
                version=version,
            )
        )
    db_session.commit()

    reviews = client.get(f"/api/projects/{project_id}/advisor").json()
    assert [review["version"] for review in reviews] == [2, 1]
    assert reviews[0]["payload"] == {"comparative_strength": "v2"}

    assert client.get("/api/projects/999999999/advisor").status_code == 404


def test_advisor_trigger_creates_generate_artifact_job(
    client: TestClient, db_session: Session
) -> None:
    project_id = _make_project(db_session)
    response = client.post(f"/api/projects/{project_id}/advisor")
    assert response.status_code == 202
    job = db_session.get(Job, response.json()["job_id"])
    assert job is not None
    assert job.kind is JobKind.generate_artifact
    assert job.payload == {"project_id": project_id}

    assert client.post("/api/projects/999999999/advisor").status_code == 404


def test_regenerate_trigger_creates_job(client: TestClient, db_session: Session) -> None:
    project_id = _make_project(db_session)
    response = client.post(f"/api/projects/{project_id}/regenerate")
    assert response.status_code == 202
    job = db_session.get(Job, response.json()["job_id"])
    assert job is not None
    assert job.kind is JobKind.generate_projects
    assert job.payload == {"project_id": project_id}


# --- career profile -----------------------------------------------------------


def test_career_profile_roundtrip(client: TestClient, db_session: Session) -> None:
    initial = client.get("/api/career-profile")
    assert initial.status_code == 200

    payload = {
        "background_md": "UF student focused on healthcare AI.",
        "skills": ["python", "sql", "pytorch"],
        "target_domains": ["healthcare ai", "quant finance"],
        "experience_level": "intermediate",
        "constraints": {"hours_per_week": 10, "compute": "laptop"},
        "interests_md": "Clinical NLP.",
    }
    updated = client.put("/api/career-profile", json=payload)
    assert updated.status_code == 200
    assert updated.json() == payload

    assert client.get("/api/career-profile").json() == payload

    # Unknown fields are rejected, not silently dropped.
    assert client.put("/api/career-profile", json={**payload, "surprise": 1}).status_code == 422


# --- scoring weights settings -------------------------------------------------


def test_scoring_weights_roundtrip_and_validation(client: TestClient) -> None:
    settings = client.get("/api/settings").json()
    assert "scoring_weights" in settings

    updated = client.patch(
        "/api/settings/scoring",
        json={"scoring_weights": {"originality": 2.0, "feasibility": 0.5}},
    )
    assert updated.status_code == 200
    assert updated.json()["scoring_weights"] == {"originality": 2.0, "feasibility": 0.5}

    for bad_weights in ({"vibes": 1.0}, {"originality": 2.5}, {"feasibility": -1.0}):
        response = client.patch("/api/settings/scoring", json={"scoring_weights": bad_weights})
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "invalid_weights"
