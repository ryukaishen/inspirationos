from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from redis import Redis
from rq import Queue
from sqlalchemy.orm import Session

from app.db import get_db_session
from app.models.job import Job, JobKind, JobStatus
from app.queues import QUEUE_IMPORTS
from app.redis_client import get_redis
from app.schemas.job import DemoJobRequest, JobRead

router = APIRouter(prefix="/jobs", tags=["jobs"])

DbSession = Annotated[Session, Depends(get_db_session)]
RedisDep = Annotated[Redis, Depends(get_redis)]


@router.post("/demo", response_model=JobRead, status_code=status.HTTP_202_ACCEPTED)
def enqueue_demo_job(db: DbSession, redis: RedisDep, body: DemoJobRequest | None = None) -> Job:
    """Every enqueue creates a `jobs` row first; the task owns all later updates."""
    params = body or DemoJobRequest()
    job = Job(
        kind=JobKind.demo,
        status=JobStatus.queued,
        total=params.steps,
        payload={"steps": params.steps, "step_seconds": params.step_seconds},
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    try:
        queue = Queue(QUEUE_IMPORTS, connection=redis)
        rq_job = queue.enqueue(
            "app.workers.jobs.run_demo_job", job.id, params.steps, params.step_seconds
        )
    except Exception as exc:
        job.status = JobStatus.failed
        job.error = type(exc).__name__
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="job queue unavailable"
        ) from exc
    job.rq_job_id = rq_job.id
    db.commit()
    return job


@router.get("/{job_id}", response_model=JobRead)
def get_job(job_id: int, db: DbSession) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
    return job
