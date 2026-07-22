"""Three deletion scopes (M9, see PRIVACY_SECURITY.md):

1. Raw import — `delete_raw_import`: the ZIP, conversations, and messages
   always go; the caller chooses whether derived items are kept (source
   refs nulled) or cascade-deleted with them.
2. Project — `delete_project`: existing cascades (milestones/artifacts/
   exports) do almost all of the work; this just removes the row.
3. Complete wipe — `wipe_everything`: every table except `users`, run by the
   `delete_data` worker job (see workers/jobs.py::run_delete_data).

None of these touch `enrichment_attempts`/`duplicate_groups` cascades for
free — those two tables have no `ON DELETE CASCADE` on their item FKs (see
DATA_MODEL.md), so every scope that deletes items clears them explicitly
first to avoid FK violations.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.models.ai_request import AiRequest
from app.models.analysis import Cluster, ClusterRun, ItemCluster, ItemTopic, Topic
from app.models.app_settings import AppSettings
from app.models.artifact import Artifact
from app.models.career_profile import CareerProfile
from app.models.conversation import Conversation
from app.models.enrichment_attempt import EnrichmentAttempt
from app.models.export import Export
from app.models.import_ import Import, ImportStatus
from app.models.item import DuplicateGroup, Item
from app.models.job import Job
from app.models.message import Message
from app.models.project import Project, ProjectMilestone
from app.services.storage.base import Storage

SINGLETON_ID = 1


@dataclass(frozen=True)
class ImportDeletionReport:
    conversations_deleted: int
    messages_deleted: int
    items_deleted: int
    items_kept: int
    file_deleted: bool


def _clear_duplicate_groups_touching(session: Session, item_ids: list[int]) -> None:
    """Ungroups and deletes every duplicate_groups row touched by `item_ids`
    (even members outside `item_ids`) — safe because groups are rebuilt from
    scratch by the next extract/cluster run regardless."""
    if not item_ids:
        return
    group_ids = set(
        session.scalars(
            select(Item.duplicate_group_id).where(
                Item.id.in_(item_ids), Item.duplicate_group_id.is_not(None)
            )
        )
    )
    if not group_ids:
        return
    session.execute(
        update(Item)
        .where(Item.duplicate_group_id.in_(group_ids))
        .values(duplicate_group_id=None)
        .execution_options(synchronize_session=False)
    )
    session.execute(delete(DuplicateGroup).where(DuplicateGroup.id.in_(group_ids)))


def delete_raw_import(
    session: Session, storage: Storage, import_row: Import, *, cascade: bool
) -> ImportDeletionReport:
    item_ids = list(session.scalars(select(Item.id).where(Item.import_id == import_row.id)))
    conversation_ids = list(
        session.scalars(select(Conversation.id).where(Conversation.import_id == import_row.id))
    )

    items_deleted = 0
    items_kept = 0
    if cascade:
        session.execute(delete(EnrichmentAttempt).where(EnrichmentAttempt.item_id.in_(item_ids)))
        _clear_duplicate_groups_touching(session, item_ids)
        # item_topics/item_clusters cascade automatically on item deletion.
        if item_ids:
            session.execute(delete(Item).where(Item.id.in_(item_ids)))
            items_deleted = len(item_ids)
    elif item_ids:
        session.execute(
            update(Item)
            .where(Item.id.in_(item_ids))
            .values(import_id=None, conversation_id=None, message_id=None)
        )
        items_kept = len(item_ids)

    messages_deleted = 0
    if conversation_ids:
        messages_deleted = int(
            session.scalar(
                select(func.count())
                .select_from(Message)
                .where(Message.conversation_id.in_(conversation_ids))
            )
            or 0
        )
        session.execute(delete(Message).where(Message.conversation_id.in_(conversation_ids)))
        session.execute(delete(Conversation).where(Conversation.id.in_(conversation_ids)))

    file_deleted = False
    if import_row.storage_key is not None:
        storage.delete(import_row.storage_key)
        file_deleted = True

    import_row.status = ImportStatus.deleted
    import_row.storage_key = None
    session.commit()

    return ImportDeletionReport(
        conversations_deleted=len(conversation_ids),
        messages_deleted=messages_deleted,
        items_deleted=items_deleted,
        items_kept=items_kept,
        file_deleted=file_deleted,
    )


def delete_project(session: Session, project: Project) -> None:
    """Milestones/artifacts/exports cascade off the FK; the underlying
    export files are deliberately left for the wipe's filesystem sweep
    (see PRIVACY_SECURITY.md)."""
    session.delete(project)
    session.commit()


# (report key, model) — order is FK-safe: children before the parents they
# reference, so no `ON DELETE CASCADE` is relied on except where noted above.
_WIPE_TABLES: tuple[tuple[str, type], ...] = (
    ("item_topics", ItemTopic),
    ("item_clusters", ItemCluster),
    ("enrichment_attempts", EnrichmentAttempt),
    ("items", Item),
    ("messages", Message),
    ("conversations", Conversation),
    ("imports", Import),
    ("artifacts", Artifact),
    ("project_milestones", ProjectMilestone),
    ("exports", Export),
    ("projects", Project),
    ("topics", Topic),
    ("clusters", Cluster),
    ("cluster_runs", ClusterRun),
    ("ai_requests", AiRequest),
)


def _count(session: Session, model: type) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


def wipe_everything(
    session: Session, storage: Storage, *, keep_job_id: int | None = None
) -> dict[str, object]:
    """Truncates every table except `users` (FK-safe order), clears every
    stored file, reseeds the `settings`/`career_profile` singletons so the
    app stays usable, and returns a verification report. `keep_job_id` is
    the currently-running wipe job's own row (it cannot delete itself
    mid-execution) — `None` when called from the `wipe-data` CLI, which has
    no job row at all."""
    before = {name: _count(session, model) for name, model in _WIPE_TABLES}
    before["jobs"] = _count(session, Job)
    before["settings"] = _count(session, AppSettings)
    before["career_profile"] = _count(session, CareerProfile)

    # duplicate_groups' canonical_item_id FK (use_alter) must be cleared
    # before items are deleted.
    session.execute(update(Item).values(duplicate_group_id=None))
    session.execute(delete(DuplicateGroup))
    for _name, model in _WIPE_TABLES:
        session.execute(delete(model))
    jobs_stmt = delete(Job) if keep_job_id is None else delete(Job).where(Job.id != keep_job_id)
    session.execute(jobs_stmt)
    session.execute(delete(AppSettings))
    session.execute(delete(CareerProfile))
    session.add(AppSettings(id=SINGLETON_ID))
    session.add(CareerProfile(id=SINGLETON_ID))
    session.commit()

    # The still-running wipe job's own row isn't counted as "remaining".
    kept_jobs = 1 if keep_job_id is not None else 0
    after = {name: _count(session, model) for name, model in _WIPE_TABLES}
    after["jobs"] = _count(session, Job) - kept_jobs
    after["settings"] = _count(session, AppSettings)
    after["career_profile"] = _count(session, CareerProfile)

    files_removed = storage.clear()
    files_remaining = storage.count_files()

    return {
        "tables": {name: {"before": before[name], "after": after[name]} for name in before},
        "files_removed": files_removed,
        "files_remaining": files_remaining,
    }
