"""Deletion scopes (M9): raw import (keep vs. cascade), project, and the
complete wipe's core logic.

The wipe test calls `wipe_everything` directly against the ordinary
savepoint-scoped `db_session` (never the real-commit `pg_engine` pattern
other worker tests use) **on purpose** — it deletes every row in every
table, and this backend's Postgres is the same long-lived instance backing
the running dev compose stack. Running it for real would destroy whatever
real/manual data is sitting there. `db_session`'s commits are savepoints
inside one outer transaction that's always rolled back at teardown, so the
delete statements execute (and are correctly asserted against) without ever
reaching the real database — see conftest.py's `db_session` docstring.
"""

import tempfile
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.imports import get_storage
from app.main import app
from app.models.ai_request import AiRequest, AiRequestStatus
from app.models.analysis import Cluster, ClusterRun, ItemCluster, ItemTopic, Topic
from app.models.app_settings import AppSettings
from app.models.artifact import Artifact, ArtifactKind
from app.models.career_profile import CareerProfile
from app.models.conversation import Conversation
from app.models.enrichment_attempt import EnrichmentAttempt, EnrichmentSource, EnrichmentStatus
from app.models.export import Export, ExportBundleFormat
from app.models.import_ import ExportFormat, Import, ImportStatus
from app.models.item import DuplicateGroup, DuplicateReason, Item, ItemType
from app.models.job import Job, JobKind
from app.models.message import Message
from app.models.project import Project, ProjectMilestone
from app.models.user import User
from app.services.privacy.deletion import wipe_everything
from app.services.storage.local import LocalStorage

pytestmark = pytest.mark.integration


def _write_temp_file() -> Path:
    with tempfile.NamedTemporaryFile(delete=False) as handle:
        handle.write(b"synthetic test content")
    return Path(handle.name)


@pytest.fixture
def storage_override(tmp_path: Path) -> Generator[LocalStorage, None, None]:
    storage = LocalStorage(tmp_path / "storage")
    app.dependency_overrides[get_storage] = lambda: storage
    try:
        yield storage
    finally:
        app.dependency_overrides.pop(get_storage, None)


def _make_import_with_items(
    db_session: Session,
) -> tuple[Import, Conversation, Message, list[Item]]:
    import_row = Import(
        filename="export.zip",
        storage_key=f"imports/{uuid4().hex}.zip",
        size_bytes=10,
        checksum_sha256=uuid4().hex + uuid4().hex,
        export_format=ExportFormat.json,
        status=ImportStatus.extracted,
    )
    db_session.add(import_row)
    db_session.flush()
    conversation = Conversation(import_id=import_row.id, thread_path="inbox/friend")
    db_session.add(conversation)
    db_session.flush()
    message = Message(
        conversation_id=conversation.id,
        sender_name="friend",
        sent_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    db_session.add(message)
    db_session.flush()
    items = [
        Item(
            import_id=import_row.id,
            conversation_id=conversation.id,
            message_id=message.id,
            url_raw="https://instagram.com/reel/abc/",
            url_canonical="https://instagram.com/reel/abc/",
            item_type=ItemType.reel,
        ),
        Item(
            import_id=import_row.id,
            conversation_id=conversation.id,
            message_id=message.id,
            url_raw="https://instagram.com/reel/def/",
            url_canonical="https://instagram.com/reel/def/",
            item_type=ItemType.reel,
        ),
    ]
    db_session.add_all(items)
    db_session.flush()
    group = DuplicateGroup(canonical_item_id=items[0].id, reason=DuplicateReason.same_shortcode)
    db_session.add(group)
    db_session.flush()
    items[0].duplicate_group_id = group.id
    items[1].duplicate_group_id = group.id
    db_session.add(
        EnrichmentAttempt(
            item_id=items[0].id, source=EnrichmentSource.oembed, status=EnrichmentStatus.not_found
        )
    )
    db_session.commit()
    return import_row, conversation, message, items


# --- raw import deletion -----------------------------------------------------


def test_delete_import_requires_matching_confirmation_text(
    client: TestClient, db_session: Session
) -> None:
    import_row, _conversation, _message, _items = _make_import_with_items(db_session)
    response = client.post(
        f"/api/imports/{import_row.id}/delete", json={"confirm_text": "wrong-name.zip"}
    )
    assert response.status_code == 400
    assert db_session.get(Import, import_row.id) is not None


def test_delete_import_keep_mode_nulls_source_refs(
    client: TestClient, db_session: Session, storage_override: LocalStorage
) -> None:
    import_row, conversation, message, items = _make_import_with_items(db_session)
    assert import_row.storage_key is not None
    storage_override.save_file(import_row.storage_key, _write_temp_file())

    response = client.post(
        f"/api/imports/{import_row.id}/delete",
        json={"confirm_text": import_row.filename, "cascade": False},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["items_kept"] == 2
    assert body["items_deleted"] == 0
    assert body["file_deleted"] is True

    for item in items:
        db_session.refresh(item)
        assert item.import_id is None
        assert item.conversation_id is None
        assert item.message_id is None
    assert db_session.get(Conversation, conversation.id) is None
    assert db_session.get(Message, message.id) is None
    refreshed_import = db_session.get(Import, import_row.id)
    assert refreshed_import is not None
    assert refreshed_import.status is ImportStatus.deleted
    assert refreshed_import.storage_key is None
    assert storage_override.count_files() == 0


def test_delete_import_cascade_removes_items_and_dependents(
    client: TestClient, db_session: Session
) -> None:
    import_row, _conversation, _message, items = _make_import_with_items(db_session)
    group_id = items[0].duplicate_group_id
    assert group_id is not None

    response = client.post(
        f"/api/imports/{import_row.id}/delete",
        json={"confirm_text": import_row.filename, "cascade": True},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["items_deleted"] == 2
    assert body["items_kept"] == 0

    assert db_session.get(Item, items[0].id) is None
    assert db_session.get(Item, items[1].id) is None
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(EnrichmentAttempt)
            .where(EnrichmentAttempt.item_id.in_([i.id for i in items]))
        )
        == 0
    )
    assert db_session.get(DuplicateGroup, group_id) is None


def test_delete_import_404_for_unknown_id(client: TestClient) -> None:
    response = client.post("/api/imports/999999999/delete", json={"confirm_text": "x"})
    assert response.status_code == 404


# --- project deletion --------------------------------------------------------


def test_delete_project_requires_matching_title(client: TestClient, db_session: Session) -> None:
    project = Project(title="My Project", one_liner="...", summary_md="...")
    db_session.add(project)
    db_session.commit()

    response = client.request(
        "DELETE", f"/api/projects/{project.id}", json={"confirm_text": "Wrong Title"}
    )
    assert response.status_code == 400
    assert db_session.get(Project, project.id) is not None


def test_delete_project_cascades_milestones_and_artifacts(
    client: TestClient, db_session: Session
) -> None:
    project = Project(title="My Project", one_liner="...", summary_md="...")
    db_session.add(project)
    db_session.flush()
    milestone = ProjectMilestone(project_id=project.id, title="Step 1")
    artifact = Artifact(
        project_id=project.id,
        kind=ArtifactKind.readme,
        content_md="# hi",
        provider="mock",
        model="mock",
        prompt_version="v1",
    )
    db_session.add_all([milestone, artifact])
    db_session.commit()
    project_id = project.id

    response = client.request(
        "DELETE", f"/api/projects/{project_id}", json={"confirm_text": "My Project"}
    )
    assert response.status_code == 204
    assert db_session.get(Project, project_id) is None
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(ProjectMilestone)
            .where(ProjectMilestone.project_id == project_id)
        )
        == 0
    )
    assert (
        db_session.scalar(
            select(func.count()).select_from(Artifact).where(Artifact.project_id == project_id)
        )
        == 0
    )


# --- complete wipe (core logic only — see module docstring) ------------------


def test_privacy_wipe_endpoint_validates_confirmation(client: TestClient, test_user: User) -> None:
    mismatch = client.post("/api/privacy/wipe", json={"confirm_email": "wrong@example.com"})
    assert mismatch.status_code == 400

    accepted = client.post("/api/privacy/wipe", json={"confirm_email": test_user.email.upper()})
    assert accepted.status_code == 202
    assert accepted.json()["job_id"]


def test_wipe_everything_clears_every_table_and_reseeds_singletons(
    db_session: Session, tmp_path: Path, test_user: User
) -> None:
    storage = LocalStorage(tmp_path / "wipe-storage")
    storage.save_file("imports/keep.zip", _write_temp_file())
    storage.save_file("exports/keep.md", _write_temp_file())
    assert storage.count_files() == 2

    _import_row, _conversation, _message, items = _make_import_with_items(db_session)
    project = Project(title="P", one_liner="...", summary_md="...")
    db_session.add(project)
    db_session.flush()
    db_session.add(ProjectMilestone(project_id=project.id, title="Step"))
    db_session.add(
        Artifact(
            project_id=project.id,
            kind=ArtifactKind.readme,
            content_md="# hi",
            provider="mock",
            model="mock",
            prompt_version="v1",
        )
    )
    db_session.add(Export(project_id=project.id, format=ExportBundleFormat.markdown))
    topic = Topic(name="Cooking", slug=f"cooking-{uuid4().hex[:6]}")
    db_session.add(topic)
    db_session.flush()
    db_session.add(ItemTopic(item_id=items[0].id, topic_id=topic.id, confidence=0.9))
    cluster_run = ClusterRun(method="agglomerative", embedding_model="mock")
    db_session.add(cluster_run)
    db_session.flush()
    cluster = Cluster(run_id=cluster_run.id, size=1)
    db_session.add(cluster)
    db_session.flush()
    db_session.add(ItemCluster(item_id=items[0].id, cluster_id=cluster.id))
    db_session.add(
        AiRequest(provider="mock", model="mock", task="topics", status=AiRequestStatus.success)
    )
    db_session.add(Job(kind=JobKind.demo))
    db_session.commit()

    report = wipe_everything(db_session, storage, keep_job_id=None)

    wiped_models: list[type] = [
        Import,
        Conversation,
        Message,
        Item,
        DuplicateGroup,
        EnrichmentAttempt,
        Project,
        ProjectMilestone,
        Artifact,
        Export,
        Topic,
        ItemTopic,
        ClusterRun,
        Cluster,
        ItemCluster,
        AiRequest,
        Job,
    ]
    for model in wiped_models:
        count = db_session.scalar(select(func.count()).select_from(model))
        assert count == 0, f"{model.__tablename__} still has {count} row(s) after wipe"

    settings_rows = list(db_session.scalars(select(AppSettings)))
    assert len(settings_rows) == 1
    assert settings_rows[0].id == 1

    career_rows = list(db_session.scalars(select(CareerProfile)))
    assert len(career_rows) == 1
    assert career_rows[0].id == 1

    # The acting user is never touched by a wipe.
    assert db_session.get(User, test_user.id) is not None

    assert storage.count_files() == 0
    assert report["files_removed"] == 2
    assert report["files_remaining"] == 0
    assert report["tables"]["items"]["before"] >= 2
    assert report["tables"]["items"]["after"] == 0
    assert report["tables"]["jobs"]["after"] == 0
