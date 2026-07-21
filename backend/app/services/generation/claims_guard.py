"""Fabricated-performance-claims guard (M8): a regex heuristic that flags
suspicious "already achieved" performance numbers in generated career
artifacts, for the user's attention — never a hard gate. Findings are stored
alongside the artifact (`artifacts.claims_flags`); generation never fails
because of a flag. Runs only on `content_md`, which is already AI-generated
text derived from the project's own stored fields — never raw message text.
"""

from __future__ import annotations

import re

_ACHIEVEMENT_VERBS = (
    "achiev",
    "reach",
    "attain",
    "deliver",
    "improv",
    "reduc",
    "increas",
    "boost",
    "outperform",
    "surpass",
    "obtain",
    "exceed",
)

_METRIC_WORDS = (
    "accuracy",
    "precision",
    "recall",
    "f1",
    "f1-score",
    "auc",
    "latency",
    "throughput",
    "speedup",
    "uptime",
    "coverage",
    "error rate",
    "rmse",
    "mae",
    "conversion",
    "engagement",
)

_HEDGE_WORDS = (
    "target",
    "goal",
    "aim",
    "estimate",
    "approximat",
    "roughly",
    "projected",
    "up to",
    "hope to",
    "plan to",
    "expect",
    "hypothetical",
)

_NUMBER = r"\d{1,3}(?:\.\d+)?\s?(?:%|percent|x|times)"
_ACHIEVEMENT_RE = re.compile(
    rf"\b(?:{'|'.join(_ACHIEVEMENT_VERBS)})\w*\b[^.\n]{{0,60}}?{_NUMBER}",
    re.IGNORECASE,
)
_METRIC_RE = re.compile(
    rf"\b\d{{1,3}}(?:\.\d+)?\s?%\s*(?:{'|'.join(_METRIC_WORDS)})\b",
    re.IGNORECASE,
)

_HEDGE_WINDOW_CHARS = 30


def _is_hedged(text: str, match_start: int) -> bool:
    window = text[max(0, match_start - _HEDGE_WINDOW_CHARS) : match_start].lower()
    return any(word in window for word in _HEDGE_WORDS)


def find_claims(text: str) -> list[str]:
    """Return deduplicated snippets that read as unverified, already-achieved
    performance claims (e.g. "achieved 97% accuracy"). Any match is skipped
    when a hedge word ("target", "goal", "aim", "estimate", "plan to", ...)
    appears shortly before it — a stated target or estimate is not a
    fabricated claim."""
    if not text:
        return []
    matches: list[str] = []
    for pattern in (_ACHIEVEMENT_RE, _METRIC_RE):
        for match in pattern.finditer(text):
            if _is_hedged(text, match.start()):
                continue
            snippet = " ".join(match.group(0).split())
            if snippet not in matches:
                matches.append(snippet)
    return matches
