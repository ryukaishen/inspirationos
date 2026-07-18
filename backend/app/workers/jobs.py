"""RQ tasks. Convention for every task in this app:

- receives IDs (and scalar knobs) only — never message content;
- owns the `jobs` row lifecycle: running → succeeded/failed, with progress;
- is safe to re-run: a finished job is a no-op;
- records only the exception class name in `jobs.error` (redaction rule).
"""

import time
import zipfile
from datetime import UTC, datetime

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.config import get_config
from app.db import get_sessionmaker
from app.models.app_settings import AppSettings
from app.models.conversation import Conversation
from app.models.enrichment_attempt import EnrichmentAttempt, EnrichmentSource, EnrichmentStatus
from app.models.import_ import Import, ImportStatus
from app.models.item import DuplicateGroup, DuplicateReason, Item
from app.models.job import Job, JobStatus
from app.models.message import Message
from app.services.enrichment import policy as enrichment_policy
from app.services.enrichment.fetcher import EnrichmentFetcher, HttpEnrichmentFetcher
from app.services.ingest.format_detection import count_message_json_files
from app.services.ingest.instagram.export_reader import (
    iter_threads,
    read_owner_name,
    thread_entries,
)
from app.services.ingest.instagram.parser import (
    ConversationSummary,
    build_item_drafts,
    group_exact_duplicates,
    summarize_thread,
    to_datetime,
)
from app.services.ingest.instagram.selfdm import detect_owner, is_self_dm_candidate
from app.services.storage.local import LocalStorage


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _fail_job_and_import(session: Session, job: Job, import_id: int, exc: Exception) -> None:
    """Shared failure path: both rows failed, class name only — never message text."""
    session.rollback()
    job.status = JobStatus.failed
    job.error = type(exc).__name__
    job.finished_at = _utcnow()
    import_row = session.get(Import, import_id)
    if import_row is not None:
        import_row.status = ImportStatus.failed
        import_row.error = type(exc).__name__
    session.commit()


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
    """Scan pass: persist per-thread conversation summaries — no message bodies.

    Message contents are read in memory only to count links; the only rows
    written are `conversations` summaries, upserted by (import_id, thread_path)
    so a crashed-and-retried scan never duplicates and re-scanning preserves
    `is_selected`. Idempotent: a finished job is a no-op.
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
            summaries: list[ConversationSummary] = []
            with storage.open(import_row.storage_key) as fh, zipfile.ZipFile(fh) as archive:
                entry_names = archive.namelist()
                personal_name = read_owner_name(archive)
                job.total = len(thread_entries(archive))
                session.commit()
                # One thread's messages in memory at a time; only summaries kept.
                for thread in iter_threads(archive):
                    summaries.append(summarize_thread(thread))
                    job.progress += 1
                    session.commit()

            owner = detect_owner(personal_name, [s.participant_names for s in summaries])
            existing = {
                conversation.thread_path: conversation
                for conversation in session.scalars(
                    select(Conversation).where(Conversation.import_id == import_id)
                )
            }
            for summary in summaries:
                conversation = existing.get(summary.thread_path)
                if conversation is None:
                    conversation = Conversation(
                        import_id=import_id, thread_path=summary.thread_path
                    )
                    session.add(conversation)
                conversation.title = summary.title
                conversation.participant_names = list(summary.participant_names)
                conversation.message_count = summary.message_count
                conversation.link_count = summary.link_count
                conversation.is_self_dm_candidate = is_self_dm_candidate(
                    summary.title, summary.participant_names, owner
                )
                conversation.first_message_at = summary.first_message_at
                conversation.last_message_at = summary.last_message_at

            import_row.counts = {
                # total_entries/message_files kept for the M2 frontend/e2e contract
                "total_entries": len(entry_names),
                "message_files": count_message_json_files(entry_names),
                "conversations": len(summaries),
                "messages": sum(s.message_count for s in summaries),
                "links": sum(s.link_count for s in summaries),
            }
            import_row.status = ImportStatus.scanned
            job.status = JobStatus.succeeded
            job.finished_at = _utcnow()
            session.commit()
        except Exception as exc:
            _fail_job_and_import(session, job, import_id, exc)
            raise


def run_import_extract(job_id: int, import_id: int) -> None:
    """Extract pass: persist messages + items for **selected** conversations only.

    Delete-and-reinsert per conversation inside chunked transactions makes a
    crashed-and-retried run converge to the same rows (no duplicate items),
    and deselected conversations lose their rows — messages exist in the DB
    only for currently selected conversations. Exact duplicate groups are
    rebuilt from scratch across the whole import at the end.
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
        session.commit()
        try:
            import_row = session.get(Import, import_id)
            if import_row is None:
                raise ValueError(f"imports row {import_id} does not exist")
            if import_row.storage_key is None:
                raise ValueError(f"imports row {import_id} has no stored file")
            import_row.status = ImportStatus.extracting
            session.commit()

            conversations = list(
                session.scalars(select(Conversation).where(Conversation.import_id == import_id))
            )
            selected = {c.thread_path: c for c in conversations if c.is_selected}
            deselected_ids = [c.id for c in conversations if not c.is_selected]
            job.total = len(selected)
            session.commit()

            # Duplicate groups are rebuilt below; deselected conversations lose
            # their rows so the "messages only for selected" invariant holds.
            import_item_ids = select(Item.id).where(Item.import_id == import_id)
            session.execute(
                update(Item).where(Item.import_id == import_id).values(duplicate_group_id=None)
            )
            session.execute(
                delete(DuplicateGroup).where(DuplicateGroup.canonical_item_id.in_(import_item_ids))
            )
            if deselected_ids:
                session.execute(delete(Item).where(Item.conversation_id.in_(deselected_ids)))
                session.execute(delete(Message).where(Message.conversation_id.in_(deselected_ids)))
            session.commit()

            window = get_config().adjacent_text_window_seconds
            storage = LocalStorage(get_config().data_dir)
            extracted_messages = 0
            extracted_items = 0
            with storage.open(import_row.storage_key) as fh, zipfile.ZipFile(fh) as archive:
                for thread in iter_threads(archive):
                    conversation = selected.get(thread.thread_path)
                    if conversation is None:
                        continue
                    session.execute(delete(Item).where(Item.conversation_id == conversation.id))
                    session.execute(
                        delete(Message).where(Message.conversation_id == conversation.id)
                    )
                    message_rows = [
                        Message(
                            conversation_id=conversation.id,
                            sender_name=message.sender_name,
                            sent_at=to_datetime(message.timestamp_ms),
                            text=message.content,
                            share_link=message.share_link,
                            share_text=message.share_text,
                        )
                        for message in thread.messages
                    ]
                    session.add_all(message_rows)
                    session.flush()
                    drafts = build_item_drafts(thread, window)
                    session.add_all(
                        Item(
                            import_id=import_id,
                            conversation_id=conversation.id,
                            message_id=message_rows[draft.message_index].id,
                            url_raw=draft.url_raw,
                            url_canonical=draft.url_canonical,
                            shortcode=draft.shortcode,
                            item_type=draft.item_type,
                            shared_at=draft.shared_at,
                            share_text=draft.share_text,
                            adjacent_text=draft.adjacent_text,
                            status=draft.status,
                        )
                        for draft in drafts
                    )
                    extracted_messages += len(message_rows)
                    extracted_items += len(drafts)
                    job.progress += 1
                    session.commit()

            items = list(
                session.scalars(select(Item).where(Item.import_id == import_id).order_by(Item.id))
            )
            group_count = 0
            for reason, members in group_exact_duplicates(items):
                canonical = min(members, key=lambda i: (i.shared_at or _utcnow(), i.id))
                group = DuplicateGroup(
                    canonical_item_id=canonical.id, reason=DuplicateReason(reason)
                )
                session.add(group)
                session.flush()
                for member in members:
                    member.duplicate_group_id = group.id
                group_count += 1

            import_row.counts = {
                **import_row.counts,
                "extracted_messages": extracted_messages,
                "items": extracted_items,
                "duplicate_groups": group_count,
            }
            import_row.status = ImportStatus.extracted
            job.status = JobStatus.succeeded
            job.finished_at = _utcnow()
            session.commit()
        except Exception as exc:
            _fail_job_and_import(session, job, import_id, exc)
            raise


def _cached_attempt_exists(session: Session, item_id: int, source: EnrichmentSource) -> bool:
    """True if (item, source) already has a `success`/`not_found` attempt —
    permanent outcomes are never re-fetched."""
    return (
        session.scalar(
            select(EnrichmentAttempt.id)
            .where(
                EnrichmentAttempt.item_id == item_id,
                EnrichmentAttempt.source == source,
                EnrichmentAttempt.status.in_(
                    (EnrichmentStatus.success, EnrichmentStatus.not_found)
                ),
            )
            .limit(1)
        )
        is not None
    )


def _enrich_one_item(
    session: Session,
    item: Item,
    fetcher: EnrichmentFetcher,
    bucket: enrichment_policy.TokenBucket,
    breaker: enrichment_policy.CircuitBreaker,
) -> None:
    """oEmbed, then OpenGraph fallback; stops at the first success.

    Every attempted (non-cached) source is audited. Once the breaker is
    open, remaining sources are recorded `disabled` with zero HTTP calls. An
    item that already succeeded via an earlier source on a prior run is
    skipped entirely — per-source caching alone wouldn't catch this, since a
    source after the one that already succeeded was never attempted (and so
    never cached) in that prior run.
    """
    if item.enriched_source is not None:
        return
    for source, fetch in (
        (EnrichmentSource.oembed, fetcher.fetch_oembed),
        (EnrichmentSource.og, fetcher.fetch_og),
    ):
        if _cached_attempt_exists(session, item.id, source):
            continue
        if breaker.is_open:
            session.add(
                EnrichmentAttempt(item_id=item.id, source=source, status=EnrichmentStatus.disabled)
            )
            continue
        bucket.acquire()
        result = fetch(item.url_raw)
        outcome = enrichment_policy.classify_response(result.http_status, result.exc)
        breaker.record(outcome)
        session.add(
            EnrichmentAttempt(
                item_id=item.id,
                source=source,
                status=outcome,
                http_status=result.http_status,
                fetched_title=result.title,
                fetched_caption=result.caption,
                fetched_author=result.author,
                error=type(result.exc).__name__ if result.exc is not None else None,
            )
        )
        if outcome is EnrichmentStatus.success:
            if result.title:
                item.enriched_title = result.title
            if result.caption:
                item.enriched_caption = result.caption
            if result.author:
                item.enriched_author = result.author
            item.enriched_source = source
            return


def run_enrich_batch(job_id: int, item_ids: list[int]) -> None:
    """Consent-gated metadata enrichment: oEmbed -> OpenGraph fallback per item.

    Every attempted source is recorded in `enrichment_attempts` (full audit
    trail); a cached success/not_found for (item, source) is never
    re-fetched. A token bucket rate-limits requests and a circuit breaker
    (consecutive `blocked` classifications) stops making requests for the
    rest of this batch once tripped. Consent is re-checked here even though
    the API layer is the primary gate — if it's not given, this function
    makes zero outbound requests.
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
        job.total = len(item_ids)
        session.commit()
        try:
            settings = session.get(AppSettings, 1)
            if settings is None or not enrichment_policy.consent_given(settings):
                raise PermissionError("enrichment is disabled or not consented to")

            config = get_config()
            fetcher = HttpEnrichmentFetcher(
                timeout_seconds=config.enrichment_timeout_seconds,
                user_agent=config.enrichment_user_agent,
            )
            bucket = enrichment_policy.TokenBucket(config.enrichment_requests_per_minute)
            breaker = enrichment_policy.CircuitBreaker(config.enrichment_circuit_breaker_threshold)

            for item_id in item_ids:
                item = session.get(Item, item_id)
                if item is not None:
                    _enrich_one_item(session, item, fetcher, bucket, breaker)
                job.progress += 1
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
