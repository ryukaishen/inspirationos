"""Mojibake repair: strict latin-1→UTF-8 round-trip with safe fallback."""

from app.services.ingest.instagram.encoding import fix_mojibake, fix_optional


def test_repairs_mojibake_emoji() -> None:
    # UTF-8 bytes of 😊 (F0 9F 98 8A) stored as latin-1 code points
    assert fix_mojibake("ð") == "\U0001f60a"


def test_repairs_mojibake_accented_text() -> None:
    assert fix_mojibake("cafÃ©") == "café"


def test_matches_instagram_encoding_exactly() -> None:
    original = "emoji \U0001f60a and café"
    mojibake = original.encode("utf-8").decode("latin-1")
    assert fix_mojibake(mojibake) == original


def test_ascii_passthrough() -> None:
    assert fix_mojibake("plain synthetic text") == "plain synthetic text"


def test_already_correct_unicode_is_unchanged() -> None:
    # latin-1 encoding fails for the emoji — the fallback must not drop it,
    # which is why the round-trip is strict rather than errors="ignore"
    assert fix_mojibake("\U0001f60a café") == "\U0001f60a café"


def test_latin1_only_text_is_unchanged() -> None:
    # encodes to latin-1 fine but is not valid UTF-8 — fallback keeps it intact
    assert fix_mojibake("café") == "café"


def test_empty_string() -> None:
    assert fix_mojibake("") == ""


def test_fix_optional_passes_none_through() -> None:
    assert fix_optional(None) is None
    assert fix_optional("cafÃ©") == "café"
