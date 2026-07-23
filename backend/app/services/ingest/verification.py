"""Import verification report (M10).

Assembles a report entirely from `Import.counts` (already computed by
`run_import_scan`/`run_import_extract`, see `app/workers/jobs.py`) plus a
fresh `duplicate_groups` query — no ZIP is reopened and no message content is
read. The report exists so a real-export run always answers "how much of the
raw export did we actually use, and why not the rest" with categorized
counts, never a silent gap; see docs/TESTING_STRATEGY.md's real-data
workflow.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.import_ import Import
from app.models.item import DuplicateGroup, Item
from app.schemas.import_ import (
    DuplicateReasonSummary,
    ImportVerificationReport,
    SkippedEntryBreakdown,
)

# Static, non-content descriptions — one per counter written by
# `ScanIssues.as_dict()` (app/services/ingest/instagram/export_reader.py).
_SKIP_DESCRIPTIONS: dict[str, str] = {
    "non_dict_page_payload": "A message_N.json page whose top-level JSON was not an object.",
    "message_not_object": 'An entry in a page\'s "messages" array that was not a JSON object.',
    "message_missing_sender_or_timestamp": (
        "A message object missing a string sender_name or integer timestamp_ms."
    ),
    "unrecognized_message_path": (
        "A message_N.json file under a messages/<category>/ directory that isn't one of the "
        "recognized categories (inbox, message_requests, filtered_threads, archived_threads)."
    ),
}


def build_verification_report(session: Session, import_row: Import) -> ImportVerificationReport:
    counts = import_row.counts or {}
    skipped = counts.get("skipped") or {}

    matched_message_json_entries = int(counts.get("message_files", 0))
    unrecognized_count = int(skipped.get("unrecognized_message_path", 0))
    messages_skipped = int(skipped.get("message_not_object", 0)) + int(
        skipped.get("message_missing_sender_or_timestamp", 0)
    )

    skip_breakdown = [
        SkippedEntryBreakdown(
            category=category,
            count=int(skipped.get(category, 0)),
            description=description,
        )
        for category, description in _SKIP_DESCRIPTIONS.items()
    ]
    unrecognized_categories: list[str] = skipped.get("unrecognized_message_path_categories") or []
    if unrecognized_categories:
        skip_breakdown.append(
            SkippedEntryBreakdown(
                category="unrecognized_message_path_categories_seen",
                count=len(unrecognized_categories),
                description="Distinct unrecognized messages/<category>/ names seen: "
                + ", ".join(unrecognized_categories),
            )
        )

    duplicate_rows = session.execute(
        select(
            DuplicateGroup.reason,
            func.count(func.distinct(DuplicateGroup.id)),
            func.count(Item.id),
        )
        .join(Item, Item.duplicate_group_id == DuplicateGroup.id)
        .where(Item.import_id == import_row.id)
        .group_by(DuplicateGroup.reason)
    ).all()
    duplicate_summary = [
        DuplicateReasonSummary(reason=reason.value, group_count=group_count, item_count=item_count)
        for reason, group_count, item_count in duplicate_rows
    ]

    return ImportVerificationReport(
        import_id=import_row.id,
        status=import_row.status,
        raw_message_json_entries=matched_message_json_entries + unrecognized_count,
        matched_message_json_entries=matched_message_json_entries,
        conversations_found=int(counts.get("conversations", 0)),
        messages_parsed=int(counts.get("messages", 0)),
        messages_skipped=messages_skipped,
        skip_breakdown=skip_breakdown,
        extracted_messages=counts.get("extracted_messages"),
        items_extracted=counts.get("items"),
        duplicate_summary=duplicate_summary,
    )
