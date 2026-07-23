"""Streamed reading of Instagram-export ZIPs into typed thread structures.

Entries are read one at a time via ``zipfile`` — the archive is never
extracted to disk. Both export layouts are handled identically because the
thread path is derived from the entry name's ``<category>/<dir>`` suffix,
which is the same in `your_instagram_activity/messages/<category>/…`
(current) and `messages/<category>/…` (legacy). ``<category>`` is one of
`format_detection.KNOWN_MESSAGE_CATEGORIES` — `inbox` plus Meta's other
documented thread categories (M10). Paginated ``message_N.json`` files
(newest page first) are merged and re-sorted chronologically. Every string is
passed through the mojibake fix.

Tolerated message shapes: missing ``content``, missing ``share`` /
``share_text``, media-only, unsent. Messages without a sender name or
timestamp are skipped. Malformed JSON raises — the surrounding job fails
cleanly with a redacted error.

**Nothing here is silently dropped** (M10): every skip — a non-dict page
payload, a non-object raw message, a message missing sender/timestamp, or a
message-shaped JSON path under an unrecognized `messages/<category>/`
directory — increments a counter on the caller-supplied `ScanIssues`. Only
counts and structural path segments (category *names*, never message
content) are ever recorded.
"""

from __future__ import annotations

import json
import re
import zipfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

from app.services.ingest.format_detection import ANY_MESSAGE_JSON_RE, KNOWN_MESSAGE_CATEGORIES
from app.services.ingest.instagram.encoding import fix_mojibake, fix_optional

_MESSAGE_ENTRY_RE = re.compile(
    rf"(?:^|/)messages/((?:{'|'.join(KNOWN_MESSAGE_CATEGORIES)})/[^/]+)/message_(\d+)\.json$"
)
_PERSONAL_INFO_RE = re.compile(r"(?:^|/)personal_information\.json$")
_MAX_UNRECOGNIZED_CATEGORIES = 10  # small, bounded — structural directory names only


@dataclass
class ScanIssues:
    """Counts of scan-pass skips, by category — never any message content.

    `unrecognized_categories` holds up to `_MAX_UNRECOGNIZED_CATEGORIES`
    distinct `messages/<category>/` directory names seen that aren't one of
    `KNOWN_MESSAGE_CATEGORIES` — a structural path segment, not content.
    """

    non_dict_page_payload: int = 0
    message_not_object: int = 0
    message_missing_sender_or_timestamp: int = 0
    unrecognized_message_path: int = 0
    unrecognized_categories: set[str] = field(default_factory=set)

    def record_unrecognized_path(self, category: str) -> None:
        self.unrecognized_message_path += 1
        if len(self.unrecognized_categories) < _MAX_UNRECOGNIZED_CATEGORIES:
            self.unrecognized_categories.add(category)

    def as_dict(self) -> dict[str, Any]:
        return {
            "non_dict_page_payload": self.non_dict_page_payload,
            "message_not_object": self.message_not_object,
            "message_missing_sender_or_timestamp": self.message_missing_sender_or_timestamp,
            "unrecognized_message_path": self.unrecognized_message_path,
            "unrecognized_message_path_categories": sorted(self.unrecognized_categories),
        }


def scan_unrecognized_message_paths(entry_names: Iterable[str], issues: ScanIssues) -> None:
    """Records message-shaped JSON entries under an unrecognized `messages/<category>/`
    directory — the one place a whole future/unknown thread category could
    otherwise vanish with zero signal anywhere (M10)."""
    for name in entry_names:
        normalized = _normalized(name)
        if _MESSAGE_ENTRY_RE.search(normalized):
            continue
        match = ANY_MESSAGE_JSON_RE.search(normalized)
        if match:
            issues.record_unrecognized_path(match.group(1))


@dataclass(frozen=True)
class ParsedMessage:
    sender_name: str
    timestamp_ms: int
    content: str | None
    share_link: str | None
    share_text: str | None


@dataclass(frozen=True)
class ParsedThread:
    thread_path: str  # normalized "<category>/<dir>" — identical across export layouts
    title: str | None
    participant_names: tuple[str, ...]
    messages: tuple[ParsedMessage, ...]  # ascending by timestamp


def _normalized(name: str) -> str:
    return name.replace("\\", "/")


def thread_entries(archive: zipfile.ZipFile) -> dict[str, list[tuple[int, str]]]:
    """Map thread_path -> [(page_number, entry_name)], pages sorted ascending."""
    threads: dict[str, list[tuple[int, str]]] = {}
    for name in archive.namelist():
        match = _MESSAGE_ENTRY_RE.search(_normalized(name))
        if match:
            threads.setdefault(match.group(1), []).append((int(match.group(2)), name))
    for pages in threads.values():
        pages.sort()
    return threads


def _parse_message(raw: Any, issues: ScanIssues | None = None) -> ParsedMessage | None:
    if not isinstance(raw, dict):
        if issues is not None:
            issues.message_not_object += 1
        return None
    sender = raw.get("sender_name")
    timestamp_ms = raw.get("timestamp_ms")
    if not isinstance(sender, str) or not isinstance(timestamp_ms, int):
        if issues is not None:
            issues.message_missing_sender_or_timestamp += 1
        return None
    content = raw.get("content")
    share = raw.get("share")
    share_link: str | None = None
    share_text: str | None = None
    if isinstance(share, dict):
        link = share.get("link")
        text = share.get("share_text")
        share_link = link if isinstance(link, str) else None
        share_text = text if isinstance(text, str) else None
    return ParsedMessage(
        sender_name=fix_mojibake(sender),
        timestamp_ms=timestamp_ms,
        content=fix_optional(content if isinstance(content, str) else None),
        share_link=fix_optional(share_link),
        share_text=fix_optional(share_text),
    )


def _load_json(archive: zipfile.ZipFile, entry_name: str) -> Any:
    with archive.open(entry_name) as entry:
        return json.load(entry)


def iter_threads(
    archive: zipfile.ZipFile, issues: ScanIssues | None = None
) -> Iterator[ParsedThread]:
    """Yield one ParsedThread per thread directory, in deterministic order.

    Only one thread's messages are held in memory at a time. `issues`, when
    given, accumulates counts of every skip encountered (M10) — never any
    message content.
    """
    for thread_path, pages in sorted(thread_entries(archive).items()):
        title: str | None = None
        participants: list[str] = []
        messages: list[ParsedMessage] = []
        for index, (_, entry_name) in enumerate(pages):
            payload = _load_json(archive, entry_name)
            if not isinstance(payload, dict):
                if issues is not None:
                    issues.non_dict_page_payload += 1
                continue
            if index == 0:  # lowest page number = newest — its metadata wins
                raw_title = payload.get("title")
                title = fix_optional(raw_title if isinstance(raw_title, str) else None)
            for participant in payload.get("participants") or []:
                if isinstance(participant, dict) and isinstance(participant.get("name"), str):
                    name = fix_mojibake(participant["name"])
                    if name not in participants:
                        participants.append(name)
            for raw_message in payload.get("messages") or []:
                parsed = _parse_message(raw_message, issues)
                if parsed is not None:
                    messages.append(parsed)
        messages.sort(key=lambda m: m.timestamp_ms)
        yield ParsedThread(
            thread_path=thread_path,
            title=title,
            participant_names=tuple(participants),
            messages=tuple(messages),
        )


def read_owner_name(archive: zipfile.ZipFile) -> str | None:
    """Owner name from ``personal_information.json``, if present and well-formed."""
    for name in archive.namelist():
        if not _PERSONAL_INFO_RE.search(_normalized(name)):
            continue
        payload = _load_json(archive, name)
        if not isinstance(payload, dict):
            continue
        profiles = payload.get("profile_user")
        if not isinstance(profiles, list):
            continue
        for profile in profiles:
            if not isinstance(profile, dict):
                continue
            string_map = profile.get("string_map_data")
            if not isinstance(string_map, dict):
                continue
            entry = string_map.get("Name")
            if isinstance(entry, dict) and isinstance(entry.get("value"), str):
                return fix_mojibake(entry["value"])
    return None
