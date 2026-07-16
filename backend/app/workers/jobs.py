"""RQ tasks. Convention for every task in this app:

- receives IDs (and scalar knobs) only — never message content;
- owns the `jobs` row lifecycle: running → succeeded/failed, with progress;
- is safe to re-run: a finished job is a no-op;
- records only the exception class name in `jobs.error` (redaction rule).
"""

import time
import zipfile
from datetime import UTC, datetime

from app.config import get_config
from app.db import get_sessionmaker
from app.models.import_ import Import, ImportStatus
from app.models.job import Job, JobStatus
from app.services.ingest.format_detection import count_message_json_files
from app.services.storage.local import LocalStorage


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


def run_import_scan(job_id: int, import_id: int) -> None:
    """M2 scan stub: prove the upload→job pipeline with central-directory counts.

    Reads entry **names** only — no message bodies are opened or persisted
    (real conversation scanning arrives in M3). Idempotent: a finished job or
    an already-scanned import is a no-op.
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
        job.total = 1
        session.commit()
        try:
            import_row = session.get(Import, import_id)
            if import_row is None:
                raise ValueError(f"imports row {import_id} does not exist")
            if import_row.storage_key is None:
                raise ValueError(f"imports row {import_id} has no stored file")
            import_row.status = ImportStatus.scanning
            session.commit()

            storage = LocalStorage(get_config().data_dir)
            with storage.open(import_row.storage_key) as fh, zipfile.ZipFile(fh) as archive:
                entry_names = archive.namelist()

            import_row.counts = {
                "total_entries": len(entry_names),
                "message_files": count_message_json_files(entry_names),
            }
            import_row.status = ImportStatus.scanned
            job.progress = 1
            job.status = JobStatus.succeeded
            job.finished_at = _utcnow()
            session.commit()
        except Exception as exc:
            session.rollback()
            job.status = JobStatus.failed
            job.error = type(exc).__name__  # class name only — never message text
            job.finished_at = _utcnow()
            failed_import = session.get(Import, import_id)
            if failed_import is not None:
                failed_import.status = ImportStatus.failed
                failed_import.error = type(exc).__name__
            session.commit()
            raise
