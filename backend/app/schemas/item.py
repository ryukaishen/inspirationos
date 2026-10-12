from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enrichment_attempt import EnrichmentSource
from app.models.item import ItemStatus, ItemType


class ItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    import_id: int | None
    conversation_id: int | None
    message_id: int | None
    url_raw: str
    url_canonical: str
    shortcode: str | None
    item_type: ItemType
    shared_at: datetime | None
    share_text: str | None
    adjacent_text: str | None
    enriched_title: str | None
    enriched_caption: str | None
    enriched_author: str | None
    enriched_source: EnrichmentSource | None
    context_note: str | None
    transcript: str | None
    visual_text: str | None
    status: ItemStatus
    tags: list[str]
    duplicate_group_id: int | None
    created_at: datetime
    updated_at: datetime


class ItemEntry(BaseModel):
    """One inbox row: a standalone item, or a duplicate group's canonical item."""

    item: ItemRead
    duplicate_count: int


class ItemListResponse(BaseModel):
    entries: list[ItemEntry]
    total: int
    page: int
    page_size: int


class ItemUpdateRequest(BaseModel):
    """All fields optional; only fields present in the request body are applied
    (see `exclude_unset=True` in the endpoint) — a PATCH, not a PUT."""

    status: ItemStatus | None = None
    tags: list[str] | None = None
    context_note: str | None = None


class BulkUpdateRequest(BaseModel):
    # Optional on its own: a group-only bulk action supplies no literal
    # item_ids, only duplicate_group_ids (see _expand_item_ids).
    item_ids: list[int] = Field(default_factory=list)
    status: ItemStatus | None = None
    add_tags: list[str] | None = None
    context_note: str | None = None
    # Expanded server-side to every member — lets one bulk action cover an
    # entire "shared again" group, not just its canonical (visible) item.
    duplicate_group_ids: list[int] | None = None


class BulkUpdateResponse(BaseModel):
    updated: int


class EnrichRequest(BaseModel):
    """Backs per-item/per-selection/per-group Enrich actions — the same
    endpoint serves all three (and, later, per-cluster) via item_ids and/or
    duplicate_group_ids expansion."""

    item_ids: list[int] = Field(default_factory=list)
    duplicate_group_ids: list[int] | None = None


class EnrichAccepted(BaseModel):
    job_id: int


class ConversationFacet(BaseModel):
    id: int
    title: str | None
    item_count: int


class TagFacet(BaseModel):
    tag: str
    item_count: int


class ItemFacets(BaseModel):
    conversations: list[ConversationFacet]
    tags: list[TagFacet]
