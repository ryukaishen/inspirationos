"""Full-pipeline log capture (M9): scan + extract over the rich synthetic
export must never log any real fixture text. `app.main` (imported by every
test via conftest) already installs the redaction filter on the root logger
at import time — this test doesn't re-install it, so it's exercising the
actual wiring, not a hand-built filter instance.

Workers use their own session (`get_sessionmaker()`), so this follows
test_parser_pipeline.py's real-commit-and-purge pattern rather than the
savepoint-scoped `db_session`.
"""

import logging
from pathlib import Path
from uuid import uuid4

import pytest
from fixture_builder import (
    EXPECTED_ADJACENT_REEL_A,
    FRIEND_NAME,
    OWNER_NAME,
    RICH_ADJACENT_AFTER,
    RICH_EXTERNAL_NOTE,
    RICH_FRIEND_THREAD_PATH,
    RICH_LATE_NOTE,
    RICH_MOJIBAKE_NOTE,
    RICH_POST_NOTE,
    RICH_SELF_NOTE,
    RICH_SELF_SHARE_TEXT,
    RICH_SELF_THREAD_PATH,
    RICH_SHARE_TEXT,
    build_rich_export_zip,
)
from sqlalchemy import Engine, delete, select, update
from sqlalchemy.orm import Session

from app.config import get_config
from app.models.conversation import Conversation
from app.models.import_ import ExportFormat, Import, ImportStatus
from app.models.item import DuplicateGroup, Item
from app.models.job import Job, JobKind, JobStatus
from app.models.message import Message
from app.services.storage.local import LocalStorage
from app.workers.jobs import run_import_extract, run_import_scan

pytestmark = pytest.mark.integration

# The private-content strings a leak would reveal — not paths, counts, or
# canonical URLs, which aren't message content.
SENSITIVE_STRINGS = (
    RICH_SHARE_TEXT,
    RICH_MOJIBAKE_NOTE,
    RICH_ADJACENT_AFTER,
    RICH_LATE_NOTE,
    RICH_POST_NOTE,
    RICH_EXTERNAL_NOTE,
    RICH_SELF_SHARE_TEXT,
    RICH_SELF_NOTE,
    EXPECTED_ADJACENT_REEL_A,
    FRIEND_NAME,
    OWNER_NAME,
)


def _purge(pg_engine: Engine, import_id: int) -> None:
    with Session(pg_engine) as session:
        item_ids = select(Item.id).where(Item.import_id == import_id)
        session.execute(delete(Job).where(Job.payload["import_id"].as_integer() == import_id))
        # The rich export deliberately shares one reel three times, forming a
        # duplicate group — null the circular FK before deleting items/groups.
        session.execute(
            update(Item).where(Item.import_id == import_id).values(duplicate_group_id=None)
        )
        session.execute(
            delete(DuplicateGroup).where(DuplicateGroup.canonical_item_id.in_(item_ids))
        )
        session.execute(delete(Item).where(Item.id.in_(item_ids)))
        conversation_ids = select(Conversation.id).where(Conversation.import_id == import_id)
        session.execute(delete(Message).where(Message.conversation_id.in_(conversation_ids)))
        session.execute(delete(Conversation).where(Conversation.import_id == import_id))
        session.execute(delete(Import).where(Import.id == import_id))
        session.commit()


def test_scan_and_extract_never_log_fixture_message_strings(
    pg_engine: Engine,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The worker tasks build their own LocalStorage from get_config().data_dir
    # rather than taking it as a parameter, so point config at a temp root.
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    get_config.cache_clear()
    storage = LocalStorage(get_config().data_dir)
    zip_path = build_rich_export_zip(tmp_path / "rich_a.zip")
    storage_key = f"imports/{uuid4().hex}.zip"
    storage.save_file(storage_key, zip_path)

    with Session(pg_engine, expire_on_commit=False) as session:
        import_row = Import(
            filename="rich_a.zip",
            storage_key=storage_key,
            size_bytes=1,
            checksum_sha256=uuid4().hex + uuid4().hex,
            export_format=ExportFormat.json,
            status=ImportStatus.uploaded,
        )
        session.add(import_row)
        session.flush()
        scan_job = Job(kind=JobKind.import_scan, status=JobStatus.queued, total=1)
        session.add(scan_job)
        session.commit()
        import_id, scan_job_id = import_row.id, scan_job.id

    try:
        with caplog.at_level(logging.DEBUG):
            run_import_scan(scan_job_id, import_id)

            with Session(pg_engine, expire_on_commit=False) as session:
                friend = session.scalar(
                    select(Conversation).where(
                        Conversation.import_id == import_id,
                        Conversation.thread_path == RICH_FRIEND_THREAD_PATH,
                    )
                )
                self_dm = session.scalar(
                    select(Conversation).where(
                        Conversation.import_id == import_id,
                        Conversation.thread_path == RICH_SELF_THREAD_PATH,
                    )
                )
                assert friend is not None
                assert self_dm is not None
                friend.is_selected = True
                self_dm.is_selected = True
                extract_job = Job(kind=JobKind.import_extract, status=JobStatus.queued, total=1)
                session.add(extract_job)
                session.commit()
                extract_job_id = extract_job.id

            run_import_extract(extract_job_id, import_id)

        log_text = caplog.text
        for sensitive in SENSITIVE_STRINGS:
            assert sensitive not in log_text, f"leaked into logs: {sensitive!r}"
    finally:
        _purge(pg_engine, import_id)
        get_config.cache_clear()
