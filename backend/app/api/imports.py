"""Secure export-ZIP upload and import listing.

Upload design (see ARCHITECTURE.md "Upload & storage"):

- The ZIP arrives as the **raw request body** (not multipart): multipart parsing
  would consume the whole body before endpoint code runs, defeating the
  "reject oversized uploads before the body is fully read" requirement.
- Transaction-safe sequence: spool → validate → promote file → ONE transaction
  inserting the `imports` row plus its single `import_scan` `jobs` row → enqueue.
  Every failure path below deletes or retains files so that rows and files stay
  mutually consistent; the spool file is always removed in `finally`.
- Dedupe: an application-level pre-check gives friendly early 409s, but the
  authoritative, race-safe guard is the partial unique index on
  `imports.checksum_sha256` (active rows only) — a concurrent duplicate insert
  surfaces as `IntegrityError` and is mapped to the same 409.

Error payloads are static strings and IDs only — never file contents.
"""

import contextlib
import hashlib
import re
from dataclasses import dataclass
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from redis import Redis
from rq import Queue
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_config
from app.db import get_db_session
from app.models.import_ import ExportFormat, Import, ImportStatus
from app.models.job import Job, JobKind, JobStatus
from app.queues import QUEUE_IMPORTS
from app.redis_client import get_redis
from app.schemas.import_ import ImportDetail, ImportRead, ImportVerificationReport, UploadAccepted
from app.schemas.job import JobRead
from app.schemas.privacy import ImportDeletionReport, ImportDeletionRequest
from app.services.ingest.format_detection import ExportKind, detect_export_format
from app.services.ingest.verification import build_verification_report
from app.services.ingest.zip_safety import ZipLimits, ZipRejectedError, validate_zip
from app.services.privacy.deletion import delete_raw_import
from app.services.storage.base import Storage
from app.services.storage.local import LocalStorage

router = APIRouter(prefix="/imports", tags=["imports"])

HTML_EXPORT_MESSAGE = (
    "This export is in HTML format, which cannot be parsed. "
    "Re-request your Instagram data export in JSON format, then upload the new ZIP."
)
UNRECOGNIZED_MESSAGE = (
    "This ZIP is not recognized as an Instagram JSON export "
    "(no messages/<inbox|message_requests|filtered_threads|archived_threads>/*/"
    "message_*.json entries found)."
)
TOO_LARGE_MESSAGE = "upload exceeds the maximum allowed size"
QUEUE_UNAVAILABLE_MESSAGE = "job queue unavailable"

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True)
class UploadPolicy:
    max_upload_bytes: int
    zip_limits: ZipLimits


def get_upload_policy() -> UploadPolicy:
    config = get_config()
    return UploadPolicy(
        max_upload_bytes=config.max_upload_size_mb * 1024 * 1024,
        zip_limits=ZipLimits(
            max_entries=config.max_zip_entries,
            max_total_uncompressed_bytes=config.max_zip_uncompressed_mb * 1024 * 1024,
            max_compression_ratio=config.max_zip_compression_ratio,
        ),
    )


def get_storage() -> Storage:
    return LocalStorage(get_config().data_dir)


DbSession = Annotated[Session, Depends(get_db_session)]
RedisDep = Annotated[Redis, Depends(get_redis)]
StorageDep = Annotated[Storage, Depends(get_storage)]
PolicyDep = Annotated[UploadPolicy, Depends(get_upload_policy)]


def sanitize_filename(raw: str | None) -> str:
    """Display metadata only — never used in filesystem paths or logs."""
    if not raw:
        return "export.zip"
    name = raw.replace("\\", "/").rsplit("/", 1)[-1]
    name = _CONTROL_CHARS.sub("", name).strip()
    return name[:255] or "export.zip"


def find_active_duplicate(db: Session, checksum: str) -> Import | None:
    """Fast-path dedupe check; the partial unique index remains authoritative."""
    return db.scalars(
        select(Import).where(
            Import.checksum_sha256 == checksum,
            Import.status.not_in([ImportStatus.failed, ImportStatus.deleted]),
        )
    ).first()


def _too_large() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
        detail={"code": "too_large", "message": TOO_LARGE_MESSAGE},
    )


def _duplicate(existing_import_id: int | None) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "duplicate",
            "message": "this ZIP was already uploaded (matching checksum)",
            "existing_import_id": existing_import_id,
        },
    )


def _delete_quietly(storage: Storage, key: str) -> None:
    """Cleanup must never mask the primary error being raised."""
    with contextlib.suppress(Exception):
        storage.delete(key)


@router.post("/upload", response_model=UploadAccepted, status_code=status.HTTP_201_CREATED)
async def upload_import(
    request: Request,
    db: DbSession,
    redis: RedisDep,
    storage: StorageDep,
    policy: PolicyDep,
    filename: str | None = None,
) -> UploadAccepted:
    display_name = sanitize_filename(filename)

    content_length = request.headers.get("content-length")
    if (
        content_length is not None
        and content_length.isdigit()
        and int(content_length) > policy.max_upload_bytes
    ):
        raise _too_large()  # rejected before reading any of the body

    spool_path = storage.spool_dir() / f"upload-{uuid4().hex}.part"
    try:
        hasher = hashlib.sha256()
        received = 0
        with spool_path.open("wb") as spool:
            async for chunk in request.stream():
                received += len(chunk)
                if received > policy.max_upload_bytes:
                    raise _too_large()  # chunked/lying clients: abort mid-stream
                hasher.update(chunk)
                spool.write(chunk)
        checksum = hasher.hexdigest()

        existing = find_active_duplicate(db, checksum)
        if existing is not None:
            raise _duplicate(existing.id)

        try:
            report = validate_zip(spool_path, policy.zip_limits)
        except ZipRejectedError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": exc.code, "message": str(exc)},
            ) from exc

        kind = detect_export_format(report.entry_names)
        if kind is ExportKind.html:
            # Recorded (visible in the import list) but no file is retained.
            db.add(
                Import(
                    filename=display_name,
                    storage_key=None,
                    size_bytes=received,
                    checksum_sha256=checksum,
                    export_format=ExportFormat.html_detected,
                    status=ImportStatus.failed,
                    error=HTML_EXPORT_MESSAGE,
                )
            )
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "html_export", "message": HTML_EXPORT_MESSAGE},
            )
        if kind is ExportKind.unrecognized:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "unrecognized", "message": UNRECOGNIZED_MESSAGE},
            )

        storage_key = f"imports/{uuid4().hex}.zip"
        storage.save_file(storage_key, spool_path)

        try:
            import_row = Import(
                filename=display_name,
                storage_key=storage_key,
                size_bytes=received,
                checksum_sha256=checksum,
                export_format=ExportFormat.json,
                status=ImportStatus.uploaded,
            )
            db.add(import_row)
            db.flush()
            job = Job(
                kind=JobKind.import_scan,
                status=JobStatus.queued,
                total=1,
                payload={"import_id": import_row.id},
            )
            db.add(job)
            db.commit()
        except IntegrityError as exc:
            # Lost a concurrent-duplicate race: the partial unique index fired.
            db.rollback()
            _delete_quietly(storage, storage_key)
            racing = find_active_duplicate(db, checksum)
            raise _duplicate(racing.id if racing is not None else None) from exc
        except Exception as exc:
            db.rollback()
            _delete_quietly(storage, storage_key)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"code": "upload_failed", "message": "upload could not be recorded"},
            ) from exc

        try:
            rq_job = Queue(QUEUE_IMPORTS, connection=redis).enqueue(
                "app.workers.jobs.run_import_scan", job.id, import_row.id
            )
        except Exception as exc:
            # Rows go failed together; the stored ZIP is retained for recovery.
            job.status = JobStatus.failed
            job.error = type(exc).__name__
            import_row.status = ImportStatus.failed
            import_row.error = QUEUE_UNAVAILABLE_MESSAGE
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "queue_unavailable", "message": QUEUE_UNAVAILABLE_MESSAGE},
            ) from exc
        job.rq_job_id = rq_job.id
        db.commit()
        return UploadAccepted(import_id=import_row.id, job_id=job.id)
    finally:
        with contextlib.suppress(OSError):
            spool_path.unlink(missing_ok=True)


@router.get("", response_model=list[ImportRead])
def list_imports(db: DbSession) -> list[Import]:
    return list(db.scalars(select(Import).order_by(Import.id.desc())).all())


@router.get("/{import_id}", response_model=ImportDetail)
def get_import(import_id: int, db: DbSession) -> ImportDetail:
    import_row = db.get(Import, import_id)
    if import_row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="import not found")
    latest_job = db.scalars(
        select(Job)
        .where(
            Job.kind == JobKind.import_scan,
            Job.payload["import_id"].as_integer() == import_id,
        )
        .order_by(Job.id.desc())
    ).first()
    base = ImportRead.model_validate(import_row)
    return ImportDetail(
        **base.model_dump(),
        latest_job=JobRead.model_validate(latest_job) if latest_job is not None else None,
    )


@router.get("/{import_id}/verification", response_model=ImportVerificationReport)
def get_import_verification(import_id: int, db: DbSession) -> ImportVerificationReport:
    """Raw-vs-parsed counts, every scan-pass skip categorized, and a
    duplicate-reason summary (M10) — built from `Import.counts` plus a fresh
    duplicate-groups query; see docs/TESTING_STRATEGY.md's real-data
    workflow. Available (with zeros where not yet computed) as soon as the
    import row exists — no gating on status."""
    import_row = db.get(Import, import_id)
    if import_row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="import not found")
    return build_verification_report(db, import_row)


@router.post("/{import_id}/delete", response_model=ImportDeletionReport)
def delete_import(
    import_id: int, body: ImportDeletionRequest, db: DbSession, storage: StorageDep
) -> ImportDeletionReport:
    """Typed confirmation: `confirm_text` must exactly match the filename.
    `cascade=False` keeps derived items with source refs nulled;
    `cascade=True` deletes them too. Synchronous — bounded work."""
    import_row = db.get(Import, import_id)
    if import_row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="import not found")
    if body.confirm_text != import_row.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "confirmation_mismatch",
                "message": "confirmation text does not match the import's filename",
            },
        )
    report = delete_raw_import(db, storage, import_row, cascade=body.cascade)
    return ImportDeletionReport(
        conversations_deleted=report.conversations_deleted,
        messages_deleted=report.messages_deleted,
        items_deleted=report.items_deleted,
        items_kept=report.items_kept,
        file_deleted=report.file_deleted,
    )
