"""URL extraction, canonicalization, shortcode parsing, type classification."""

from app.models.item import ItemType
from app.services.ingest.instagram.links import canonicalize, extract_urls

REEL = "https://www.instagram.com/reel/SYNTHAAA111/"


class TestExtractUrls:
    def test_finds_multiple_urls_in_order(self) -> None:
        content = "see https://a.example/one and http://b.example/two now"
        assert extract_urls(content) == ["https://a.example/one", "http://b.example/two"]

    def test_strips_trailing_punctuation(self) -> None:
        assert extract_urls("look (https://a.example/x), ok?") == ["https://a.example/x"]

    def test_keeps_trailing_slash(self) -> None:
        assert extract_urls(f"note about {REEL}") == [REEL]

    def test_no_urls(self) -> None:
        assert extract_urls("no links in this synthetic text") == []


class TestInstagramCanonicalization:
    def test_reel(self) -> None:
        link = canonicalize(REEL)
        assert link.url_canonical == REEL
        assert link.shortcode == "SYNTHAAA111"
        assert link.item_type is ItemType.reel

    def test_reels_path_maps_to_reel(self) -> None:
        link = canonicalize("https://www.instagram.com/reels/SYNTHAAA111/")
        assert link.url_canonical == REEL
        assert link.item_type is ItemType.reel

    def test_post(self) -> None:
        link = canonicalize("https://www.instagram.com/p/SYNTHBBB222/")
        assert link.url_canonical == "https://www.instagram.com/p/SYNTHBBB222/"
        assert link.shortcode == "SYNTHBBB222"
        assert link.item_type is ItemType.post

    def test_tv(self) -> None:
        link = canonicalize("https://www.instagram.com/tv/SYNTHDDD444/")
        assert link.item_type is ItemType.tv
        assert link.shortcode == "SYNTHDDD444"

    def test_tracking_params_collapse_to_same_canonical(self) -> None:
        variant = canonicalize(f"{REEL}?igsh=synthtrack&utm_source=synthetic&si=x")
        assert variant.url_canonical == canonicalize(REEL).url_canonical
        assert variant.url_raw == f"{REEL}?igsh=synthtrack&utm_source=synthetic&si=x"

    def test_host_case_and_missing_trailing_slash(self) -> None:
        link = canonicalize("https://WWW.Instagram.COM/reel/SYNTHAAA111")
        assert link.url_canonical == REEL

    def test_mobile_subdomain(self) -> None:
        link = canonicalize("https://m.instagram.com/p/SYNTHBBB222/")
        assert link.item_type is ItemType.post
        assert link.url_canonical == "https://www.instagram.com/p/SYNTHBBB222/"

    def test_short_domain(self) -> None:
        link = canonicalize("https://instagr.am/p/SYNTHBBB222/")
        assert link.item_type is ItemType.post
        assert link.shortcode == "SYNTHBBB222"

    def test_story_has_no_shortcode(self) -> None:
        link = canonicalize("https://www.instagram.com/stories/synthuser/123456/?igsh=x")
        assert link.item_type is ItemType.story
        assert link.shortcode is None
        assert link.url_canonical == "https://www.instagram.com/stories/synthuser/123456/"

    def test_unrecognized_instagram_path_is_unknown(self) -> None:
        link = canonicalize("https://www.instagram.com/synthuser/?igsh=x")
        assert link.item_type is ItemType.unknown
        assert link.shortcode is None
        assert link.url_canonical == "https://www.instagram.com/synthuser/"


class TestExternalCanonicalization:
    def test_external_type_and_tracking_strip(self) -> None:
        link = canonicalize("https://Example.com/Path?utm_source=a&id=42&si=b#frag")
        assert link.item_type is ItemType.external
        assert link.shortcode is None
        assert link.url_canonical == "https://example.com/Path?id=42"

    def test_external_keeps_meaningful_params(self) -> None:
        link = canonicalize("https://youtube.example/watch?v=synth123")
        assert link.url_canonical == "https://youtube.example/watch?v=synth123"

    def test_external_igshid_stripped(self) -> None:
        link = canonicalize("https://example.com/a?igshid=xyz")
        assert link.url_canonical == "https://example.com/a"
