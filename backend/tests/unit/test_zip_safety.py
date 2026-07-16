"""Every archive rejection branch, plus the happy path — no services needed."""

from pathlib import Path

import pytest
from fixture_builder import (
    build_corrupted_zip,
    build_empty_zip,
    build_entry_count_bomb_zip,
    build_not_a_zip,
    build_ratio_bomb_zip,
    build_total_size_bomb_zip,
    build_variant_a_zip,
    build_variant_b_zip,
    build_zip_slip_zip,
)

from app.services.ingest.zip_safety import (
    NotAZipError,
    ZipBombError,
    ZipLimits,
    ZipSlipError,
    validate_zip,
)

LIMITS = ZipLimits(
    max_entries=100,
    max_total_uncompressed_bytes=32 * 1024 * 1024,
    max_compression_ratio=100,
)


def test_variant_a_passes_and_reports_metadata(tmp_path: Path) -> None:
    archive = build_variant_a_zip(tmp_path / "a.zip")
    report = validate_zip(archive, LIMITS)
    assert report.entry_count == 2
    assert report.total_uncompressed_bytes > 0
    assert any(name.endswith("message_1.json") for name in report.entry_names)


def test_variant_b_passes(tmp_path: Path) -> None:
    archive = build_variant_b_zip(tmp_path / "b.zip")
    report = validate_zip(archive, LIMITS)
    assert report.entry_count == 1


@pytest.mark.parametrize(
    "entry_name",
    [
        "../../evil.txt",  # posix traversal
        "..\\..\\evil.txt",  # windows-separator traversal
        "nested/../../evil.txt",  # traversal below the top level
        "/abs/evil.txt",  # absolute posix path
        "\\abs\\evil.txt",  # absolute windows path
        "C:\\evil.txt",  # drive-letter path
    ],
)
def test_zip_slip_entries_rejected(tmp_path: Path, entry_name: str) -> None:
    archive = build_zip_slip_zip(tmp_path / "slip.zip", entry_name=entry_name)
    with pytest.raises(ZipSlipError):
        validate_zip(archive, LIMITS)


def test_compression_ratio_bomb_rejected(tmp_path: Path) -> None:
    archive = build_ratio_bomb_zip(tmp_path / "ratio.zip", payload_bytes=2 * 1024 * 1024)
    with pytest.raises(ZipBombError):
        validate_zip(archive, LIMITS)


def test_entry_count_bomb_rejected(tmp_path: Path) -> None:
    archive = build_entry_count_bomb_zip(tmp_path / "entries.zip", entries=200)
    with pytest.raises(ZipBombError):
        validate_zip(archive, LIMITS)


def test_total_uncompressed_bomb_rejected(tmp_path: Path) -> None:
    # Entries below the per-entry ratio floor, so only the total-size cap can fire.
    limits = ZipLimits(
        max_entries=100,
        max_total_uncompressed_bytes=1024 * 1024,
        max_compression_ratio=100,
    )
    archive = build_total_size_bomb_zip(tmp_path / "total.zip", entries=4, entry_bytes=512 * 1024)
    with pytest.raises(ZipBombError):
        validate_zip(archive, limits)


def test_not_a_zip_rejected(tmp_path: Path) -> None:
    payload = build_not_a_zip(tmp_path / "garbage.zip")
    with pytest.raises(NotAZipError):
        validate_zip(payload, LIMITS)


def test_corrupted_central_directory_rejected(tmp_path: Path) -> None:
    archive = build_corrupted_zip(tmp_path / "corrupt.zip")
    with pytest.raises(NotAZipError):
        validate_zip(archive, LIMITS)


def test_empty_zip_passes_validation(tmp_path: Path) -> None:
    # An empty archive is structurally safe; it is rejected later by format
    # detection ("unrecognized"), not by the safety layer.
    archive = build_empty_zip(tmp_path / "empty.zip")
    report = validate_zip(archive, LIMITS)
    assert report.entry_count == 0
    assert report.entry_names == ()


def test_ratio_below_floor_is_not_flagged(tmp_path: Path) -> None:
    # A small all-zeros entry compresses extremely well but sits below the
    # ratio floor — it must not trip the bomb heuristic.
    archive = build_ratio_bomb_zip(tmp_path / "small.zip", payload_bytes=64 * 1024)
    report = validate_zip(archive, LIMITS)
    assert report.entry_count == 1
