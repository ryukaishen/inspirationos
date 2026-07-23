"""RQ tasks. Convention for every task in this app:

- receives IDs (and scalar knobs) only — never message content;
- owns the `jobs` row lifecycle: running → succeeded/failed, with progress;
- is safe to re-run: a finished job is a no-op;
- records only the exception class name in `jobs.error` (redaction rule).
"""

import time
import zipfile
from datetime import UTC, datetime
from uuid import uuid4

import numpy as np
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.config import get_config
from app.db import get_sessionmaker
from app.models.analysis import Cluster, ClusterRun, ClusterRunStatus, ItemCluster, ItemTopic
from app.models.app_settings import AppSettings
from app.models.artifact import Artifact, ArtifactKind
from app.models.conversation import Conversation
from app.models.enrichment_attempt import EnrichmentAttempt, EnrichmentSource, EnrichmentStatus
from app.models.export import Export, ExportBundleFormat
from app.models.import_ import Import, ImportStatus
from app.models.item import DuplicateGroup, DuplicateReason, Item
from app.models.job import Job, JobStatus
from app.models.message import Message
from app.models.project import Project
from app.services.ai.budget import JobTokenTracker
from app.services.ai.factory import get_llm_provider
from app.services.ai.provider import ModelTier
from app.services.ai.schemas import (
    TASK_ADVISOR_REVIEW,
    TASK_CLUSTER_LABEL,
    TASK_COMBINE_PROJECTS,
    TASK_GENERATE_PROJECTS,
    TASK_TOPIC_EXTRACTION,
    AdvisorReview,
    ClusterLabel,
    CombinedProject,
    ProjectIdeas,
    TopicExtraction,
)
from app.services.ai.structured import PROMPT_VERSION, generate_validated
from app.services.analysis.clustering import (
    CLUSTER_METHOD,
    LINKAGE,
    MIN_CLUSTER_SIZE,
    cluster_embeddings,
)
from app.services.analysis.dedupe import near_duplicate_components
from app.services.analysis.embeddings import embedding_text_for, get_embedding_provider
from app.services.analysis.topics import (
    build_llm_context_items,
    get_or_create_topic,
    verify_echoed_item_ids,
)
from app.services.enrichment import policy as enrichment_policy
from app.services.enrichment.fetcher import EnrichmentFetcher, HttpEnrichmentFetcher
from app.services.generation.advisor import (
    build_advisor_context,
    next_artifact_version,
    render_advisor_markdown,
)
from app.services.generation.career_outputs import (
    CAREER_ARTIFACT_SPECS,
    build_career_artifact_context,
)
from app.services.generation.claims_guard import find_claims
from app.services.generation.combine import build_combine_context, combined_source_ids
from app.services.generation.export import (
    build_library_export,
    build_project_export,
    render_library_markdown,
    render_project_markdown,
)
from app.services.generation.projects import (
    apply_generated_fields,
    build_generation_context,
    generation_source,
    load_career_profile_context,
    verify_idea_grounding,
)
from app.services.ingest.format_detection import count_message_json_files
from app.services.ingest.instagram.export_reader import (
    ScanIssues,
    iter_threads,
    read_owner_name,
    scan_unrecognized_message_paths,
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
from app.services.privacy.deletion import wipe_everything
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
            issues = ScanIssues()
            with storage.open(import_row.storage_key) as fh, zipfile.ZipFile(fh) as archive:
                entry_names = archive.namelist()
                personal_name = read_owner_name(archive)
                job.total = len(thread_entries(archive))
                session.commit()
                scan_unrecognized_message_paths(entry_names, issues)
                # One thread's messages in memory at a time; only summaries kept.
                for thread in iter_threads(archive, issues):
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
                # M10: every scan-pass skip, categorized — see verification.py
                "skipped": issues.as_dict(),
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


EMBED_CHUNK_SIZE = 64


def run_embed_batch(job_id: int, item_ids: list[int] | None = None, force: bool = False) -> None:
    """Embed item texts into pgvector via the configured EmbeddingProvider.

    Default scope is every item missing an embedding for the active model
    (idempotent — re-running skips already-embedded items); `force` re-embeds,
    e.g. after context notes changed. Items with no real text at all are never
    embedded, so they can never enter semantic analysis.
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
            provider = get_embedding_provider(get_config())
            stmt = select(Item).order_by(Item.id)
            if item_ids:
                stmt = stmt.where(Item.id.in_(item_ids))
            candidates: list[tuple[Item, str]] = []
            for item in session.scalars(stmt):
                text = embedding_text_for(item)
                if text is None:
                    continue
                if not force and (
                    item.embedding is not None and item.embedding_model == provider.model_name
                ):
                    continue
                candidates.append((item, text))
            job.total = len(candidates)
            session.commit()

            for start in range(0, len(candidates), EMBED_CHUNK_SIZE):
                chunk = candidates[start : start + EMBED_CHUNK_SIZE]
                vectors = provider.embed([text for _, text in chunk])
                for (item, _), vector in zip(chunk, vectors, strict=True):
                    item.embedding = vector
                    item.embedding_model = provider.model_name
                job.progress += len(chunk)
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


def run_cluster(job_id: int, distance_threshold: float | None = None) -> None:
    """Versioned agglomerative clustering + near-text duplicate rebuild.

    Fully local and deterministic — no LLM, no network — so it is runnable
    before review. Every execution creates a new `cluster_runs` row over the
    items embedded with the active model; singletons stay unclustered.
    Afterwards `near_text` duplicate groups are rebuilt from scratch from
    cosine similarity (exact shortcode/URL groups are never touched).
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
        job.total = 3  # cluster, dedupe, finalize — coarse but visible
        session.commit()
        run: ClusterRun | None = None
        try:
            config = get_config()
            model_name = get_embedding_provider(config).model_name
            threshold = (
                distance_threshold
                if distance_threshold is not None
                else config.cluster_distance_threshold
            )
            run = ClusterRun(
                method=CLUSTER_METHOD,
                params={
                    "distance_threshold": threshold,
                    "linkage": LINKAGE,
                    "metric": "cosine",
                    "min_cluster_size": MIN_CLUSTER_SIZE,
                    "near_duplicate_similarity_threshold": (
                        config.near_duplicate_similarity_threshold
                    ),
                },
                embedding_model=model_name,
                status=ClusterRunStatus.running,
            )
            session.add(run)
            session.commit()

            items = list(
                session.scalars(
                    select(Item)
                    .where(Item.embedding.is_not(None), Item.embedding_model == model_name)
                    .order_by(Item.id)
                )
            )
            if len(items) >= 2:
                matrix = np.stack([np.asarray(item.embedding, dtype=np.float64) for item in items])
                groups = cluster_embeddings(matrix, distance_threshold=threshold)
            else:
                matrix = None
                groups = []
            for member_indices in groups:
                cluster = Cluster(run_id=run.id, size=len(member_indices))
                session.add(cluster)
                session.flush()
                session.add_all(
                    ItemCluster(item_id=items[index].id, cluster_id=cluster.id)
                    for index in member_indices
                )
            job.progress = 1
            session.commit()

            # Rebuild near_text duplicate groups from scratch; exact groups
            # keep their members, which therefore never enter near-dedupe.
            cleared_group_ids = set(
                session.scalars(
                    select(DuplicateGroup.id).where(
                        DuplicateGroup.reason == DuplicateReason.near_text
                    )
                )
            )
            if cleared_group_ids:
                session.execute(
                    update(Item)
                    .where(Item.duplicate_group_id.in_(cleared_group_ids))
                    .values(duplicate_group_id=None)
                    .execution_options(synchronize_session=False)
                )
                session.execute(
                    delete(DuplicateGroup).where(DuplicateGroup.id.in_(cleared_group_ids))
                )
            eligible = [
                item
                for item in items
                if item.duplicate_group_id is None or item.duplicate_group_id in cleared_group_ids
            ]
            if matrix is not None and len(eligible) >= 2:
                eligible_matrix = np.stack(
                    [np.asarray(item.embedding, dtype=np.float64) for item in eligible]
                )
                components = near_duplicate_components(
                    eligible_matrix,
                    similarity_threshold=config.near_duplicate_similarity_threshold,
                )
                for component in components:
                    members = [eligible[index] for index in component]
                    canonical = min(members, key=lambda i: (i.shared_at or _utcnow(), i.id))
                    group = DuplicateGroup(
                        canonical_item_id=canonical.id, reason=DuplicateReason.near_text
                    )
                    session.add(group)
                    session.flush()
                    for member in members:
                        member.duplicate_group_id = group.id
            job.progress = 2
            session.commit()

            run.status = ClusterRunStatus.succeeded
            job.progress = 3
            job.status = JobStatus.succeeded
            job.finished_at = _utcnow()
            session.commit()
        except Exception as exc:
            session.rollback()
            if run is not None and run.id is not None:
                run.status = ClusterRunStatus.failed
            job.status = JobStatus.failed
            job.error = type(exc).__name__
            job.finished_at = _utcnow()
            session.commit()
            raise


def run_topics(job_id: int, cluster_run_id: int | None = None) -> None:
    """Fast-model topic extraction + cluster labeling over one cluster run.

    Per cluster (own transaction, visible progress): only items passing the
    anti-hallucination gate contribute text; echoed item_ids are verified
    server-side; labels/descriptions are written only when still NULL so user
    edits survive re-runs. A budget abort mid-batch keeps completed clusters.
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
            config = get_config()
            if cluster_run_id is not None:
                run = session.get(ClusterRun, cluster_run_id)
            else:
                run = session.scalar(
                    select(ClusterRun)
                    .where(ClusterRun.status == ClusterRunStatus.succeeded)
                    .order_by(ClusterRun.id.desc())
                    .limit(1)
                )
            if run is None:
                raise ValueError("no succeeded cluster run available for topic extraction")

            settings = session.get(AppSettings, 1)
            provider = get_llm_provider(settings, config)
            model = provider.resolve_model(ModelTier.fast)
            tracker = JobTokenTracker(config.ai_job_token_budget)

            clusters = list(
                session.scalars(
                    select(Cluster).where(Cluster.run_id == run.id).order_by(Cluster.id)
                )
            )
            job.total = len(clusters)
            session.commit()

            for cluster in clusters:
                members = list(
                    session.scalars(
                        select(Item)
                        .join(ItemCluster, ItemCluster.item_id == Item.id)
                        .where(ItemCluster.cluster_id == cluster.id)
                        .order_by(Item.id)
                    )
                )
                context_items = build_llm_context_items(
                    members,
                    max_chars_per_item=config.topics_max_chars_per_item,
                    max_items=config.topics_max_items_per_cluster,
                )
                if context_items:
                    if cluster.label is None or cluster.description_md is None:
                        label_result = generate_validated(
                            session,
                            provider,
                            task=TASK_CLUSTER_LABEL,
                            context={"items": context_items},
                            schema=ClusterLabel,
                            model=model,
                            config=config,
                            job_id=job.id,
                            token_tracker=tracker,
                        )
                        if cluster.label is None:
                            cluster.label = label_result.label[:256]
                        if cluster.description_md is None:
                            cluster.description_md = label_result.description_md

                    topics_result = generate_validated(
                        session,
                        provider,
                        task=TASK_TOPIC_EXTRACTION,
                        context={"items": context_items},
                        schema=TopicExtraction,
                        model=model,
                        config=config,
                        job_id=job.id,
                        token_tracker=tracker,
                    )
                    allowed_ids = {entry["item_id"] for entry in context_items}
                    verify_echoed_item_ids(
                        [assignment.item_id for assignment in topics_result.assignments],
                        allowed_ids,
                    )
                    echoed_ids = [a.item_id for a in topics_result.assignments]
                    session.execute(delete(ItemTopic).where(ItemTopic.item_id.in_(echoed_ids)))
                    for assignment in topics_result.assignments:
                        confidence_by_topic: dict[int, float] = {}
                        for entry in assignment.topics:
                            topic = get_or_create_topic(session, entry.name)
                            existing_confidence = confidence_by_topic.get(topic.id, 0.0)
                            confidence_by_topic[topic.id] = max(
                                existing_confidence, entry.confidence
                            )
                        session.add_all(
                            ItemTopic(
                                item_id=assignment.item_id,
                                topic_id=topic_id,
                                confidence=confidence,
                            )
                            for topic_id, confidence in confidence_by_topic.items()
                        )
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


def run_generate_projects(
    job_id: int,
    item_ids: list[int] | None = None,
    cluster_ids: list[int] | None = None,
    count: int | None = None,
) -> None:
    """Generate grounded project ideas from selected clusters/items + career
    profile (M7). One generation-tier LLM call returns the whole batch; every
    idea's echoed source item/cluster ids are verified server-side before any
    project row is written — a fabricated citation fails the job.
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
            config = get_config()
            requested_item_ids = list(item_ids or [])
            requested_cluster_ids = list(cluster_ids or [])
            requested_count = count if count is not None else config.projects_default_count
            requested_count = max(1, min(requested_count, config.projects_max_count))
            context, allowed_item_ids = build_generation_context(
                session,
                config,
                item_ids=requested_item_ids,
                cluster_ids=requested_cluster_ids,
                count=requested_count,
            )
            settings = session.get(AppSettings, 1)
            provider = get_llm_provider(settings, config)
            model = provider.resolve_model(ModelTier.generation)
            tracker = JobTokenTracker(config.ai_job_token_budget)

            result = generate_validated(
                session,
                provider,
                task=TASK_GENERATE_PROJECTS,
                context=context,
                schema=ProjectIdeas,
                model=model,
                config=config,
                job_id=job.id,
                token_tracker=tracker,
            )
            job.total = 1 + len(result.ideas)
            job.progress = 1
            session.commit()

            # Verify the whole batch before persisting any of it: one
            # ungrounded idea fails the generation, no partial writes.
            allowed_cluster_ids = set(requested_cluster_ids)
            for idea in result.ideas:
                verify_idea_grounding(
                    idea,
                    allowed_item_ids=allowed_item_ids,
                    allowed_cluster_ids=allowed_cluster_ids,
                )
            for idea in result.ideas:
                project = Project()
                apply_generated_fields(project, idea)
                project.source = generation_source(
                    item_ids=idea.source_item_ids,
                    cluster_ids=idea.source_cluster_ids,
                    prompt_version=PROMPT_VERSION,
                    provider=provider.name,
                    model=model,
                )
                session.add(project)
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


def run_combine_projects(job_id: int, parent_project_ids: list[int]) -> None:
    """Combine two parent projects into one child (M7). The child's `source`
    is the union of the parents' provenance and `parent_project_ids` links
    both parents; the provider only ever sees the parents' generated text."""
    with get_sessionmaker()() as session:
        job = session.get(Job, job_id)
        if job is None:
            raise ValueError(f"jobs row {job_id} does not exist")
        if job.status in (JobStatus.succeeded, JobStatus.cancelled):
            return
        job.status = JobStatus.running
        job.started_at = _utcnow()
        job.progress = 0
        job.total = 2
        session.commit()
        try:
            config = get_config()
            parents = [session.get(Project, parent_id) for parent_id in parent_project_ids]
            loaded = [parent for parent in parents if parent is not None]
            if len(loaded) != 2 or len(parent_project_ids) != 2:
                raise ValueError("combine requires exactly two existing parent projects")

            settings = session.get(AppSettings, 1)
            provider = get_llm_provider(settings, config)
            model = provider.resolve_model(ModelTier.generation)
            tracker = JobTokenTracker(config.ai_job_token_budget)

            result = generate_validated(
                session,
                provider,
                task=TASK_COMBINE_PROJECTS,
                context=build_combine_context(loaded, load_career_profile_context(session)),
                schema=CombinedProject,
                model=model,
                config=config,
                job_id=job.id,
                token_tracker=tracker,
            )
            job.progress = 1
            session.commit()

            source_item_ids, source_cluster_ids = combined_source_ids(loaded)
            child = Project()
            apply_generated_fields(child, result)
            child.source = generation_source(
                item_ids=source_item_ids,
                cluster_ids=source_cluster_ids,
                prompt_version=PROMPT_VERSION,
                provider=provider.name,
                model=model,
            )
            child.parent_project_ids = [parent.id for parent in loaded]
            session.add(child)
            job.progress = 2
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


def run_regenerate_project(job_id: int, project_id: int) -> None:
    """Regenerate one project from its stored source ids (M7). Replaces the
    generated fields only — status, milestones, parent links, and existing
    advisor reviews are user-owned state and survive untouched."""
    with get_sessionmaker()() as session:
        job = session.get(Job, job_id)
        if job is None:
            raise ValueError(f"jobs row {job_id} does not exist")
        if job.status in (JobStatus.succeeded, JobStatus.cancelled):
            return
        job.status = JobStatus.running
        job.started_at = _utcnow()
        job.progress = 0
        job.total = 2
        session.commit()
        try:
            config = get_config()
            project = session.get(Project, project_id)
            if project is None:
                raise ValueError(f"projects row {project_id} does not exist")
            source = project.source or {}
            source_item_ids = [int(value) for value in source.get("item_ids", [])]
            source_cluster_ids = [int(value) for value in source.get("cluster_ids", [])]
            context, allowed_item_ids = build_generation_context(
                session,
                config,
                item_ids=source_item_ids,
                cluster_ids=source_cluster_ids,
                count=1,
            )
            settings = session.get(AppSettings, 1)
            provider = get_llm_provider(settings, config)
            model = provider.resolve_model(ModelTier.generation)
            tracker = JobTokenTracker(config.ai_job_token_budget)

            result = generate_validated(
                session,
                provider,
                task=TASK_GENERATE_PROJECTS,
                context=context,
                schema=ProjectIdeas,
                model=model,
                config=config,
                job_id=job.id,
                token_tracker=tracker,
            )
            job.progress = 1
            session.commit()

            idea = result.ideas[0]
            verify_idea_grounding(
                idea,
                allowed_item_ids=allowed_item_ids,
                allowed_cluster_ids=set(source_cluster_ids),
            )
            apply_generated_fields(project, idea)
            project.source = generation_source(
                item_ids=idea.source_item_ids,
                cluster_ids=idea.source_cluster_ids,
                prompt_version=PROMPT_VERSION,
                provider=provider.name,
                model=model,
            )
            job.progress = 2
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


def run_advisor_review(job_id: int, project_id: int) -> None:
    """Project Advisor (M7): one generation-tier call producing the five
    structured sections, stored as a versioned `advisor_review` artifact.
    Re-running appends the next version; earlier versions stay."""
    with get_sessionmaker()() as session:
        job = session.get(Job, job_id)
        if job is None:
            raise ValueError(f"jobs row {job_id} does not exist")
        if job.status in (JobStatus.succeeded, JobStatus.cancelled):
            return
        job.status = JobStatus.running
        job.started_at = _utcnow()
        job.progress = 0
        job.total = 2
        session.commit()
        try:
            config = get_config()
            project = session.get(Project, project_id)
            if project is None:
                raise ValueError(f"projects row {project_id} does not exist")
            library = list(session.scalars(select(Project).order_by(Project.id)))

            settings = session.get(AppSettings, 1)
            provider = get_llm_provider(settings, config)
            model = provider.resolve_model(ModelTier.generation)
            tracker = JobTokenTracker(config.ai_job_token_budget)

            review = generate_validated(
                session,
                provider,
                task=TASK_ADVISOR_REVIEW,
                context=build_advisor_context(
                    project, library, load_career_profile_context(session)
                ),
                schema=AdvisorReview,
                model=model,
                config=config,
                job_id=job.id,
                token_tracker=tracker,
            )
            job.progress = 1
            session.commit()

            session.add(
                Artifact(
                    project_id=project.id,
                    kind=ArtifactKind.advisor_review,
                    content_md=render_advisor_markdown(review),
                    payload=review.model_dump(),
                    provider=provider.name,
                    model=model,
                    prompt_version=PROMPT_VERSION,
                    version=next_artifact_version(session, project.id, ArtifactKind.advisor_review),
                )
            )
            job.progress = 2
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


def run_generate_career_artifact(job_id: int, project_id: int, kind: str) -> None:
    """Career artifacts (M8): README, resume bullets, portfolio description,
    interview answer, or technical questions — one generation-tier call per
    kind (dispatched by `kind` via `CAREER_ARTIFACT_SPECS` instead of one
    function per kind), stored as a versioned artifact. The claims guard
    flags (never blocks) suspicious performance-claim language in the
    rendered markdown."""
    with get_sessionmaker()() as session:
        job = session.get(Job, job_id)
        if job is None:
            raise ValueError(f"jobs row {job_id} does not exist")
        if job.status in (JobStatus.succeeded, JobStatus.cancelled):
            return
        job.status = JobStatus.running
        job.started_at = _utcnow()
        job.progress = 0
        job.total = 2
        session.commit()
        try:
            artifact_kind = ArtifactKind(kind)
            spec = CAREER_ARTIFACT_SPECS[artifact_kind]
            config = get_config()
            project = session.get(Project, project_id)
            if project is None:
                raise ValueError(f"projects row {project_id} does not exist")

            settings = session.get(AppSettings, 1)
            provider = get_llm_provider(settings, config)
            model = provider.resolve_model(ModelTier.generation)
            tracker = JobTokenTracker(config.ai_job_token_budget)

            result = generate_validated(
                session,
                provider,
                task=spec.task,
                context=build_career_artifact_context(
                    project, load_career_profile_context(session)
                ),
                schema=spec.schema,
                model=model,
                config=config,
                job_id=job.id,
                token_tracker=tracker,
            )
            job.progress = 1
            session.commit()

            content_md = spec.render_markdown(result)
            session.add(
                Artifact(
                    project_id=project.id,
                    kind=artifact_kind,
                    content_md=content_md,
                    payload=result.model_dump(),
                    claims_flags=find_claims(content_md),
                    provider=provider.name,
                    model=model,
                    prompt_version=PROMPT_VERSION,
                    version=next_artifact_version(session, project.id, artifact_kind),
                )
            )
            job.progress = 2
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


def run_export_bundle(job_id: int, export_id: int) -> None:
    """Markdown/JSON export (M8): renders a project bundle (or, when
    `exports.project_id IS NULL`, the full library) and writes it through
    Storage. Fills in the `exports` row's `storage_key`/`size_bytes` (or
    `error`) so `GET /api/exports/{id}` reports readiness without needing to
    cross-reference the job."""
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
        export_row: Export | None = None
        try:
            export_row = session.get(Export, export_id)
            if export_row is None:
                raise ValueError(f"exports row {export_id} does not exist")

            if export_row.project_id is not None:
                project = session.get(Project, export_row.project_id)
                if project is None:
                    raise ValueError(f"projects row {export_row.project_id} does not exist")
                project_export = build_project_export(session, project)
                if export_row.format is ExportBundleFormat.markdown:
                    content = render_project_markdown(project_export)
                    extension = "md"
                else:
                    content = project_export.model_dump_json(indent=2)
                    extension = "json"
            else:
                library_export = build_library_export(session)
                if export_row.format is ExportBundleFormat.markdown:
                    content = render_library_markdown(library_export)
                    extension = "md"
                else:
                    content = library_export.model_dump_json(indent=2)
                    extension = "json"

            data = content.encode("utf-8")
            storage = LocalStorage(get_config().data_dir)
            spool_path = storage.spool_dir() / f"export-{uuid4().hex}.{extension}"
            spool_path.write_bytes(data)
            storage_key = f"exports/{uuid4().hex}.{extension}"
            storage.save_file(storage_key, spool_path)

            export_row.storage_key = storage_key
            export_row.size_bytes = len(data)
            job.progress = 1
            job.status = JobStatus.succeeded
            job.finished_at = _utcnow()
            session.commit()
        except Exception as exc:
            session.rollback()
            job.status = JobStatus.failed
            job.error = type(exc).__name__
            job.finished_at = _utcnow()
            if export_row is not None:
                export_row.error = type(exc).__name__
            session.commit()
            raise


def run_delete_data(job_id: int) -> None:
    """Complete wipe (M9): every table except `users`, every stored file.
    The verification report (before/after row counts + files-remaining
    check) is written into this job's own `payload` so the existing job-
    polling UI surfaces it with no new endpoint."""
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
            storage = LocalStorage(get_config().data_dir)
            report = wipe_everything(session, storage, keep_job_id=job.id)
            job.payload = {"report": report}
            job.progress = 1
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
