"""Export-format detection over entry names — no services needed."""

import zipfile
from pathlib import Path

from fixture_builder import (
    VERIFICATION_MESSAGE_FILES,
    VERIFICATION_TOTAL_ENTRIES,
    build_empty_zip,
    build_html_export_zip,
    build_unrecognized_zip,
    build_variant_a_zip,
    build_variant_b_zip,
    build_verification_export_zip,
    build_zip_with_entry,
)

from app.services.ingest.format_detection import (
    ExportKind,
    count_message_json_files,
    detect_export_format,
)


def _names(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as archive:
        return archive.namelist()


def test_variant_a_detected_as_json(tmp_path: Path) -> None:
    names = _names(build_variant_a_zip(tmp_path / "a.zip"))
    assert detect_export_format(names) is ExportKind.json


def test_variant_b_detected_as_json(tmp_path: Path) -> None:
    names = _names(build_variant_b_zip(tmp_path / "b.zip"))
    assert detect_export_format(names) is ExportKind.json


def test_html_export_detected_as_html(tmp_path: Path) -> None:
    names = _names(build_html_export_zip(tmp_path / "html.zip"))
    assert detect_export_format(names) is ExportKind.html


def test_unrecognized_zip(tmp_path: Path) -> None:
    names = _names(build_unrecognized_zip(tmp_path / "other.zip"))
    assert detect_export_format(names) is ExportKind.unrecognized


def test_empty_zip_is_unrecognized(tmp_path: Path) -> None:
    names = _names(build_empty_zip(tmp_path / "empty.zip"))
    assert detect_export_format(names) is ExportKind.unrecognized


def test_count_message_json_files(tmp_path: Path) -> None:
    names = _names(build_variant_a_zip(tmp_path / "a.zip"))
    assert count_message_json_files(names) == 1
    assert count_message_json_files(["unrelated.txt"]) == 0


def test_backslash_separated_names_are_normalized() -> None:
    names = ["your_instagram_activity\\messages\\inbox\\t_1\\message_1.json"]
    assert detect_export_format(names) is ExportKind.json
    assert count_message_json_files(names) == 1


def test_known_non_inbox_categories_detected_as_json(tmp_path: Path) -> None:
    """M10: message_requests/filtered_threads/archived_threads count toward
    the same raw-vs-parsed accounting as inbox, not just inbox alone."""
    names = ["your_instagram_activity/messages/message_requests/t_1/message_1.json"]
    assert detect_export_format(names) is ExportKind.json
    assert count_message_json_files(names) == 1

    names = ["your_instagram_activity/messages/filtered_threads/t_1/message_1.json"]
    assert detect_export_format(names) is ExportKind.json
    assert count_message_json_files(names) == 1

    names = ["your_instagram_activity/messages/archived_threads/t_1/message_1.json"]
    assert detect_export_format(names) is ExportKind.json
    assert count_message_json_files(names) == 1


def test_unrecognized_category_alone_is_unrecognized(tmp_path: Path) -> None:
    """A message-shaped JSON path under a category we don't know about is
    *not* mistaken for a recognized export — M10's verification report is
    the place that surfaces it instead (never silently accepted or dropped)."""
    names = _names(
        build_zip_with_entry(
            tmp_path / "unknown_category.zip",
            "your_instagram_activity/messages/synthetic_unknown_category/t_1/message_1.json",
            data=b"{}",
        )
    )
    assert detect_export_format(names) is ExportKind.unrecognized
    assert count_message_json_files(names) == 0


def test_verification_fixture_counts(tmp_path: Path) -> None:
    names = _names(build_verification_export_zip(tmp_path / "verification.zip"))
    assert len(names) == VERIFICATION_TOTAL_ENTRIES
    assert count_message_json_files(names) == VERIFICATION_MESSAGE_FILES
