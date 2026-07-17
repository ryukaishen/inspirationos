"""Mojibake repair for Instagram-export strings.

Instagram's JSON exports store UTF-8 bytes reinterpreted as latin-1 code
points (e.g. an emoji arrives as ``\\u00f0\\u009f\\u0098\\u008a``). Reversing
that — encode back to latin-1 bytes, decode as UTF-8 — restores the original
text.

The round-trip is **strict** with a fallback to the input, not ``'ignore'``:
strings that are already correct Unicode fail the latin-1 encode (or the
UTF-8 decode) and are returned unchanged, whereas ``'ignore'`` would silently
delete characters from them.
"""

from __future__ import annotations


def fix_mojibake(value: str) -> str:
    try:
        return value.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value


def fix_optional(value: str | None) -> str | None:
    return None if value is None else fix_mojibake(value)
