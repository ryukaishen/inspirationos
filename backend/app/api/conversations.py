"""Conversation listing and selection for a scanned import.

Selection uses replace semantics (the request is the full desired selection)
and immediately enqueues the extract job — one transaction inserts the `jobs`
row, then enqueue failure marks it failed and returns 503, mirroring the
upload endpoint. A `failed` import with a stored file stays selectable so a
failed extract can be retried.

Error payloads are static strings and IDs only — never conversation titles
or message content.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from redis import Redis
from rq import Queue
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.imports import QUEUE_UNAVAILABLE_MESSAGE
from app.db import get_db_session
from app.models.conversation import Conversation
from app.models.import_ import Import, ImportStatus
from app.models.job import Job, JobKind, JobStatus
from app.queues import QUEUE_IMPORTS
from app.redis_client import get_redis
from app.schemas.conversation import ConversationRead, ExtractAccepted, SelectionRequest

router = APIRouter(prefix="/imports/{import_id}/conversations", tags=["conversations"])

NOT_READY_MESSAGE = "import has not been scanned yet"
NO_STORED_FILE_MESSAGE = "import has no stored ZIP to extract from"
UNKNOWN_CONVERSATIONS_MESSAGE = "some conversation ids do not belong to this import"

SELECTABLE_STATUSES = (ImportStatus.scanned, ImportStatus.extracted, ImportStatus.failed)

DbSession = Annotated[Session, Depends(get_db_session)]
RedisDep = Annotated[Redis, Depends(get_redis)]


def _get_import_or_404(db: Session, import_id: int) -> Import:
    import_row = db.get(Import, import_id)
    if import_row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="import not found")
    return import_row


@router.get("", response_model=list[ConversationRead])
def list_conversations(import_id: int, db: DbSession) -> list[Conversation]:
    _get_import_or_404(db, import_id)
    return list(
        db.scalars(
            select(Conversation)
            .where(Conversation.import_id == import_id)
            .order_by(Conversation.id)
        ).all()
    )


@router.post("/selection", response_model=ExtractAccepted, status_code=status.HTTP_202_ACCEPTED)
def select_conversations(
    import_id: int, body: SelectionRequest, db: DbSession, redis: RedisDep
) -> ExtractAccepted:
    import_row = _get_import_or_404(db, import_id)
    if import_row.storage_key is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "no_stored_file", "message": NO_STORED_FILE_MESSAGE},
        )
    if import_row.status not in SELECTABLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "not_ready", "message": NOT_READY_MESSAGE},
        )

    conversations = list(
        db.scalars(select(Conversation).where(Conversation.import_id == import_id)).all()
    )
    requested = set(body.conversation_ids)
    known = {conversation.id for conversation in conversations}
    if not requested <= known:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "unknown_conversations", "message": UNKNOWN_CONVERSATIONS_MESSAGE},
        )

    for conversation in conversations:
        conversation.is_selected = conversation.id in requested
    job = Job(
        kind=JobKind.import_extract,
        status=JobStatus.queued,
        total=len(requested),
        payload={"import_id": import_id},  # IDs only — never content
    )
    db.add(job)
    db.commit()

    try:
        rq_job = Queue(QUEUE_IMPORTS, connection=redis).enqueue(
            "app.workers.jobs.run_import_extract", job.id, import_id
        )
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
    return ExtractAccepted(job_id=job.id)
