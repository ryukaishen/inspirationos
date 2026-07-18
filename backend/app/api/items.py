"""Inbox: browsing, search, filters, and status/tag/note editing over items.

Duplicate groups collapse to one row (the canonical/earliest item) everywhere
in this module — list, count, and facets all share `_canonical_only_stmt()`
so pagination totals and "a filter narrows results" counts stay exact and a
duplicate group never splits across pages.

Error payloads are static strings and IDs only — never item text (see
PRIVACY_SECURITY.md). No jobs are enqueued here (everything is synchronous
CRUD), so the "job payloads are IDs only" rule does not apply to this module.
"""

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from redis import Redis
from rq import Queue
from sqlalchemy import ColumnElement, Select, case, func, or_, select
from sqlalchemy.orm import Session

from app.db import get_db_session
from app.models.app_settings import AppSettings
from app.models.conversation import Conversation
from app.models.item import DuplicateGroup, Item, ItemStatus, ItemType
from app.models.job import Job, JobKind, JobStatus
from app.queues import QUEUE_ENRICHMENT
from app.redis_client import get_redis
from app.schemas.item import (
    BulkUpdateRequest,
    BulkUpdateResponse,
    ConversationFacet,
    EnrichAccepted,
    EnrichRequest,
    ItemEntry,
    ItemFacets,
    ItemListResponse,
    ItemRead,
    ItemUpdateRequest,
    TagFacet,
)
from app.services.enrichment import policy as enrichment_policy

router = APIRouter(prefix="/items", tags=["items"])

ITEM_NOT_FOUND_MESSAGE = "item not found"
NO_OP_MESSAGE = "bulk update requires at least one of status, add_tags, or context_note"
NO_TARGET_MESSAGE = "bulk update requires at least one item_id or duplicate_group_id"
ENRICH_NO_OP_MESSAGE = "enrich requires at least one item_id or duplicate_group_id"
ENRICHMENT_DISABLED_MESSAGE = "enrichment is disabled — enable it in Settings first"
QUEUE_UNAVAILABLE_MESSAGE = "job queue unavailable"

DbSession = Annotated[Session, Depends(get_db_session)]
RedisDep = Annotated[Redis, Depends(get_redis)]


def _canonical_only_stmt() -> Select[tuple[Item]]:
    """Every standalone item, plus exactly one row (the canonical item) per
    duplicate group — never a full group's worth of rows."""
    return (
        select(Item)
        .outerjoin(DuplicateGroup, Item.duplicate_group_id == DuplicateGroup.id)
        .where(
            or_(
                Item.duplicate_group_id.is_(None),
                Item.id == DuplicateGroup.canonical_item_id,
            )
        )
    )


def _fts_document() -> ColumnElement[str]:
    # coalesce(...) || ' ' || ... rather than concat(...): concat() is not
    # IMMUTABLE-eligible for the matching Postgres expression index (see the
    # 0004 migration), so this must stay textually equivalent to that index.
    share = func.coalesce(Item.share_text, "")
    adjacent = func.coalesce(Item.adjacent_text, "")
    note = func.coalesce(Item.context_note, "")
    return func.to_tsvector("english", share + " " + adjacent + " " + note)


def _duplicate_count(item: Item, counts_by_group: dict[int, int]) -> int:
    if item.duplicate_group_id is None:
        return 1
    return counts_by_group.get(item.duplicate_group_id, 1)


def _expand_item_ids(
    db: Session, item_ids: list[int], duplicate_group_ids: list[int] | None
) -> list[int]:
    """Union of the literal item_ids with every member of the given
    duplicate groups — lets one bulk/enrich action cover an entire "shared
    again" group, not just its canonical (visible) item."""
    expanded = set(item_ids)
    if duplicate_group_ids:
        members = db.scalars(
            select(Item.id).where(Item.duplicate_group_id.in_(duplicate_group_ids))
        ).all()
        expanded.update(members)
    return sorted(expanded)


@router.get("", response_model=ItemListResponse)
def list_items(
    db: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    status_filter: Annotated[list[ItemStatus] | None, Query(alias="status")] = None,
    item_type: Annotated[list[ItemType] | None, Query()] = None,
    tags: Annotated[list[str] | None, Query()] = None,
    conversation_id: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    search: str | None = None,
    order: Literal["default", "needs_context_first"] = "default",
) -> ItemListResponse:
    stmt = _canonical_only_stmt()
    if status_filter:
        stmt = stmt.where(Item.status.in_(status_filter))
    if item_type:
        stmt = stmt.where(Item.item_type.in_(item_type))
    if tags:
        stmt = stmt.where(Item.tags.overlap(tags))
    if conversation_id is not None:
        stmt = stmt.where(Item.conversation_id == conversation_id)
    if date_from is not None:
        stmt = stmt.where(Item.shared_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(Item.shared_at <= date_to)
    if search:
        stmt = stmt.where(_fts_document().op("@@")(func.plainto_tsquery("english", search)))

    total = (
        db.scalar(select(func.count()).select_from(stmt.with_only_columns(Item.id).subquery())) or 0
    )

    order_terms: list[ColumnElement[Any]] = []
    if order == "needs_context_first":
        order_terms.append(case((Item.status == ItemStatus.needs_context, 0), else_=1))
    order_terms.extend([Item.shared_at.desc().nulls_last(), Item.id.desc()])

    page_items = list(
        db.scalars(
            stmt.order_by(*order_terms).offset((page - 1) * page_size).limit(page_size)
        ).all()
    )

    group_ids: set[int] = {
        item.duplicate_group_id for item in page_items if item.duplicate_group_id is not None
    }
    counts_by_group: dict[int, int] = {}
    if group_ids:
        rows = db.execute(
            select(Item.duplicate_group_id, func.count())
            .where(Item.duplicate_group_id.in_(group_ids))
            .group_by(Item.duplicate_group_id)
        ).all()
        counts_by_group = {group_id: count for group_id, count in rows if group_id is not None}

    entries = [
        ItemEntry(
            item=ItemRead.model_validate(item),
            duplicate_count=_duplicate_count(item, counts_by_group),
        )
        for item in page_items
    ]
    return ItemListResponse(entries=entries, total=total, page=page, page_size=page_size)


@router.get("/facets", response_model=ItemFacets)
def get_item_facets(db: DbSession) -> ItemFacets:
    canonical_ids = _canonical_only_stmt().with_only_columns(Item.id).scalar_subquery()

    conversation_rows = db.execute(
        select(Conversation.id, Conversation.title, func.count(Item.id))
        .join(Item, Item.conversation_id == Conversation.id)
        .where(Item.id.in_(canonical_ids))
        .group_by(Conversation.id, Conversation.title)
        .order_by(Conversation.id)
    ).all()

    tag_column = func.unnest(Item.tags).label("tag")
    tag_rows = db.execute(
        select(tag_column, func.count().label("item_count"))
        .where(Item.id.in_(canonical_ids))
        .group_by(tag_column)
        .order_by(tag_column)
    ).all()

    return ItemFacets(
        conversations=[
            ConversationFacet(id=row[0], title=row[1], item_count=row[2])
            for row in conversation_rows
        ],
        tags=[TagFacet(tag=row[0], item_count=row[1]) for row in tag_rows],
    )


@router.patch("/{item_id}", response_model=ItemRead)
def update_item(item_id: int, body: ItemUpdateRequest, db: DbSession) -> Item:
    item = db.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ITEM_NOT_FOUND_MESSAGE)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    db.commit()
    return item


@router.post("/bulk", response_model=BulkUpdateResponse)
def bulk_update_items(body: BulkUpdateRequest, db: DbSession) -> BulkUpdateResponse:
    if not body.item_ids and not body.duplicate_group_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "no_op", "message": NO_TARGET_MESSAGE},
        )
    if body.status is None and not body.add_tags and body.context_note is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "no_op", "message": NO_OP_MESSAGE},
        )
    item_ids = _expand_item_ids(db, body.item_ids, body.duplicate_group_ids)
    items = list(db.scalars(select(Item).where(Item.id.in_(item_ids))).all())
    for item in items:
        if body.status is not None:
            item.status = body.status
        if body.add_tags:
            # ARRAY(Text) isn't Mutable-tracked: always reassign, never .append()/.extend().
            item.tags = sorted(set(item.tags) | set(body.add_tags))
        if body.context_note is not None:
            item.context_note = body.context_note
    db.commit()
    return BulkUpdateResponse(updated=len(items))


@router.post("/enrich", response_model=EnrichAccepted, status_code=status.HTTP_202_ACCEPTED)
def enrich_items(body: EnrichRequest, db: DbSession, redis: RedisDep) -> EnrichAccepted:
    """Per-item / per-selection / per-group Enrich trigger — the same shape
    will serve per-cluster once M6 adds clusters, by passing that cluster's
    member item_ids. 403s before any row is created if enrichment isn't
    enabled and consented, so no outbound request ever occurs while it's off.
    """
    settings = db.get(AppSettings, 1)
    if settings is None or not enrichment_policy.consent_given(settings):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "enrichment_disabled", "message": ENRICHMENT_DISABLED_MESSAGE},
        )
    item_ids = _expand_item_ids(db, body.item_ids, body.duplicate_group_ids)
    if not item_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "no_op", "message": ENRICH_NO_OP_MESSAGE},
        )
    job = Job(
        kind=JobKind.enrich_batch,
        status=JobStatus.queued,
        total=len(item_ids),
        payload={"item_ids": item_ids},
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    try:
        rq_job = Queue(QUEUE_ENRICHMENT, connection=redis).enqueue(
            "app.workers.jobs.run_enrich_batch", job.id, item_ids
        )
    except Exception as exc:
        job.status = JobStatus.failed
        job.error = type(exc).__name__
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "queue_unavailable", "message": QUEUE_UNAVAILABLE_MESSAGE},
        ) from exc
    job.rq_job_id = rq_job.id
    db.commit()
    return EnrichAccepted(job_id=job.id)
