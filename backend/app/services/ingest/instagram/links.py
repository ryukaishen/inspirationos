"""Link extraction, canonicalization, shortcode parsing, and type classification.

Canonical forms make exact-duplicate detection work across share variants:
tracking parameters (``igsh``, ``igshid``, ``si``, ``utm_*``) are stripped,
hosts are lowercased, fragments dropped. Instagram reel/post/tv URLs collapse
to ``https://www.instagram.com/<kind>/<shortcode>/`` regardless of how they
were shared.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.models.item import ItemType

URL_RE = re.compile(r"https?://\S+")
_TRAILING_PUNCTUATION = ".,;:!?)\"'>]}"

_TRACKING_PARAMS = frozenset({"igsh", "igshid", "si"})
_TRACKING_PREFIXES = ("utm_",)

# /reel/{code}, /reels/{code}, /p/{code}, /tv/{code} — shortcode is the
# URL-safe base64 alphabet Instagram uses.
_SHORTCODE_PATH_RE = re.compile(r"^/(reel|reels|p|tv)/([A-Za-z0-9_-]+)")
_STORY_PATH_RE = re.compile(r"^/stories/")

_KIND_TO_TYPE = {
    "reel": ItemType.reel,
    "reels": ItemType.reel,
    "p": ItemType.post,
    "tv": ItemType.tv,
}
_KIND_TO_CANONICAL = {"reel": "reel", "reels": "reel", "p": "p", "tv": "tv"}


@dataclass(frozen=True)
class CanonicalLink:
    url_raw: str
    url_canonical: str
    shortcode: str | None
    item_type: ItemType


def extract_urls(content: str) -> list[str]:
    """All http(s) URLs inside free text, trailing punctuation trimmed."""
    return [match.rstrip(_TRAILING_PUNCTUATION) for match in URL_RE.findall(content)]


def _is_tracking_param(name: str) -> bool:
    return name.lower() in _TRACKING_PARAMS or name.lower().startswith(_TRACKING_PREFIXES)


def _is_instagram_host(host: str) -> bool:
    return (
        host in ("instagram.com", "instagr.am")
        or host.endswith(".instagram.com")
        or host.endswith(".instagr.am")
    )


def canonicalize(url: str) -> CanonicalLink:
    parts = urlsplit(url)
    host = parts.netloc.lower()

    if _is_instagram_host(host):
        match = _SHORTCODE_PATH_RE.match(parts.path)
        if match:
            kind, shortcode = match.groups()
            canonical = f"https://www.instagram.com/{_KIND_TO_CANONICAL[kind]}/{shortcode}/"
            return CanonicalLink(url, canonical, shortcode, _KIND_TO_TYPE[kind])
        item_type = ItemType.story if _STORY_PATH_RE.match(parts.path) else ItemType.unknown
        # No shortcode to normalize on — keep the path, drop query/fragment
        # (Instagram query params are tracking noise).
        canonical = urlunsplit(("https", "www.instagram.com", parts.path, "", ""))
        return CanonicalLink(url, canonical, None, item_type)

    query = urlencode(
        [(name, value) for name, value in parse_qsl(parts.query) if not _is_tracking_param(name)]
    )
    canonical = urlunsplit((parts.scheme.lower(), host, parts.path, query, ""))
    return CanonicalLink(url, canonical, None, ItemType.external)
