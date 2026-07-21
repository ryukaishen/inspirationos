"""Career-artifact / project-library export (M8).

`POST /` mirrors `imports.py`'s accept sequence: insert the `exports` row
(`storage_key=NULL`) plus its `jobs` row in one transaction, then enqueue —
so a request that never got queued never leaves a "ready" row behind.
`GET /{id}/download` streams the file the `export_bundle` worker wrote
through the `Storage` abstraction.
"""

from collections.abc import Iterator
from typing import Annotated, BinaryIO

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from redis import Redis
from rq import Queue
from sqlalchemy.orm import Session

from app.config import get_config
from app.db import get_db_session
from app.models.export import Export
from app.models.job import Job, JobKind, JobStatus
from app.models.project import Project
from app.queues import QUEUE_AI
from app.redis_client import get_redis
from app.schemas.export import ExportAccepted, ExportRead, ExportRequest
from app.services.storage.base import Storage
from app.services.storage.local import LocalStorage

router = APIRouter(prefix="/exports", tags=["exports"])

EXPORT_NOT_FOUND_MESSAGE = "export not found"
PROJECT_NOT_FOUND_MESSAGE = "project not found"
QUEUE_UNAVAILABLE_MESSAGE = "job queue unavailable"
FILE_NOT_READY_MESSAGE = "export is not ready yet"

DbSession = Annotated[Session, Depends(get_db_session)]
RedisDep = Annotated[Redis, Depends(get_redis)]


def get_storage() -> Storage:
    return LocalStorage(get_config().data_dir)


StorageDep = Annotated[Storage, Depends(get_storage)]


def _iter_and_close(handle: BinaryIO) -> Iterator[bytes]:
    """Streaming a raw file object never closes it on its own — an explicit
    `finally` is required so the handle (and, on Windows, the file lock) is
    released as soon as the response finishes or the client disconnects."""
    try:
        while chunk := handle.read(65536):
            yield chunk
    finally:
        handle.close()


def _to_read(export_row: Export) -> ExportRead:
    return ExportRead(
        id=export_row.id,
        project_id=export_row.project_id,
        format=export_row.format,
        ready=export_row.storage_key is not None,
        size_bytes=export_row.size_bytes,
        error=export_row.error,
        created_at=export_row.created_at,
    )


@router.post("", response_model=ExportAccepted, status_code=status.HTTP_202_ACCEPTED)
def request_export(request: ExportRequest, db: DbSession, redis: RedisDep) -> ExportAccepted:
    if request.project_id is not None and db.get(Project, request.project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=PROJECT_NOT_FOUND_MESSAGE)

    export_row = Export(project_id=request.project_id, format=request.format)
    db.add(export_row)
    db.flush()
    job = Job(
        kind=JobKind.export_bundle,
        status=JobStatus.queued,
        total=1,
        payload={"export_id": export_row.id},
    )
    db.add(job)
    db.commit()

    try:
        rq_job = Queue(QUEUE_AI, connection=redis).enqueue(
            "app.workers.jobs.run_export_bundle", job.id, export_row.id
        )
    except Exception as exc:
        job.status = JobStatus.failed
        job.error = type(exc).__name__
        export_row.error = type(exc).__name__
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "queue_unavailable", "message": QUEUE_UNAVAILABLE_MESSAGE},
        ) from exc
    job.rq_job_id = rq_job.id
    export_row.job_id = job.id
    db.commit()
    return ExportAccepted(export_id=export_row.id, job_id=job.id)


@router.get("/{export_id}", response_model=ExportRead)
def get_export(export_id: int, db: DbSession) -> ExportRead:
    export_row = db.get(Export, export_id)
    if export_row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=EXPORT_NOT_FOUND_MESSAGE)
    return _to_read(export_row)


@router.get("/{export_id}/download")
def download_export(export_id: int, db: DbSession, storage: StorageDep) -> StreamingResponse:
    export_row = db.get(Export, export_id)
    if export_row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=EXPORT_NOT_FOUND_MESSAGE)
    if export_row.storage_key is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=FILE_NOT_READY_MESSAGE)

    extension = "md" if export_row.format.value == "markdown" else "json"
    media_type = "text/markdown" if extension == "md" else "application/json"
    scope = f"project-{export_row.project_id}" if export_row.project_id else "library"
    filename = f"export-{scope}-{export_row.id}.{extension}"

    return StreamingResponse(
        _iter_and_close(storage.open(export_row.storage_key)),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
