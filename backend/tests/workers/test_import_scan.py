"""Import-scan stub job against real Postgres + Redis.

The happy path runs through the production enqueue path (dotted string) and an
RQ SimpleWorker; failure and idempotency paths call the task directly.
"""

from collections.abc import Callable, Generator
from pathlib import Path

import pytest
from fixture_builder import build_variant_a_zip
from redis import Redis
from rq import Queue, SimpleWorker
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.config import get_config
from app.models.import_ import ExportFormat, Import, ImportStatus
from app.models.job import Job, JobKind, JobStatus
from app.queues import QUEUE_IMPORTS
from app.services.storage.local import LocalStorage
from app.workers.jobs import run_import_scan

pytestmark = pytest.mark.integration

MakeImport = Callable[[str | None], tuple[int, int]]


@pytest.fixture
def scan_storage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[LocalStorage, None, None]:
    """Point the worker's config-derived storage at a temp root."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_config.cache_clear()
    yield LocalStorage(tmp_path)
    get_config.cache_clear()


@pytest.fixture
def make_import(pg_engine: Engine) -> Generator[MakeImport, None, None]:
    """Creates really-committed imports+jobs rows (the worker uses its own
    connection), deleting them afterwards."""
    created_imports: list[int] = []
    created_jobs: list[int] = []

    def _make(storage_key: str | None) -> tuple[int, int]:
        with Session(pg_engine, expire_on_commit=False) as session:
            import_row = Import(
                filename="synthetic.zip",
                storage_key=storage_key,
                size_bytes=123,
                checksum_sha256="0" * 64,
                export_format=ExportFormat.json,
                status=ImportStatus.uploaded,
            )
            session.add(import_row)
            session.flush()
            job = Job(
                kind=JobKind.import_scan,
                status=JobStatus.queued,
                total=1,
                payload={"import_id": import_row.id},
            )
            session.add(job)
            session.commit()
            created_imports.append(import_row.id)
            created_jobs.append(job.id)
            return job.id, import_row.id

    yield _make
    with Session(pg_engine) as session:
        for job_id in created_jobs:
            row = session.get(Job, job_id)
            if row is not None:
                session.delete(row)
        for import_id in created_imports:
            row = session.get(Import, import_id)
            if row is not None:
                session.delete(row)
        session.commit()


# Dedicated queue name: a running dev compose worker also consumes "imports"
# and must not race this test's SimpleWorker for the enqueued job.
TEST_QUEUE = f"{QUEUE_IMPORTS}-test-scan"


@pytest.fixture
def imports_queue(redis_client: Redis) -> Generator[Queue, None, None]:
    queue = Queue(TEST_QUEUE, connection=redis_client)
    yield queue
    queue.empty()


def _reload(pg_engine: Engine, job_id: int, import_id: int) -> tuple[Job, Import]:
    with Session(pg_engine) as session:
        job = session.get(Job, job_id)
        import_row = session.get(Import, import_id)
        assert job is not None
        assert import_row is not None
        return job, import_row


def test_scan_reaches_scanned_with_stub_counts(
    make_import: MakeImport,
    scan_storage: LocalStorage,
    imports_queue: Queue,
    redis_client: Redis,
    pg_engine: Engine,
    tmp_path: Path,
) -> None:
    archive = build_variant_a_zip(tmp_path / "a.zip")
    scan_storage.save_file("imports/test-scan.zip", archive)
    job_id, import_id = make_import("imports/test-scan.zip")

    imports_queue.enqueue("app.workers.jobs.run_import_scan", job_id, import_id)
    SimpleWorker([imports_queue], connection=redis_client).work(burst=True)

    job, import_row = _reload(pg_engine, job_id, import_id)
    assert job.status is JobStatus.succeeded
    assert job.progress == job.total == 1
    assert job.error is None
    assert import_row.status is ImportStatus.scanned
    # variant A: message_1.json + personal_information.json
    assert import_row.counts == {"total_entries": 2, "message_files": 1}


def test_scan_failure_records_redacted_error_on_both_rows(
    make_import: MakeImport, scan_storage: LocalStorage, pg_engine: Engine
) -> None:
    job_id, import_id = make_import("imports/does-not-exist.zip")

    with pytest.raises(FileNotFoundError):
        run_import_scan(job_id, import_id)

    job, import_row = _reload(pg_engine, job_id, import_id)
    assert job.status is JobStatus.failed
    assert job.error == "FileNotFoundError"  # class name only — never message text
    assert job.finished_at is not None
    assert import_row.status is ImportStatus.failed
    assert import_row.error == "FileNotFoundError"


def test_scan_missing_import_row_fails_cleanly(
    make_import: MakeImport, scan_storage: LocalStorage, pg_engine: Engine
) -> None:
    job_id, _ = make_import(None)

    with pytest.raises(ValueError):
        run_import_scan(job_id, 999_999_999)

    with Session(pg_engine) as session:
        job = session.get(Job, job_id)
        assert job is not None
        assert job.status is JobStatus.failed
        assert job.error == "ValueError"


def test_scan_rerun_of_finished_job_is_noop(
    make_import: MakeImport, scan_storage: LocalStorage, pg_engine: Engine, tmp_path: Path
) -> None:
    archive = build_variant_a_zip(tmp_path / "a.zip")
    scan_storage.save_file("imports/rerun.zip", archive)
    job_id, import_id = make_import("imports/rerun.zip")

    run_import_scan(job_id, import_id)
    first_job, first_import = _reload(pg_engine, job_id, import_id)

    run_import_scan(job_id, import_id)
    second_job, second_import = _reload(pg_engine, job_id, import_id)

    assert second_job.status is JobStatus.succeeded
    assert second_job.finished_at == first_job.finished_at
    assert second_import.counts == first_import.counts
