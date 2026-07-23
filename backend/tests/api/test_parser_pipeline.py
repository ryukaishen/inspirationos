"""Full parser pipeline against real Postgres + Redis:

upload-equivalent committed rows → scan → conversations API → selection →
extract (through the production enqueue path on a dedicated test queue) →
messages/items/duplicate groups.

Rows are really committed (the worker uses its own connection), so every
fixture tracks and purges what it created. A dedicated queue name keeps a
running dev compose worker from racing the test's SimpleWorker.
"""

from collections.abc import Callable, Generator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from fixture_builder import (
    EXPECTED_ADJACENT_REEL_A,
    FRIEND_NAME,
    OWNER_NAME,
    POST_B_CANONICAL,
    POST_B_SHORTCODE,
    REEL_A_CANONICAL,
    REEL_A_SHORTCODE,
    REEL_A_TRACKING_URL,
    REEL_URL,
    RICH_DUPLICATE_GROUP_SIZE,
    RICH_EXTERNAL_CANONICAL,
    RICH_EXTERNAL_NOTE,
    RICH_FRIEND_FIRST_MS,
    RICH_FRIEND_LAST_MS,
    RICH_FRIEND_LINK_COUNT,
    RICH_FRIEND_MESSAGE_COUNT,
    RICH_FRIEND_THREAD_PATH,
    RICH_FRIEND_TITLE,
    RICH_POST_NOTE,
    RICH_SELF_LINK_COUNT,
    RICH_SELF_MESSAGE_COUNT,
    RICH_SELF_THREAD_PATH,
    RICH_SHARE_TEXT,
    VERIFICATION_CONVERSATIONS,
    VERIFICATION_DUP_SHORTCODE,
    VERIFICATION_DUPLICATE_GROUP_SIZE,
    VERIFICATION_MESSAGE_FILES,
    VERIFICATION_MESSAGE_MISSING_FIELDS,
    VERIFICATION_MESSAGE_NOT_OBJECT,
    VERIFICATION_MESSAGES_PARSED,
    VERIFICATION_NON_DICT_PAGE_PAYLOAD,
    VERIFICATION_UNKNOWN_CATEGORY,
    VERIFICATION_UNRECOGNIZED_MESSAGE_PATH,
    build_rich_export_zip,
    build_verification_export_zip,
)
from redis import Redis
from rq import Queue, SimpleWorker
from sqlalchemy import Engine, delete, func, select, update
from sqlalchemy.orm import Session

from app.config import get_config
from app.db import get_db_session
from app.main import app
from app.models.conversation import Conversation
from app.models.import_ import ExportFormat, Import, ImportStatus
from app.models.item import DuplicateGroup, DuplicateReason, Item, ItemStatus, ItemType
from app.models.job import Job, JobKind, JobStatus
from app.models.message import Message
from app.models.user import User
from app.queues import QUEUE_IMPORTS
from app.redis_client import get_redis
from app.services.auth.passwords import hash_password
from app.services.storage.local import LocalStorage
from app.workers.jobs import run_import_extract, run_import_scan

pytestmark = pytest.mark.integration

# Dedicated queue: a running dev compose worker also consumes "imports" and
# must not race this test's SimpleWorker for enqueued extract jobs.
TEST_QUEUE = f"{QUEUE_IMPORTS}-test-extract"

CSRF_HEADERS = {"X-Requested-With": "XMLHttpRequest"}
_TEST_USER_EMAIL = "parser-pipeline@example.com"
_TEST_USER_PASSWORD = "correct-horse-battery-staple"

MakeImport = Callable[..., int]


def _ms_to_dt(timestamp_ms: int) -> datetime:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC)


def _purge_imports(engine: Engine, import_ids: list[int]) -> None:
    if not import_ids:
        return
    with Session(engine) as session:
        item_ids = select(Item.id).where(Item.import_id.in_(import_ids))
        session.execute(
            update(Item).where(Item.import_id.in_(import_ids)).values(duplicate_group_id=None)
        )
        session.execute(
            delete(DuplicateGroup).where(DuplicateGroup.canonical_item_id.in_(item_ids))
        )
        session.execute(delete(Item).where(Item.import_id.in_(import_ids)))
        conversation_ids = select(Conversation.id).where(Conversation.import_id.in_(import_ids))
        session.execute(delete(Message).where(Message.conversation_id.in_(conversation_ids)))
        session.execute(delete(Conversation).where(Conversation.import_id.in_(import_ids)))
        session.execute(delete(Job).where(Job.payload["import_id"].as_integer().in_(import_ids)))
        session.execute(delete(Import).where(Import.id.in_(import_ids)))
        session.commit()


@pytest.fixture
def parser_storage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[LocalStorage, None, None]:
    """Point the config-derived storage (used by the worker tasks) at a temp root."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    get_config.cache_clear()
    yield LocalStorage(get_config().data_dir)
    get_config.cache_clear()


@pytest.fixture
def make_import(
    pg_engine: Engine, parser_storage: LocalStorage
) -> Generator[MakeImport, None, None]:
    """Really-committed import + scan-job rows; optionally runs the scan."""
    created: list[int] = []

    def _make(zip_path: Path, scan: bool = True, storage_key: str | None = "auto") -> int:
        key: str | None = None
        if storage_key == "auto":
            key = f"imports/{uuid4().hex}.zip"
            parser_storage.save_file(key, zip_path)
        with Session(pg_engine, expire_on_commit=False) as session:
            import_row = Import(
                filename=zip_path.name,
                storage_key=key,
                size_bytes=1,
                checksum_sha256=uuid4().hex + uuid4().hex,
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
            created.append(import_row.id)
            job_id, import_id = job.id, import_row.id
        if scan:
            run_import_scan(job_id, import_id)
        return import_id

    yield _make
    _purge_imports(pg_engine, created)


@pytest.fixture
def client(pg_engine: Engine, redis_client: Redis) -> Generator[TestClient, None, None]:
    """TestClient over really-committed sessions, so worker tasks (own
    connection) see what the API wrote. Shadows conftest's savepoint client
    on purpose. Needs its own really-committed user (M9 gates every
    non-auth route) — created and purged here rather than reusing
    conftest's savepoint-scoped user, which this file's real commits
    wouldn't roll back."""

    def _session() -> Generator[Session, None, None]:
        with Session(pg_engine, expire_on_commit=False) as session:
            yield session

    app.dependency_overrides[get_db_session] = _session
    app.dependency_overrides[get_redis] = lambda: redis_client
    with Session(pg_engine, expire_on_commit=False) as setup_session:
        user = User(email=_TEST_USER_EMAIL, password_hash=hash_password(_TEST_USER_PASSWORD))
        setup_session.add(user)
        setup_session.commit()
        user_id = user.id
    try:
        with TestClient(app) as test_client:
            test_client.headers.update(CSRF_HEADERS)
            login_response = test_client.post(
                "/api/auth/login",
                json={"email": _TEST_USER_EMAIL, "password": _TEST_USER_PASSWORD},
            )
            assert login_response.status_code == 200, login_response.text
            yield test_client
    finally:
        app.dependency_overrides.clear()
        with Session(pg_engine, expire_on_commit=False) as cleanup_session:
            cleanup_session.execute(delete(User).where(User.id == user_id))
            cleanup_session.commit()


@pytest.fixture
def extract_queue(
    redis_client: Redis, monkeypatch: pytest.MonkeyPatch
) -> Generator[Queue, None, None]:
    monkeypatch.setattr("app.api.conversations.QUEUE_IMPORTS", TEST_QUEUE)
    queue = Queue(TEST_QUEUE, connection=redis_client)
    yield queue
    queue.empty()


def _conversations(client: TestClient, import_id: int) -> list[dict]:
    response = client.get(f"/api/imports/{import_id}/conversations")
    assert response.status_code == 200, response.text
    return response.json()


def _select_and_extract(
    client: TestClient,
    redis_client: Redis,
    extract_queue: Queue,
    import_id: int,
    conversation_ids: list[int],
) -> int:
    response = client.post(
        f"/api/imports/{import_id}/conversations/selection",
        json={"conversation_ids": conversation_ids},
    )
    assert response.status_code == 202, response.text
    SimpleWorker([extract_queue], connection=redis_client).work(burst=True)
    return int(response.json()["job_id"])


# --- scan pass ---------------------------------------------------------------


def test_scan_persists_summaries_and_no_message_bodies(
    make_import: MakeImport, client: TestClient, pg_engine: Engine, tmp_path: Path
) -> None:
    import_id = make_import(build_rich_export_zip(tmp_path / "rich_a.zip"))
    conversations = _conversations(client, import_id)
    assert len(conversations) == 2
    by_path = {c["thread_path"]: c for c in conversations}

    friend = by_path[RICH_FRIEND_THREAD_PATH]
    assert friend["title"] == RICH_FRIEND_TITLE  # mojibake round-trip via the DB
    assert friend["participant_names"] == [OWNER_NAME, FRIEND_NAME]
    assert friend["message_count"] == RICH_FRIEND_MESSAGE_COUNT
    assert friend["link_count"] == RICH_FRIEND_LINK_COUNT
    assert friend["is_self_dm_candidate"] is False
    assert friend["is_selected"] is False
    assert datetime.fromisoformat(friend["first_message_at"]) == _ms_to_dt(RICH_FRIEND_FIRST_MS)
    assert datetime.fromisoformat(friend["last_message_at"]) == _ms_to_dt(RICH_FRIEND_LAST_MS)

    self_dm = by_path[RICH_SELF_THREAD_PATH]
    assert self_dm["is_self_dm_candidate"] is True
    assert self_dm["message_count"] == RICH_SELF_MESSAGE_COUNT
    assert self_dm["link_count"] == RICH_SELF_LINK_COUNT

    with Session(pg_engine) as session:
        import_row = session.get(Import, import_id)
        assert import_row is not None
        assert import_row.status is ImportStatus.scanned
        assert import_row.counts == {
            "total_entries": 4,
            "message_files": 3,
            "conversations": 2,
            "messages": RICH_FRIEND_MESSAGE_COUNT + RICH_SELF_MESSAGE_COUNT,
            "links": RICH_FRIEND_LINK_COUNT + RICH_SELF_LINK_COUNT,
            "skipped": {
                "non_dict_page_payload": 0,
                "message_not_object": 0,
                "message_missing_sender_or_timestamp": 0,
                "unrecognized_message_path": 0,
                "unrecognized_message_path_categories": [],
            },
        }
        # privacy invariant: the scan pass persisted zero message bodies/items
        conversation_ids = [c["id"] for c in conversations]
        message_count = session.scalar(
            select(func.count())
            .select_from(Message)
            .where(Message.conversation_id.in_(conversation_ids))
        )
        assert message_count == 0
        item_count = session.scalar(
            select(func.count()).select_from(Item).where(Item.import_id == import_id)
        )
        assert item_count == 0


def test_no_self_dm_and_no_personal_info_yields_no_candidates(
    make_import: MakeImport, client: TestClient, tmp_path: Path
) -> None:
    path = build_rich_export_zip(
        tmp_path / "lonely.zip", include_self_dm=False, include_personal_info=False
    )
    import_id = make_import(path)
    conversations = _conversations(client, import_id)
    assert len(conversations) == 1
    assert conversations[0]["is_self_dm_candidate"] is False


# --- selection + extract pass ------------------------------------------------


def test_extract_persists_selected_conversations_only(
    make_import: MakeImport,
    client: TestClient,
    redis_client: Redis,
    extract_queue: Queue,
    pg_engine: Engine,
    tmp_path: Path,
) -> None:
    import_id = make_import(build_rich_export_zip(tmp_path / "rich_a.zip"))
    by_path = {c["thread_path"]: c for c in _conversations(client, import_id)}
    friend_id = by_path[RICH_FRIEND_THREAD_PATH]["id"]
    self_id = by_path[RICH_SELF_THREAD_PATH]["id"]

    job_id = _select_and_extract(client, redis_client, extract_queue, import_id, [friend_id])

    with Session(pg_engine) as session:
        job = session.get(Job, job_id)
        assert job is not None
        assert job.status is JobStatus.succeeded
        assert job.kind is JobKind.import_extract
        assert job.payload == {"import_id": import_id}  # IDs only — never content
        assert job.progress == job.total == 1

        import_row = session.get(Import, import_id)
        assert import_row is not None
        assert import_row.status is ImportStatus.extracted
        assert import_row.counts["extracted_messages"] == RICH_FRIEND_MESSAGE_COUNT
        assert import_row.counts["items"] == RICH_FRIEND_LINK_COUNT
        assert import_row.counts["duplicate_groups"] == 1

        # the invariant: messages/items exist ONLY for selected conversations
        for conversation_id, expected in ((friend_id, RICH_FRIEND_MESSAGE_COUNT), (self_id, 0)):
            count = session.scalar(
                select(func.count())
                .select_from(Message)
                .where(Message.conversation_id == conversation_id)
            )
            assert count == expected
        self_items = session.scalar(
            select(func.count()).select_from(Item).where(Item.conversation_id == self_id)
        )
        assert self_items == 0

        items = list(
            session.scalars(select(Item).where(Item.import_id == import_id).order_by(Item.id)).all()
        )
        assert len(items) == RICH_FRIEND_LINK_COUNT
        first_reel, post, tracking_reel, repeat_reel, external = items

        assert first_reel.url_raw == REEL_URL
        assert first_reel.url_canonical == REEL_A_CANONICAL
        assert first_reel.shortcode == REEL_A_SHORTCODE
        assert first_reel.item_type is ItemType.reel
        assert first_reel.share_text == RICH_SHARE_TEXT  # mojibake round-trip
        assert first_reel.adjacent_text == EXPECTED_ADJACENT_REEL_A
        assert first_reel.status is ItemStatus.new
        assert first_reel.message_id is not None

        assert post.url_canonical == POST_B_CANONICAL
        assert post.shortcode == POST_B_SHORTCODE
        assert post.item_type is ItemType.post
        assert post.share_text is None
        assert post.adjacent_text == RICH_POST_NOTE  # a link in a note is its own context

        assert tracking_reel.url_raw == REEL_A_TRACKING_URL
        assert tracking_reel.url_canonical == REEL_A_CANONICAL
        assert tracking_reel.adjacent_text is None  # no same-sender text in window

        assert repeat_reel.url_raw == REEL_URL
        assert repeat_reel.adjacent_text is None

        assert external.url_canonical == RICH_EXTERNAL_CANONICAL
        assert external.item_type is ItemType.external
        assert external.shortcode is None
        assert external.adjacent_text == RICH_EXTERNAL_NOTE

        # duplicate group: the three REEL_A shares, canonical = earliest
        groups = list(
            session.scalars(
                select(DuplicateGroup).where(
                    DuplicateGroup.canonical_item_id.in_(
                        select(Item.id).where(Item.import_id == import_id)
                    )
                )
            ).all()
        )
        assert len(groups) == 1
        group = groups[0]
        assert group.reason is DuplicateReason.same_shortcode
        assert group.canonical_item_id == first_reel.id
        members = [item for item in items if item.duplicate_group_id == group.id]
        assert len(members) == RICH_DUPLICATE_GROUP_SIZE
        assert {member.shortcode for member in members} == {REEL_A_SHORTCODE}
        assert post.duplicate_group_id is None
        assert external.duplicate_group_id is None


def test_variant_a_and_b_extract_to_identical_logical_results(
    make_import: MakeImport,
    client: TestClient,
    redis_client: Redis,
    extract_queue: Queue,
    pg_engine: Engine,
    tmp_path: Path,
) -> None:
    results = []
    for variant in ("a", "b"):
        path = build_rich_export_zip(tmp_path / f"rich_{variant}.zip", variant=variant)
        import_id = make_import(path)
        ids = [c["id"] for c in _conversations(client, import_id)]
        _select_and_extract(client, redis_client, extract_queue, import_id, ids)
        results.append(_logical_snapshot(pg_engine, import_id))
    assert results[0] == results[1]


def _logical_snapshot(engine: Engine, import_id: int) -> list[tuple]:
    """Everything extracted, minus database identifiers."""
    snapshot: list[tuple] = []
    with Session(engine) as session:
        conversations = session.scalars(
            select(Conversation)
            .where(Conversation.import_id == import_id)
            .order_by(Conversation.thread_path)
        ).all()
        for conversation in conversations:
            messages = session.scalars(
                select(Message)
                .where(Message.conversation_id == conversation.id)
                .order_by(Message.sent_at, Message.id)
            ).all()
            items = session.scalars(
                select(Item).where(Item.conversation_id == conversation.id).order_by(Item.id)
            ).all()
            snapshot.append(
                (
                    conversation.thread_path,
                    conversation.title,
                    tuple(conversation.participant_names),
                    conversation.message_count,
                    conversation.link_count,
                    conversation.is_self_dm_candidate,
                    conversation.first_message_at,
                    conversation.last_message_at,
                    tuple(
                        (m.sender_name, m.sent_at, m.text, m.share_link, m.share_text)
                        for m in messages
                    ),
                    tuple(
                        (
                            i.url_raw,
                            i.url_canonical,
                            i.shortcode,
                            i.item_type,
                            i.shared_at,
                            i.share_text,
                            i.adjacent_text,
                            i.duplicate_group_id is not None,
                        )
                        for i in items
                    ),
                )
            )
    return snapshot


def test_extract_rerun_is_idempotent_and_reselection_removes_rows(
    make_import: MakeImport,
    client: TestClient,
    redis_client: Redis,
    extract_queue: Queue,
    pg_engine: Engine,
    tmp_path: Path,
) -> None:
    import_id = make_import(build_rich_export_zip(tmp_path / "rich_a.zip"))
    by_path = {c["thread_path"]: c for c in _conversations(client, import_id)}
    friend_id = by_path[RICH_FRIEND_THREAD_PATH]["id"]
    self_id = by_path[RICH_SELF_THREAD_PATH]["id"]
    both = [friend_id, self_id]

    job_id = _select_and_extract(client, redis_client, extract_queue, import_id, both)
    first = _logical_snapshot(pg_engine, import_id)

    # re-running the finished job is a no-op
    run_import_extract(job_id, import_id)
    # a fresh extract over the same selection converges to the same rows
    _select_and_extract(client, redis_client, extract_queue, import_id, both)
    second = _logical_snapshot(pg_engine, import_id)
    assert second == first

    with Session(pg_engine) as session:
        total_messages = RICH_FRIEND_MESSAGE_COUNT + RICH_SELF_MESSAGE_COUNT
        total_items = RICH_FRIEND_LINK_COUNT + RICH_SELF_LINK_COUNT
        import_row = session.get(Import, import_id)
        assert import_row is not None
        assert import_row.counts["extracted_messages"] == total_messages
        assert import_row.counts["items"] == total_items
        item_count = session.scalar(
            select(func.count()).select_from(Item).where(Item.import_id == import_id)
        )
        assert item_count == total_items  # no duplicates from the re-run

    # deselecting the friend conversation removes its rows
    _select_and_extract(client, redis_client, extract_queue, import_id, [self_id])
    with Session(pg_engine) as session:
        friend_messages = session.scalar(
            select(func.count()).select_from(Message).where(Message.conversation_id == friend_id)
        )
        assert friend_messages == 0
        self_messages = session.scalar(
            select(func.count()).select_from(Message).where(Message.conversation_id == self_id)
        )
        assert self_messages == RICH_SELF_MESSAGE_COUNT
        remaining_items = list(
            session.scalars(select(Item).where(Item.import_id == import_id)).all()
        )
        assert len(remaining_items) == RICH_SELF_LINK_COUNT
        assert all(item.conversation_id == self_id for item in remaining_items)


# --- selection endpoint validation -------------------------------------------


def test_selection_validation_errors(
    make_import: MakeImport, client: TestClient, extract_queue: Queue, tmp_path: Path
) -> None:
    assert (
        client.post(
            "/api/imports/999999999/conversations/selection",
            json={"conversation_ids": [1]},
        ).status_code
        == 404
    )

    unscanned_id = make_import(build_rich_export_zip(tmp_path / "u.zip"), scan=False)
    response = client.post(
        f"/api/imports/{unscanned_id}/conversations/selection", json={"conversation_ids": [1]}
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "not_ready"

    no_file_id = make_import(tmp_path / "u.zip", scan=False, storage_key=None)
    response = client.post(
        f"/api/imports/{no_file_id}/conversations/selection", json={"conversation_ids": [1]}
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "no_stored_file"

    scanned_id = make_import(build_rich_export_zip(tmp_path / "s.zip"))
    response = client.post(
        f"/api/imports/{scanned_id}/conversations/selection",
        json={"conversation_ids": [999999999]},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "unknown_conversations"

    response = client.post(
        f"/api/imports/{scanned_id}/conversations/selection", json={"conversation_ids": []}
    )
    assert response.status_code == 422  # empty selection rejected by the schema


def test_selection_queue_failure_marks_job_failed(
    make_import: MakeImport,
    client: TestClient,
    pg_engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ExplodingQueue:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def enqueue(self, *args: object, **kwargs: object) -> None:
            raise ConnectionError("injected queue failure")

    monkeypatch.setattr("app.api.conversations.Queue", ExplodingQueue)
    import_id = make_import(build_rich_export_zip(tmp_path / "q.zip"))
    conversation_ids = [c["id"] for c in _conversations(client, import_id)]

    response = client.post(
        f"/api/imports/{import_id}/conversations/selection",
        json={"conversation_ids": conversation_ids},
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "queue_unavailable"

    with Session(pg_engine) as session:
        job = session.scalars(
            select(Job)
            .where(
                Job.kind == JobKind.import_extract,
                Job.payload["import_id"].as_integer() == import_id,
            )
            .order_by(Job.id.desc())
        ).first()
        assert job is not None
        assert job.status is JobStatus.failed
        assert job.error == "ConnectionError"  # class name only


# --- verification report (M10) ------------------------------------------------


def test_verification_report_before_scan_is_zeroed(
    make_import: MakeImport, client: TestClient, tmp_path: Path
) -> None:
    """The endpoint never errors before a scan has run — it just reports
    zeros/empties, since `Import.counts` starts empty."""
    import_id = make_import(build_rich_export_zip(tmp_path / "unscanned.zip"), scan=False)
    response = client.get(f"/api/imports/{import_id}/verification")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["conversations_found"] == 0
    assert body["messages_parsed"] == 0
    assert body["extracted_messages"] is None
    assert body["items_extracted"] is None
    assert body["duplicate_summary"] == []


def test_verification_report_unknown_import_404s(client: TestClient) -> None:
    assert client.get("/api/imports/999999999/verification").status_code == 404


def test_verification_report_after_scan_categorizes_every_skip(
    make_import: MakeImport, client: TestClient, tmp_path: Path
) -> None:
    """M10 acceptance: raw-vs-parsed counts and every skip category are
    visible through the API — nothing silent."""
    import_id = make_import(build_verification_export_zip(tmp_path / "verification.zip"))

    response = client.get(f"/api/imports/{import_id}/verification")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["matched_message_json_entries"] == VERIFICATION_MESSAGE_FILES
    assert body["raw_message_json_entries"] == (
        VERIFICATION_MESSAGE_FILES + VERIFICATION_UNRECOGNIZED_MESSAGE_PATH
    )
    assert body["conversations_found"] == VERIFICATION_CONVERSATIONS
    assert body["messages_parsed"] == VERIFICATION_MESSAGES_PARSED
    assert body["messages_skipped"] == (
        VERIFICATION_MESSAGE_NOT_OBJECT + VERIFICATION_MESSAGE_MISSING_FIELDS
    )
    assert body["extracted_messages"] is None  # not extracted yet
    assert body["items_extracted"] is None

    skip_by_category = {row["category"]: row["count"] for row in body["skip_breakdown"]}
    assert skip_by_category["non_dict_page_payload"] == VERIFICATION_NON_DICT_PAGE_PAYLOAD
    assert skip_by_category["message_not_object"] == VERIFICATION_MESSAGE_NOT_OBJECT
    assert (
        skip_by_category["message_missing_sender_or_timestamp"]
        == VERIFICATION_MESSAGE_MISSING_FIELDS
    )
    assert skip_by_category["unrecognized_message_path"] == VERIFICATION_UNRECOGNIZED_MESSAGE_PATH
    unrecognized_row = next(
        row
        for row in body["skip_breakdown"]
        if row["category"] == "unrecognized_message_path_categories_seen"
    )
    assert VERIFICATION_UNKNOWN_CATEGORY in unrecognized_row["description"]

    # no message content anywhere in the response
    assert "share_text" not in response.text
    assert "adjacent_text" not in response.text


def test_verification_report_after_extract_includes_duplicate_summary(
    make_import: MakeImport,
    client: TestClient,
    redis_client: Redis,
    extract_queue: Queue,
    tmp_path: Path,
) -> None:
    import_id = make_import(build_verification_export_zip(tmp_path / "verification.zip"))
    conversation_ids = [c["id"] for c in _conversations(client, import_id)]
    _select_and_extract(client, redis_client, extract_queue, import_id, conversation_ids)

    response = client.get(f"/api/imports/{import_id}/verification")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["extracted_messages"] == VERIFICATION_MESSAGES_PARSED
    assert body["duplicate_summary"] == [
        {
            "reason": "same_shortcode",
            "group_count": 1,
            "item_count": VERIFICATION_DUPLICATE_GROUP_SIZE,
        }
    ]
    # the duplicate summary is counts-by-reason only — no canonical URL or
    # shortcode is ever surfaced by this endpoint
    assert VERIFICATION_DUP_SHORTCODE not in response.text
