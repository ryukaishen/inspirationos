"""HttpEnrichmentFetcher: oEmbed/OpenGraph parsing and retry/backoff.

Entirely mocked via respx — no real network calls, and a no-op `sleep` is
injected so the retry-schedule tests run instantly instead of actually
waiting.
"""

import httpx
import respx

from app.services.enrichment.fetcher import HttpEnrichmentFetcher

OEMBED_URL = "https://api.instagram.com/oembed/"
PAGE_URL = "https://www.instagram.com/reel/ABC123/"


def _fetcher(**overrides: object) -> HttpEnrichmentFetcher:
    defaults: dict[str, object] = {
        "timeout_seconds": 5.0,
        "user_agent": "test-agent",
        "sleep": lambda _seconds: None,
    }
    defaults.update(overrides)
    return HttpEnrichmentFetcher(**defaults)  # type: ignore[arg-type]


@respx.mock
def test_fetch_oembed_parses_json_success() -> None:
    respx.get(OEMBED_URL).mock(
        return_value=httpx.Response(200, json={"title": "A caption", "author_name": "someone"})
    )
    result = _fetcher().fetch_oembed(PAGE_URL)
    assert result.http_status == 200
    assert result.title == "A caption"
    assert result.author == "someone"
    assert result.exc is None


@respx.mock
def test_fetch_oembed_not_found() -> None:
    respx.get(OEMBED_URL).mock(return_value=httpx.Response(404))
    result = _fetcher().fetch_oembed(PAGE_URL)
    assert result.http_status == 404
    assert result.exc is None


@respx.mock
def test_fetch_og_parses_meta_tags() -> None:
    html = (
        "<html><head>"
        '<meta property="og:title" content="A reel title">'
        '<meta property="og:description" content="A caption from OG">'
        "</head></html>"
    )
    respx.get(PAGE_URL).mock(return_value=httpx.Response(200, html=html))
    result = _fetcher().fetch_og(PAGE_URL)
    assert result.title == "A reel title"
    assert result.caption == "A caption from OG"


@respx.mock
def test_transient_errors_retry_the_full_schedule_then_classify_as_error() -> None:
    route = respx.get(PAGE_URL).mock(side_effect=httpx.ConnectError("boom"))
    result = _fetcher(retry_delays=(0.0, 0.0, 0.0)).fetch_og(PAGE_URL)
    assert result.http_status is None
    assert isinstance(result.exc, httpx.ConnectError)
    assert route.call_count == 3


@respx.mock
def test_succeeds_on_a_later_retry_without_exhausting_the_schedule() -> None:
    route = respx.get(PAGE_URL).mock(
        side_effect=[httpx.ConnectError("boom"), httpx.Response(200, html="<html></html>")]
    )
    result = _fetcher(retry_delays=(0.0, 0.0, 0.0)).fetch_og(PAGE_URL)
    assert result.http_status == 200
    assert route.call_count == 2


@respx.mock
def test_a_final_http_response_is_never_retried() -> None:
    """A definitive block (403) is not a transport error — one attempt only."""
    route = respx.get(PAGE_URL).mock(return_value=httpx.Response(403))
    result = _fetcher(retry_delays=(0.0, 0.0, 0.0)).fetch_og(PAGE_URL)
    assert result.http_status == 403
    assert route.call_count == 1
