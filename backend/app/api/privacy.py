"""Complete-wipe trigger (M9). Raw-import and project deletion live on their
own resource routers (`imports.py`, `projects.py`) since they act on a
specific row; a full wipe is cross-cutting and has no natural resource home.

Mirrors the job-row-then-enqueue convention (`app/api/enqueue.py`); the
verification report is written into the job's `payload` by the worker
(`run_delete_data`) and surfaces through the existing `GET /api/jobs/{id}`
polling endpoint — no new read endpoint needed.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from redis import Redis
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.enqueue import enqueue_job
from app.db import get_db_session
from app.models.job import JobKind
from app.models.user import User
from app.queues import QUEUE_IMPORTS
from app.redis_client import get_redis
from app.schemas.privacy import WipeAccepted, WipeRequest

router = APIRouter(prefix="/privacy", tags=["privacy"])

CONFIRMATION_MISMATCH_MESSAGE = "confirmation text does not match"

DbSession = Annotated[Session, Depends(get_db_session)]
RedisDep = Annotated[Redis, Depends(get_redis)]
CurrentUser = Annotated[User, Depends(get_current_user)]


@router.post("/wipe", response_model=WipeAccepted, status_code=status.HTTP_202_ACCEPTED)
def request_wipe(
    body: WipeRequest, user: CurrentUser, db: DbSession, redis: RedisDep
) -> WipeAccepted:
    if body.confirm_email.strip().lower() != user.email.strip().lower():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "confirmation_mismatch", "message": CONFIRMATION_MISMATCH_MESSAGE},
        )
    job = enqueue_job(
        db,
        redis,
        kind=JobKind.delete_data,
        payload={},
        func_path="app.workers.jobs.run_delete_data",
        queue_name=QUEUE_IMPORTS,
    )
    return WipeAccepted(job_id=job.id)
