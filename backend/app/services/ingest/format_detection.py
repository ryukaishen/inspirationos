"""Instagram export-format detection from ZIP entry **names** only.

No entry contents are read in Milestone 2 — message bodies stay untouched
until the user-selected extract pass (M3).
"""

from __future__ import annotations

import enum
import re
from collections.abc import Iterable


class ExportKind(enum.Enum):
    json = "json"
    html = "html"
    unrecognized = "unrecognized"


# Meta's own documented export categories for message threads (used broadly by
# third-party Facebook/Instagram export parsers) — `inbox` is the common case,
# the other three hold pending/hidden/archived threads. Not derived from any
# real export; kept as the single source of truth `instagram/export_reader.py`
# imports, so "raw ZIP scan" and "parsed" counts stay in sync (M10).
KNOWN_MESSAGE_CATEGORIES = ("inbox", "message_requests", "filtered_threads", "archived_threads")

# Matches both layouts: `your_instagram_activity/messages/<category>/<thread>/message_N.json`
# (current) and `messages/<category>/<thread>/message_N.json` (legacy).
MESSAGE_JSON_RE = re.compile(
    rf"(?:^|/)messages/(?:{'|'.join(KNOWN_MESSAGE_CATEGORIES)})/[^/]+/message_\d+\.json$"
)
# Broader match used only to detect message-shaped JSON under an *unrecognized*
# messages/<category>/ directory — so a future/unknown Meta category is
# counted, never silently dropped (M10).
ANY_MESSAGE_JSON_RE = re.compile(r"(?:^|/)messages/([^/]+)/[^/]+/message_\d+\.json$")
_HTML_RE = re.compile(r"\.html?$", re.IGNORECASE)


def _normalized(name: str) -> str:
    return name.replace("\\", "/")


def detect_export_format(entry_names: Iterable[str]) -> ExportKind:
    saw_html = False
    for name in entry_names:
        normalized = _normalized(name)
        if MESSAGE_JSON_RE.search(normalized):
            return ExportKind.json
        if _HTML_RE.search(normalized):
            saw_html = True
    return ExportKind.html if saw_html else ExportKind.unrecognized


def count_message_json_files(entry_names: Iterable[str]) -> int:
    return sum(1 for name in entry_names if MESSAGE_JSON_RE.search(_normalized(name)))
