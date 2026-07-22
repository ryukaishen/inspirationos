"""Unit tests for the log-redaction filter (M9) — no services needed.

See tests/workers/test_log_redaction_pipeline.py for the full-pipeline
integration test asserting real fixture strings never reach a log record.
"""

import logging

from app.services.privacy.log_filter import (
    REDACTED_PLACEHOLDER,
    RedactingFilter,
    install_redacting_filter,
)


def _record(msg: str, **extra: str) -> logging.LogRecord:
    record = logging.LogRecord(
        name="app.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=(),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_strips_named_extra_attributes() -> None:
    record = _record("processed item", share_text="a private caption", item_id=42)
    RedactingFilter().filter(record)
    assert record.share_text == REDACTED_PLACEHOLDER  # type: ignore[attr-defined]
    assert record.item_id == 42  # type: ignore[attr-defined] — non-sensitive fields untouched


def test_redacts_field_value_substrings_in_the_message() -> None:
    record = _record("debug: share_text='a private caption' item_id=42")
    RedactingFilter().filter(record)
    assert "a private caption" not in record.getMessage()
    assert f"share_text={REDACTED_PLACEHOLDER}" in record.getMessage()
    assert "item_id=42" in record.getMessage()


def test_leaves_ordinary_messages_untouched() -> None:
    record = _record("job %s succeeded")
    record.args = ("42",)
    original = record.getMessage()
    RedactingFilter().filter(record)
    assert record.getMessage() == original


def test_filter_always_returns_true_never_drops_the_record() -> None:
    record = _record("anything")
    assert RedactingFilter().filter(record) is True


def test_install_redacting_filter_is_idempotent() -> None:
    logger = logging.getLogger("app.test.install-idempotent")
    logger.filters.clear()
    install_redacting_filter(logger)
    install_redacting_filter(logger)
    assert sum(isinstance(f, RedactingFilter) for f in logger.filters) == 1
