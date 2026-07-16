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


# Matches both layouts: `your_instagram_activity/messages/inbox/<thread>/message_N.json`
# (current) and `messages/inbox/<thread>/message_N.json` (legacy).
MESSAGE_JSON_RE = re.compile(r"(?:^|/)messages/inbox/[^/]+/message_\d+\.json$")
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
