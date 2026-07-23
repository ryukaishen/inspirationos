"""Stale-job reconciliation: a worker that dies hard mid-job (kill/crash/
reboot, not a clean exception or a graceful SIGTERM) leaves its `jobs` row
stuck at `running` forever, since RQ's own dead-worker bookkeeping never
writes back to this table — confirmed empirically in a live drill, see
docs/REAL_DATA_VERIFICATION.md. `services/jobs.py::reconcile_stale_job` is
the fix: every read of a job past `job_stale_after_seconds` self-heals it
to `failed` in place. Uses the ordinary savepoint-scoped `db_session`/
`client` fixtures — no real-commit pattern needed, this never touches a
worker process.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import get_config
from app.models.import_ import ExportFormat, Import, ImportStatus
from app.models.job import Job, JobKind, JobStatus
from app.services.jobs import STALE_JOB_ERROR


@pytest.fixture
def short_stale_threshold(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv("JOB_STALE_AFTER_SECONDS", "1")
    get_config.cache_clear()
    yield
    get_config.cache_clear()


def _make_running_job(
    db_session: Session, *, kind: JobKind = JobKind.demo, age_seconds: int
) -> int:
    job = Job(
        kind=kind,
        status=JobStatus.running,
        total=10,
        progress=3,
        started_at=datetime.now(UTC) - timedelta(seconds=age_seconds),
    )
    db_session.add(job)
    db_session.commit()
    return job.id


def test_stale_running_job_reconciled_on_read(
    client: TestClient, db_session: Session, short_stale_threshold: None
) -> None:
    job_id = _make_running_job(db_session, age_seconds=5)  # past the 1s threshold

    response = client.get(f"/api/jobs/{job_id}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "failed"
    assert body["error"] == STALE_JOB_ERROR
    assert body["finished_at"] is not None


def test_fresh_running_job_not_reconciled(client: TestClient, db_session: Session) -> None:
    """Default threshold (30 min) — a job started moments ago stays `running`."""
    job_id = _make_running_job(db_session, age_seconds=1)

    response = client.get(f"/api/jobs/{job_id}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "running"
    assert body["error"] is None


def test_non_running_status_untouched(
    client: TestClient, db_session: Session, short_stale_threshold: None
) -> None:
    job = Job(
        kind=JobKind.demo,
        status=JobStatus.succeeded,
        total=10,
        progress=10,
        started_at=datetime.now(UTC) - timedelta(seconds=999),
        finished_at=datetime.now(UTC) - timedelta(seconds=998),
    )
    db_session.add(job)
    db_session.commit()

    response = client.get(f"/api/jobs/{job.id}")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "succeeded"
    assert response.json()["error"] is None


def test_import_detail_reconciles_its_latest_scan_job(
    client: TestClient, db_session: Session, short_stale_threshold: None
) -> None:
    import_row = Import(
        filename="stale-job-drill.zip",
        storage_key=None,
        size_bytes=1,
        checksum_sha256="1" * 64,
        export_format=ExportFormat.json,
        status=ImportStatus.scanning,
    )
    db_session.add(import_row)
    db_session.flush()
    job = Job(
        kind=JobKind.import_scan,
        status=JobStatus.running,
        total=1,
        started_at=datetime.now(UTC) - timedelta(seconds=5),
        payload={"import_id": import_row.id},
    )
    db_session.add(job)
    db_session.commit()

    response = client.get(f"/api/imports/{import_row.id}")

    assert response.status_code == 200, response.text
    latest_job = response.json()["latest_job"]
    assert latest_job["status"] == "failed"
    assert latest_job["error"] == STALE_JOB_ERROR
