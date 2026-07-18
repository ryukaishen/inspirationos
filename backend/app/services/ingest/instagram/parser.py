"""Pure scan/extract logic over parsed threads.

Scan: per-thread summaries (counts, dates, self-DM flag) — the caller
persists them as `conversations` rows; message bodies never leave memory.
Extract: message rows plus item drafts (links, canonical forms, adjacent-text
windows) for user-selected conversations, and exact duplicate grouping.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from app.models.item import Item, ItemStatus, ItemType
from app.services.enrichment.policy import initial_status_for
from app.services.ingest.instagram.export_reader import ParsedMessage, ParsedThread
from app.services.ingest.instagram.links import CanonicalLink, canonicalize, extract_urls


@dataclass(frozen=True)
class ConversationSummary:
    """Everything the scan pass persists about a thread — no message bodies.

    The self-DM flag is computed by the caller once the owner is known
    (fallback owner detection needs every thread's participants first).
    """

    thread_path: str
    title: str | None
    participant_names: tuple[str, ...]
    message_count: int
    link_count: int
    first_message_at: datetime | None
    last_message_at: datetime | None


@dataclass(frozen=True)
class ItemDraft:
    """One link occurrence; `message_index` points into the thread's messages."""

    message_index: int
    url_raw: str
    url_canonical: str
    shortcode: str | None
    item_type: ItemType
    shared_at: datetime
    share_text: str | None
    adjacent_text: str | None
    status: ItemStatus


def to_datetime(timestamp_ms: int) -> datetime:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC)


def message_links(message: ParsedMessage) -> list[CanonicalLink]:
    """Unique-by-canonical links of one message: `share.link` + URLs in content."""
    urls: list[str] = []
    if message.share_link and message.share_link.startswith(("http://", "https://")):
        urls.append(message.share_link)
    if message.content:
        urls.extend(extract_urls(message.content))
    links: list[CanonicalLink] = []
    seen: set[str] = set()
    for url in urls:
        link = canonicalize(url)
        if link.url_canonical not in seen:
            seen.add(link.url_canonical)
            links.append(link)
    return links


def summarize_thread(thread: ParsedThread) -> ConversationSummary:
    link_count = sum(len(message_links(message)) for message in thread.messages)
    first = thread.messages[0].timestamp_ms if thread.messages else None
    last = thread.messages[-1].timestamp_ms if thread.messages else None
    return ConversationSummary(
        thread_path=thread.thread_path,
        title=thread.title,
        participant_names=thread.participant_names,
        message_count=len(thread.messages),
        link_count=link_count,
        first_message_at=to_datetime(first) if first is not None else None,
        last_message_at=to_datetime(last) if last is not None else None,
    )


def adjacent_text_for(
    messages: Sequence[ParsedMessage], index: int, window_seconds: int
) -> str | None:
    """Same-sender message texts within ± the window, chronological, joined.

    Includes the carrying message's own text — a link pasted inside a note is
    its own best context.
    """
    center = messages[index]
    window_ms = window_seconds * 1000
    texts = [
        message.content
        for message in messages
        if message.sender_name == center.sender_name
        and abs(message.timestamp_ms - center.timestamp_ms) <= window_ms
        and message.content
    ]
    return "\n".join(texts) if texts else None


def build_item_drafts(thread: ParsedThread, window_seconds: int) -> list[ItemDraft]:
    drafts: list[ItemDraft] = []
    for index, message in enumerate(thread.messages):
        links = message_links(message)
        if not links:
            continue
        adjacent = adjacent_text_for(thread.messages, index, window_seconds)
        for link in links:
            drafts.append(
                ItemDraft(
                    message_index=index,
                    url_raw=link.url_raw,
                    url_canonical=link.url_canonical,
                    shortcode=link.shortcode,
                    item_type=link.item_type,
                    shared_at=to_datetime(message.timestamp_ms),
                    share_text=message.share_text,
                    adjacent_text=adjacent,
                    status=initial_status_for(message.share_text, adjacent),
                )
            )
    return drafts


def group_exact_duplicates(items: Sequence[Item]) -> list[tuple[str, list[Item]]]:
    """Groups of ≥2 items that are the same content: by shortcode when present,
    else by canonical URL. Returns (reason, members) pairs."""
    groups: dict[tuple[str, str], list[Item]] = {}
    for item in items:
        if item.shortcode:
            key = ("same_shortcode", item.shortcode)
        else:
            key = ("same_canonical_url", item.url_canonical)
        groups.setdefault(key, []).append(item)
    return [(reason, members) for (reason, _), members in groups.items() if len(members) >= 2]
