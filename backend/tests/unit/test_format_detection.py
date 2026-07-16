"""Export-format detection over entry names — no services needed."""

import zipfile
from pathlib import Path

from fixture_builder import (
    build_empty_zip,
    build_html_export_zip,
    build_unrecognized_zip,
    build_variant_a_zip,
    build_variant_b_zip,
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
