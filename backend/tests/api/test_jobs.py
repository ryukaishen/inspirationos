"""Jobs API against real Postgres and Redis."""

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from redis import Redis
from rq import Queue
from sqlalchemy.orm import Session

from app.models.job import Job, JobKind, JobStatus
from app.queues import QUEUE_IMPORTS

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def clean_queue(redis_client: Redis) -> Generator[None, None, None]:
    """Enqueued demo payloads must never leak to a real worker after the test."""
    yield
    Queue(QUEUE_IMPORTS, connection=redis_client).empty()


def test_enqueue_demo_job_creates_queued_row(client: TestClient, db_session: Session) -> None:
    response = client.post("/api/jobs/demo", json={"steps": 3, "step_seconds": 0})
    assert response.status_code == 202
    body = response.json()
    assert body["kind"] == "demo"
    assert body["status"] == "queued"
    assert body["total"] == 3
    assert body["progress"] == 0
    assert body["rq_job_id"]

    job = db_session.get(Job, body["id"])
    assert job is not None
    assert job.kind is JobKind.demo
    assert job.status is JobStatus.queued
    assert job.payload["steps"] == 3


def test_enqueue_demo_job_rejects_invalid_steps(client: TestClient) -> None:
    response = client.post("/api/jobs/demo", json={"steps": 0})
    assert response.status_code == 422


def test_get_job_returns_row(client: TestClient, db_session: Session) -> None:
    job = Job(kind=JobKind.demo, status=JobStatus.queued, total=5, payload={"steps": 5})
    db_session.add(job)
    db_session.commit()

    response = client.get(f"/api/jobs/{job.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == job.id
    assert body["status"] == "queued"
    assert body["total"] == 5


def test_get_job_missing_returns_404(client: TestClient) -> None:
    response = client.get("/api/jobs/999999999")
    assert response.status_code == 404
