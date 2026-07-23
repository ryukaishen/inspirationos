from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.import_ import ExportFormat, ImportStatus
from app.schemas.job import JobRead


class ImportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    filename: str
    size_bytes: int
    checksum_sha256: str
    export_format: ExportFormat
    status: ImportStatus
    counts: dict[str, Any]
    error: str | None
    created_at: datetime


class ImportDetail(ImportRead):
    latest_job: JobRead | None = None


class UploadAccepted(BaseModel):
    import_id: int
    job_id: int


class SkippedEntryBreakdown(BaseModel):
    """One category of scan-pass skip — a count and a static, non-content
    description (M10). Never carries message content or per-entry paths."""

    category: str
    count: int
    description: str


class DuplicateReasonSummary(BaseModel):
    """Aggregate duplicate-group counts for one import, by reason — a
    lightweight spot-check aid (M10); individual groups stay in the Inbox's
    existing duplicate-group UI (M4)."""

    reason: str
    group_count: int
    item_count: int


class ImportVerificationReport(BaseModel):
    """Raw-ZIP-scan vs. parsed counts, every skip categorized, and a
    duplicate-reason summary — so "how much of the real export did we
    actually use, and why not the rest" is always answerable, never silent
    (M10)."""

    import_id: int
    status: ImportStatus
    raw_message_json_entries: int
    matched_message_json_entries: int
    conversations_found: int
    messages_parsed: int
    messages_skipped: int
    skip_breakdown: list[SkippedEntryBreakdown]
    extracted_messages: int | None
    items_extracted: int | None
    duplicate_summary: list[DuplicateReasonSummary]
