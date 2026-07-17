"""Streamed reading of Instagram-export ZIPs into typed thread structures.

Entries are read one at a time via ``zipfile`` — the archive is never
extracted to disk. Both export layouts are handled identically because the
thread path is derived from the entry name's ``inbox/<dir>`` suffix, which is
the same in `your_instagram_activity/messages/inbox/…` (current) and
`messages/inbox/…` (legacy). Paginated ``message_N.json`` files (newest page
first) are merged and re-sorted chronologically. Every string is passed
through the mojibake fix.

Tolerated message shapes: missing ``content``, missing ``share`` /
``share_text``, media-only, unsent. Messages without a sender name or
timestamp are skipped. Malformed JSON raises — the surrounding job fails
cleanly with a redacted error.
"""

from __future__ import annotations

import json
import re
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from app.services.ingest.instagram.encoding import fix_mojibake, fix_optional

_MESSAGE_ENTRY_RE = re.compile(r"(?:^|/)messages/(inbox/[^/]+)/message_(\d+)\.json$")
_PERSONAL_INFO_RE = re.compile(r"(?:^|/)personal_information\.json$")


@dataclass(frozen=True)
class ParsedMessage:
    sender_name: str
    timestamp_ms: int
    content: str | None
    share_link: str | None
    share_text: str | None


@dataclass(frozen=True)
class ParsedThread:
    thread_path: str  # normalized "inbox/<dir>" — identical across export layouts
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


def _parse_message(raw: Any) -> ParsedMessage | None:
    if not isinstance(raw, dict):
        return None
    sender = raw.get("sender_name")
    timestamp_ms = raw.get("timestamp_ms")
    if not isinstance(sender, str) or not isinstance(timestamp_ms, int):
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


def iter_threads(archive: zipfile.ZipFile) -> Iterator[ParsedThread]:
    """Yield one ParsedThread per thread directory, in deterministic order.

    Only one thread's messages are held in memory at a time.
    """
    for thread_path, pages in sorted(thread_entries(archive).items()):
        title: str | None = None
        participants: list[str] = []
        messages: list[ParsedMessage] = []
        for index, (_, entry_name) in enumerate(pages):
            payload = _load_json(archive, entry_name)
            if not isinstance(payload, dict):
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
                parsed = _parse_message(raw_message)
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
