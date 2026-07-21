"""Career-artifact API (M8): generic trigger/list/summary endpoints for the
five career-artifact kinds. Against real Postgres + Redis through the
dependency-injected rolled-back test transaction, following test_projects.py's
conventions (`_make_project`, `clean_ai_queue`)."""

from collections.abc import Generator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from redis import Redis
from rq import Queue
from sqlalchemy.orm import Session

from app.models.artifact import Artifact, ArtifactKind
from app.models.job import Job, JobKind
from app.models.project import Project
from app.queues import QUEUE_AI
from app.services.generation.scoring import SCORE_DIMENSIONS

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def clean_ai_queue(redis_client: Redis) -> Generator[None, None, None]:
    yield
    Queue(QUEUE_AI, connection=redis_client).empty()


def _make_project(db_session: Session, **overrides: object) -> int:
    marker = uuid4().hex[:8]
    fields: dict = {
        "title": f"Artifact project {marker}",
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


def _add_artifact(db_session: Session, project_id: int, kind: ArtifactKind, version: int) -> None:
    db_session.add(
        Artifact(
            project_id=project_id,
            kind=kind,
            content_md=f"## {kind.value} v{version}",
            payload={"marker": f"v{version}"},
            claims_flags=["achieved 97%"] if version == 2 else [],
            provider="mock",
            model="mock-llm-v1",
            prompt_version="v1",
            version=version,
        )
    )
    db_session.commit()


# --- trigger --------------------------------------------------------------


def test_career_artifact_trigger_creates_generate_artifact_job(
    client: TestClient, db_session: Session
) -> None:
    project_id = _make_project(db_session)
    response = client.post(f"/api/projects/{project_id}/artifacts/readme")
    assert response.status_code == 202
    job = db_session.get(Job, response.json()["job_id"])
    assert job is not None
    assert job.kind is JobKind.generate_artifact
    assert job.payload == {"project_id": project_id, "kind": "readme"}


def test_career_artifact_trigger_404s_unknown_project(client: TestClient) -> None:
    assert client.post("/api/projects/999999999/artifacts/readme").status_code == 404


def test_career_artifact_trigger_rejects_unknown_kind(
    client: TestClient, db_session: Session
) -> None:
    project_id = _make_project(db_session)
    response = client.post(f"/api/projects/{project_id}/artifacts/not_a_kind")
    assert response.status_code == 422


def test_career_artifact_trigger_rejects_advisor_review_kind(
    client: TestClient, db_session: Session
) -> None:
    # advisor_review keeps its own dedicated /advisor endpoints, not this
    # generic one — it's a valid ArtifactKind but not a CareerArtifactKind.
    project_id = _make_project(db_session)
    response = client.post(f"/api/projects/{project_id}/artifacts/advisor_review")
    assert response.status_code == 422


# --- list versions ----------------------------------------------------------


def test_career_artifact_versions_listed_newest_first(
    client: TestClient, db_session: Session
) -> None:
    project_id = _make_project(db_session)
    assert client.get(f"/api/projects/{project_id}/artifacts/readme").json() == []

    _add_artifact(db_session, project_id, ArtifactKind.readme, version=1)
    _add_artifact(db_session, project_id, ArtifactKind.readme, version=2)

    versions = client.get(f"/api/projects/{project_id}/artifacts/readme").json()
    assert [entry["version"] for entry in versions] == [2, 1]
    assert versions[0]["claims_flags"] == ["achieved 97%"]
    assert versions[1]["claims_flags"] == []

    assert client.get("/api/projects/999999999/artifacts/readme").status_code == 404


def test_career_artifact_kinds_are_independently_versioned(
    client: TestClient, db_session: Session
) -> None:
    project_id = _make_project(db_session)
    _add_artifact(db_session, project_id, ArtifactKind.readme, version=1)
    _add_artifact(db_session, project_id, ArtifactKind.resume_bullets, version=1)

    readme_versions = client.get(f"/api/projects/{project_id}/artifacts/readme").json()
    resume_versions = client.get(f"/api/projects/{project_id}/artifacts/resume_bullets").json()
    assert len(readme_versions) == 1
    assert len(resume_versions) == 1
    assert readme_versions[0]["kind"] == "readme"
    assert resume_versions[0]["kind"] == "resume_bullets"


# --- summary ------------------------------------------------------------------


def test_list_all_artifacts_returns_latest_per_kind(
    client: TestClient, db_session: Session
) -> None:
    project_id = _make_project(db_session)
    assert client.get(f"/api/projects/{project_id}/artifacts").json() == []

    _add_artifact(db_session, project_id, ArtifactKind.readme, version=1)
    _add_artifact(db_session, project_id, ArtifactKind.readme, version=2)
    _add_artifact(db_session, project_id, ArtifactKind.tech_questions, version=1)

    summary = client.get(f"/api/projects/{project_id}/artifacts").json()
    by_kind = {entry["kind"]: entry for entry in summary}
    assert set(by_kind) == {"readme", "tech_questions"}
    assert by_kind["readme"]["version"] == 2  # latest only, v1 excluded

    assert client.get("/api/projects/999999999/artifacts").status_code == 404
