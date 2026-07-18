"""oEmbed -> OpenGraph metadata fetcher.

Anonymous GETs only — no cookies, no headless browser, no login, no
CAPTCHA handling (see PRIVACY_SECURITY.md). Best-effort: Instagram blocks
anonymous access aggressively, so a low hit rate is expected and never
load-bearing for the rest of the app.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import httpx

OEMBED_ENDPOINT = "https://api.instagram.com/oembed/"

_OG_META_RE = re.compile(
    r"""<meta[^>]+property=["']og:(title|description)["'][^>]+content=["']([^"']*)["']""",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class FetchResult:
    """One completed (post-retry) fetch outcome, ready for classification."""

    http_status: int | None
    title: str | None = None
    caption: str | None = None
    author: str | None = None
    exc: Exception | None = None


@dataclass(frozen=True)
class _ParsedBody:
    title: str | None
    caption: str | None
    author: str | None


class EnrichmentFetcher(Protocol):
    def fetch_oembed(self, url: str) -> FetchResult: ...

    def fetch_og(self, url: str) -> FetchResult: ...


def _parse_body(response: httpx.Response) -> _ParsedBody:
    if response.status_code != 200:
        return _ParsedBody(title=None, caption=None, author=None)
    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            data = response.json()
        except ValueError:
            return _ParsedBody(title=None, caption=None, author=None)
        return _ParsedBody(title=data.get("title"), caption=None, author=data.get("author_name"))
    matches = dict(_OG_META_RE.findall(response.text))
    return _ParsedBody(title=matches.get("title"), caption=matches.get("description"), author=None)


class HttpEnrichmentFetcher:
    """Real fetcher: httpx client, timeouts, fixed backoff on transient
    (connect/timeout) errors. A definitive HTTP response — success, 404, or a
    block — is never retried, only transport-level failures are."""

    def __init__(
        self,
        *,
        timeout_seconds: float,
        user_agent: str,
        retry_delays: tuple[float, ...] = (0.0, 1.0, 2.0),
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._timeout = timeout_seconds
        self._headers = {"User-Agent": user_agent}
        self._retry_delays = retry_delays
        self._sleep = sleep

    def _get(self, url: str, params: dict[str, str] | None = None) -> FetchResult:
        last_exc: Exception | None = None
        with httpx.Client(timeout=self._timeout, headers=self._headers) as client:
            for delay in self._retry_delays:
                if delay:
                    self._sleep(delay)
                try:
                    response = client.get(url, params=params)
                except httpx.HTTPError as exc:
                    last_exc = exc
                    continue
                parsed = _parse_body(response)
                return FetchResult(
                    http_status=response.status_code,
                    title=parsed.title,
                    caption=parsed.caption,
                    author=parsed.author,
                )
        return FetchResult(http_status=None, exc=last_exc)

    def fetch_oembed(self, url: str) -> FetchResult:
        return self._get(OEMBED_ENDPOINT, params={"url": url})

    def fetch_og(self, url: str) -> FetchResult:
        return self._get(url)
