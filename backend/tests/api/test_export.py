"""Export API (M8): request/read/download for career-artifact and
project-library export bundles. Against real Postgres + Redis through the
dependency-injected rolled-back test transaction."""

from collections.abc import Generator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from redis import Redis
from rq import Queue
from sqlalchemy.orm import Session

from app.config import get_config
from app.models.export import Export, ExportBundleFormat
from app.models.job import Job, JobKind
from app.models.project import Project
from app.queues import QUEUE_AI
from app.services.generation.scoring import SCORE_DIMENSIONS
from app.services.storage.local import LocalStorage

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def clean_ai_queue(redis_client: Redis) -> Generator[None, None, None]:
    yield
    Queue(QUEUE_AI, connection=redis_client).empty()


def _make_project(db_session: Session, **overrides: object) -> int:
    marker = uuid4().hex[:8]
    fields: dict = {
        "title": f"Export project {marker}",
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


def _make_export(db_session: Session, **overrides: object) -> int:
    fields: dict = {"format": ExportBundleFormat.markdown, "project_id": None}
    fields.update(overrides)
    export_row = Export(**fields)
    db_session.add(export_row)
    db_session.commit()
    return export_row.id


# --- request ------------------------------------------------------------------


def test_request_project_export_creates_export_and_job(
    client: TestClient, db_session: Session
) -> None:
    project_id = _make_project(db_session)
    response = client.post("/api/exports", json={"format": "markdown", "project_id": project_id})
    assert response.status_code == 202
    body = response.json()

    export_row = db_session.get(Export, body["export_id"])
    assert export_row is not None
    assert export_row.project_id == project_id
    assert export_row.format is ExportBundleFormat.markdown
    assert export_row.storage_key is None

    job = db_session.get(Job, body["job_id"])
    assert job is not None
    assert job.kind is JobKind.export_bundle
    assert job.payload == {"export_id": export_row.id}


def test_request_library_export_has_null_project_id(
    client: TestClient, db_session: Session
) -> None:
    response = client.post("/api/exports", json={"format": "json"})
    assert response.status_code == 202
    export_row = db_session.get(Export, response.json()["export_id"])
    assert export_row is not None
    assert export_row.project_id is None
    assert export_row.format is ExportBundleFormat.json


def test_request_export_404s_unknown_project(client: TestClient) -> None:
    response = client.post("/api/exports", json={"format": "markdown", "project_id": 999999999})
    assert response.status_code == 404


# --- read -----------------------------------------------------------------


def test_get_export_reports_readiness(client: TestClient, db_session: Session) -> None:
    export_id = _make_export(db_session)
    pending = client.get(f"/api/exports/{export_id}").json()
    assert pending["ready"] is False
    assert pending["size_bytes"] is None
    assert pending["error"] is None

    export_row = db_session.get(Export, export_id)
    assert export_row is not None
    export_row.storage_key = "exports/does-not-matter.md"
    export_row.size_bytes = 42
    db_session.commit()

    ready = client.get(f"/api/exports/{export_id}").json()
    assert ready["ready"] is True
    assert ready["size_bytes"] == 42


def test_get_export_404s_unknown_id(client: TestClient) -> None:
    assert client.get("/api/exports/999999999").status_code == 404


# --- download -------------------------------------------------------------


def test_download_export_409s_when_not_ready(client: TestClient, db_session: Session) -> None:
    export_id = _make_export(db_session)
    assert client.get(f"/api/exports/{export_id}/download").status_code == 409


def test_download_export_404s_unknown_id(client: TestClient) -> None:
    assert client.get("/api/exports/999999999/download").status_code == 404


def test_download_export_streams_markdown_with_headers(
    client: TestClient, db_session: Session
) -> None:
    storage = LocalStorage(get_config().data_dir)
    content = b"# Hello export\n"
    spool_path = storage.spool_dir() / f"test-{uuid4().hex}.md"
    spool_path.write_bytes(content)
    storage_key = f"exports/{uuid4().hex}.md"
    storage.save_file(storage_key, spool_path)

    export_id = _make_export(
        db_session,
        format=ExportBundleFormat.markdown,
        storage_key=storage_key,
        size_bytes=len(content),
    )

    response = client.get(f"/api/exports/{export_id}/download")
    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-type"].startswith("text/markdown")
    assert "attachment" in response.headers["content-disposition"]

    storage.delete(storage_key)
