"""RQ tasks. Convention for every task in this app:

- receives IDs (and scalar knobs) only — never message content;
- owns the `jobs` row lifecycle: running → succeeded/failed, with progress;
- is safe to re-run: a finished job is a no-op;
- records only the exception class name in `jobs.error` (redaction rule).
"""

import time
from datetime import UTC, datetime

from app.db import get_sessionmaker
from app.models.job import Job, JobStatus


def _utcnow() -> datetime:
    return datetime.now(UTC)


def run_demo_job(
    job_id: int,
    steps: int = 10,
    step_seconds: float = 0.5,
    fail_at_step: int | None = None,
) -> None:
    """Demo task proving the job loop: queued → running (chunked progress) → succeeded.

    `fail_at_step` exercises the failure path (used by tests and manual checks).
    """
    with get_sessionmaker()() as session:
        job = session.get(Job, job_id)
        if job is None:
            raise ValueError(f"jobs row {job_id} does not exist")
        if job.status in (JobStatus.succeeded, JobStatus.cancelled):
            return
        job.status = JobStatus.running
        job.started_at = _utcnow()
        job.progress = 0
        job.total = steps
        session.commit()
        try:
            for step in range(1, steps + 1):
                if fail_at_step is not None and step == fail_at_step:
                    raise RuntimeError("demo job failure requested")
                if step_seconds:
                    time.sleep(step_seconds)
                job.progress = step
                session.commit()
            job.status = JobStatus.succeeded
            job.finished_at = _utcnow()
            session.commit()
        except Exception as exc:
            session.rollback()
            job.status = JobStatus.failed
            job.error = type(exc).__name__
            job.finished_at = _utcnow()
            session.commit()
            raise
