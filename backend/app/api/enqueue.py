"""Shared jobs-row-then-enqueue helper (extracted from clusters.py in M7 so
the projects router doesn't duplicate it). Payloads carry IDs and scalar
knobs only — never item or message content."""

from fastapi import HTTPException, status
from redis import Redis
from rq import Queue
from sqlalchemy.orm import Session

from app.models.job import Job, JobKind, JobStatus
from app.queues import QUEUE_AI

QUEUE_UNAVAILABLE_MESSAGE = "job queue unavailable"


def enqueue_job(
    db: Session,
    redis: Redis,
    *,
    kind: JobKind,
    payload: dict[str, object],
    func_path: str,
    queue_name: str = QUEUE_AI,
) -> Job:
    """Jobs-row-then-enqueue; enqueue failure marks the row failed and 503s."""
    job = Job(kind=kind, status=JobStatus.queued, payload=payload)
    db.add(job)
    db.commit()
    db.refresh(job)
    try:
        rq_job = Queue(queue_name, connection=redis).enqueue(func_path, job.id, **payload)
    except Exception as exc:
        job.status = JobStatus.failed
        job.error = type(exc).__name__
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "queue_unavailable", "message": QUEUE_UNAVAILABLE_MESSAGE},
        ) from exc
    job.rq_job_id = rq_job.id
    db.commit()
    return job
