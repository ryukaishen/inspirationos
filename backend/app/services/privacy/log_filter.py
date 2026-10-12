"""Log redaction (M9, see PRIVACY_SECURITY.md): private message content —
`text`, `share_text`, `adjacent_text`, `context_note`, `content_md`,
`transcript`, `visual_text` — must never appear in logs. The codebase
already follows this by construction (exceptions carry only class names, job
payloads carry only IDs/counts — see ARCHITECTURE.md's job conventions), so
this filter is the defense-in-depth backstop for any future accidental leak,
not a workaround for an existing one.
"""

from __future__ import annotations

import logging
import re

REDACTED_FIELDS = (
    "text",
    "share_text",
    "adjacent_text",
    "context_note",
    "content_md",
    "transcript",
    "visual_text",
)
REDACTED_PLACEHOLDER = "[redacted]"

_FIELD_VALUE_PATTERN = re.compile(
    r"\b(" + "|".join(REDACTED_FIELDS) + r")\s*=\s*(?:'[^']*'|\"[^\"]*\"|\S+)"
)


class RedactingFilter(logging.Filter):
    """Two layers, both applied before a record reaches any handler:

    1. Named `extra=` attributes matching a redacted field name are replaced
       outright (e.g. `logger.info("...", extra={"share_text": item.share_text})`).
    2. `field=value`-shaped substrings in the rendered message are redacted
       by regex — catches an accidental f-string leak (`f"item {share_text=}"`)
       that the first layer, which only inspects structured `extra`, would miss.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        for field in REDACTED_FIELDS:
            if hasattr(record, field):
                setattr(record, field, REDACTED_PLACEHOLDER)

        message = record.getMessage()
        redacted = _FIELD_VALUE_PATTERN.sub(
            lambda match: f"{match.group(1)}={REDACTED_PLACEHOLDER}", message
        )
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


def install_redacting_filter(logger: logging.Logger | None = None) -> None:
    """Attaches the filter to a logger (root by default) exactly once —
    idempotent, so it's safe to call from both app and worker entrypoints
    without risking a double-redaction pass (redaction is itself idempotent,
    but this avoids doing the regex work twice per record)."""
    target = logger if logger is not None else logging.getLogger()
    if any(isinstance(existing, RedactingFilter) for existing in target.filters):
        return
    target.addFilter(RedactingFilter())
