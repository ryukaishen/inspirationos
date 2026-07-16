"""Upload endpoint matrix against real Postgres + Redis.

Covers every rejection branch, the transaction-safety failure injections, and
the "zero files left on disk" acceptance criterion (asserted by listing the
per-test storage root).
"""

from collections.abc import Generator, Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from fixture_builder import (
    build_empty_zip,
    build_entry_count_bomb_zip,
    build_html_export_zip,
    build_not_a_zip,
    build_ratio_bomb_zip,
    build_unrecognized_zip,
    build_variant_a_zip,
    build_variant_b_zip,
    build_zip_slip_zip,
)
from redis import Redis
from rq import Queue
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.imports import (
    HTML_EXPORT_MESSAGE,
    UploadPolicy,
    get_storage,
    get_upload_policy,
)
from app.main import app
from app.models.import_ import ExportFormat, Import, ImportStatus
from app.models.job import Job, JobKind, JobStatus
from app.queues import QUEUE_IMPORTS
from app.services.ingest.zip_safety import ZipLimits
from app.services.storage.local import LocalStorage

pytestmark = pytest.mark.integration

TEST_POLICY = UploadPolicy(
    max_upload_bytes=8 * 1024 * 1024,
    zip_limits=ZipLimits(
        max_entries=100,
        max_total_uncompressed_bytes=32 * 1024 * 1024,
        max_compression_ratio=100,
    ),
)


@pytest.fixture(autouse=True)
def clean_queue(redis_client: Redis) -> Generator[None, None, None]:
    yield
    Queue(QUEUE_IMPORTS, connection=redis_client).empty()


@pytest.fixture(autouse=True)
def isolate_imports_table(db_session: Session) -> None:
    """E2E runs against the same dev DB leave committed imports/jobs rows.

    Clear them *inside* this test's outer transaction (rolled back afterwards,
    so dev data survives) so count-based assertions see only this test's rows.
    """
    db_session.execute(delete(Job).where(Job.kind == JobKind.import_scan))
    db_session.execute(delete(Import))
    db_session.commit()


@pytest.fixture
def storage_root(tmp_path: Path) -> Path:
    return tmp_path / "storage"


@pytest.fixture
def storage(storage_root: Path) -> LocalStorage:
    return LocalStorage(storage_root)


@pytest.fixture
def upload_client(client: TestClient, storage: LocalStorage) -> TestClient:
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_upload_policy] = lambda: TEST_POLICY
    return client  # conftest's client fixture clears all overrides afterwards


def files_under(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return [p for p in root.rglob("*") if p.is_file()]


def upload(client: TestClient, path: Path, filename: str | None = None) -> httpx.Response:
    return client.post(
        "/api/imports/upload",
        params={"filename": filename or path.name},
        content=path.read_bytes(),
        headers={"content-type": "application/zip"},
    )


def count_rows(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(Import)) or 0


# --- happy path -------------------------------------------------------------


def test_valid_upload_creates_row_file_and_job(
    upload_client: TestClient, db_session: Session, storage_root: Path, tmp_path: Path
) -> None:
    archive = build_variant_a_zip(tmp_path / "a.zip")
    response = upload(upload_client, archive, filename="my export.zip")
    assert response.status_code == 201
    body = response.json()

    import_row = db_session.get(Import, body["import_id"])
    assert import_row is not None
    assert import_row.status is ImportStatus.uploaded
    assert import_row.export_format is ExportFormat.json
    assert import_row.filename == "my export.zip"
    assert import_row.size_bytes == archive.stat().st_size
    assert len(import_row.checksum_sha256) == 64
    assert import_row.storage_key is not None
    assert (storage_root / import_row.storage_key).is_file()

    job = db_session.get(Job, body["job_id"])
    assert job is not None
    assert job.kind is JobKind.import_scan
    assert job.status is JobStatus.queued
    assert job.payload == {"import_id": import_row.id}
    assert job.rq_job_id

    # exactly one scan job exists for this import
    jobs = db_session.scalars(
        select(Job).where(Job.payload["import_id"].as_integer() == import_row.id)
    ).all()
    assert len(jobs) == 1

    # no spool residue: the only file on disk is the stored ZIP
    assert files_under(storage_root) == [storage_root / import_row.storage_key]


def test_distinct_zips_both_accepted(
    upload_client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    first = upload(upload_client, build_variant_a_zip(tmp_path / "a.zip", unique="one"))
    second = upload(upload_client, build_variant_b_zip(tmp_path / "b.zip", unique="two"))
    assert first.status_code == 201
    assert second.status_code == 201
    assert count_rows(db_session) == 2


# --- size cap ---------------------------------------------------------------


def test_oversized_content_length_rejected_before_read(
    upload_client: TestClient, db_session: Session, storage_root: Path
) -> None:
    body = b"\0" * (TEST_POLICY.max_upload_bytes + 1)
    response = upload_client.post(
        "/api/imports/upload",
        params={"filename": "big.zip"},
        content=body,
        headers={"content-type": "application/zip"},
    )
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "too_large"
    assert files_under(storage_root) == []
    assert count_rows(db_session) == 0


def test_oversized_chunked_body_aborted_mid_stream(
    upload_client: TestClient, db_session: Session, storage_root: Path
) -> None:
    def chunks() -> Iterator[bytes]:
        for _ in range(9):  # 9 MB total, no Content-Length header
            yield b"\0" * (1024 * 1024)

    # iterator body → httpx sends chunked transfer encoding, no Content-Length
    response = upload_client.post(
        "/api/imports/upload",
        params={"filename": "chunked.zip"},
        content=chunks(),
        headers={"content-type": "application/zip"},
    )
    assert response.status_code == 413
    assert files_under(storage_root) == []
    assert count_rows(db_session) == 0


# --- malicious / invalid archives: zero trace -------------------------------


@pytest.mark.parametrize(
    ("builder", "expected_code"),
    [
        (build_zip_slip_zip, "zip_slip"),
        (lambda p: build_zip_slip_zip(p, entry_name="..\\..\\evil.txt"), "zip_slip"),
        (build_ratio_bomb_zip, "zip_bomb"),
        (lambda p: build_entry_count_bomb_zip(p, entries=200), "zip_bomb"),
        (build_not_a_zip, "not_a_zip"),
        (build_empty_zip, "unrecognized"),
        (build_unrecognized_zip, "unrecognized"),
    ],
    ids=[
        "zip-slip",
        "zip-slip-backslash",
        "zip-bomb-ratio",
        "zip-bomb-entries",
        "not-a-zip",
        "empty-zip",
        "unrecognized",
    ],
)
def test_rejected_archives_leave_no_trace(
    upload_client: TestClient,
    db_session: Session,
    storage_root: Path,
    tmp_path: Path,
    builder,
    expected_code: str,
) -> None:
    archive = builder(tmp_path / "payload.zip")
    response = upload(upload_client, archive)
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["code"] == expected_code
    assert detail["message"]  # clean, static error message
    assert files_under(storage_root) == []  # zero files left on disk
    assert count_rows(db_session) == 0  # and zero rows


# --- HTML export: actionable message, recorded row, no file ------------------


def test_html_export_rejected_with_actionable_message(
    upload_client: TestClient, db_session: Session, storage_root: Path, tmp_path: Path
) -> None:
    archive = build_html_export_zip(tmp_path / "html.zip")
    response = upload(upload_client, archive)
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["code"] == "html_export"
    assert detail["message"] == HTML_EXPORT_MESSAGE
    assert "JSON" in detail["message"]

    rows = db_session.scalars(select(Import)).all()
    assert len(rows) == 1
    assert rows[0].status is ImportStatus.failed
    assert rows[0].export_format is ExportFormat.html_detected
    assert rows[0].storage_key is None
    assert rows[0].error == HTML_EXPORT_MESSAGE
    assert files_under(storage_root) == []


def test_html_rejection_does_not_block_reupload(
    upload_client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    archive = build_html_export_zip(tmp_path / "html.zip")
    assert upload(upload_client, archive).status_code == 400
    # failed rows are excluded from dedupe — the same bytes get the HTML
    # message again instead of a misleading "duplicate"
    second = upload(upload_client, archive)
    assert second.status_code == 400
    assert second.json()["detail"]["code"] == "html_export"


# --- checksum dedupe ---------------------------------------------------------


def test_duplicate_upload_detected_by_checksum(
    upload_client: TestClient, db_session: Session, storage_root: Path, tmp_path: Path
) -> None:
    archive = build_variant_a_zip(tmp_path / "a.zip")
    first = upload(upload_client, archive)
    assert first.status_code == 201

    second = upload(upload_client, archive)
    assert second.status_code == 409
    detail = second.json()["detail"]
    assert detail["code"] == "duplicate"
    assert detail["existing_import_id"] == first.json()["import_id"]

    assert count_rows(db_session) == 1
    assert len(files_under(storage_root)) == 1


def test_concurrent_duplicate_caught_by_db_constraint(
    upload_client: TestClient,
    db_session: Session,
    storage_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Simulates the race: with the fast-path pre-check blinded, the partial
    unique index must still reject the duplicate and clean up its file."""
    monkeypatch.setattr("app.api.imports.find_active_duplicate", lambda db, checksum: None)
    archive = build_variant_a_zip(tmp_path / "a.zip")
    first = upload(upload_client, archive)
    assert first.status_code == 201

    second = upload(upload_client, archive)
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "duplicate"

    assert count_rows(db_session) == 1
    assert len(files_under(storage_root)) == 1  # the loser's promoted file was removed


# --- injected failures ------------------------------------------------------


def test_db_failure_after_promotion_removes_stored_file(
    upload_client: TestClient,
    db_session: Session,
    storage_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_flush = db_session.flush

    def exploding_flush() -> None:
        # Fire only on the post-promotion insert transaction, not on the
        # autoflush triggered by the earlier dedupe pre-check SELECT.
        if db_session.new:
            raise RuntimeError("injected DB failure")
        original_flush()

    monkeypatch.setattr(db_session, "flush", exploding_flush)
    archive = build_variant_a_zip(tmp_path / "a.zip")
    response = upload(upload_client, archive)
    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "upload_failed"
    assert files_under(storage_root) == []  # promoted file cleaned up


def test_storage_delete_failure_does_not_mask_primary_error(
    client: TestClient,
    db_session: Session,
    storage_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingDeleteStorage(LocalStorage):
        def delete(self, key: str) -> None:
            raise RuntimeError("injected storage failure")

    app.dependency_overrides[get_storage] = lambda: FailingDeleteStorage(storage_root)
    app.dependency_overrides[get_upload_policy] = lambda: TEST_POLICY
    monkeypatch.setattr("app.api.imports.find_active_duplicate", lambda db, checksum: None)

    archive = build_variant_a_zip(tmp_path / "a.zip")
    assert upload(client, archive).status_code == 201
    # duplicate insert loses to the constraint; cleanup delete raises but the
    # client still receives the 409, not a 500
    second = upload(client, archive)
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "duplicate"


def test_queue_failure_marks_rows_failed_and_keeps_zip(
    upload_client: TestClient,
    db_session: Session,
    storage_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ExplodingQueue:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def enqueue(self, *args: object, **kwargs: object) -> None:
            raise ConnectionError("injected queue failure")

    monkeypatch.setattr("app.api.imports.Queue", ExplodingQueue)
    archive = build_variant_a_zip(tmp_path / "a.zip")
    response = upload(upload_client, archive)
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "queue_unavailable"

    import_row = db_session.scalars(select(Import)).one()
    assert import_row.status is ImportStatus.failed
    assert import_row.error == "job queue unavailable"
    assert import_row.storage_key is not None
    assert (storage_root / import_row.storage_key).is_file()  # ZIP retained

    job = db_session.scalars(select(Job).where(Job.kind == JobKind.import_scan)).one()
    assert job.status is JobStatus.failed
    assert job.error == "ConnectionError"  # class name only


# --- list & detail ----------------------------------------------------------


def test_list_returns_imports_newest_first(
    upload_client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    first = upload(upload_client, build_variant_a_zip(tmp_path / "a.zip", unique="1"))
    second = upload(upload_client, build_variant_a_zip(tmp_path / "b.zip", unique="2"))

    response = upload_client.get("/api/imports")
    assert response.status_code == 200
    body = response.json()
    assert [row["id"] for row in body] == [second.json()["import_id"], first.json()["import_id"]]
    assert body[0]["status"] == "uploaded"


def test_detail_embeds_latest_scan_job(
    upload_client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    uploaded = upload(upload_client, build_variant_a_zip(tmp_path / "a.zip")).json()
    response = upload_client.get(f"/api/imports/{uploaded['import_id']}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == uploaded["import_id"]
    assert body["latest_job"]["id"] == uploaded["job_id"]
    assert body["latest_job"]["kind"] == "import_scan"


def test_detail_missing_returns_404(upload_client: TestClient) -> None:
    assert upload_client.get("/api/imports/999999999").status_code == 404
