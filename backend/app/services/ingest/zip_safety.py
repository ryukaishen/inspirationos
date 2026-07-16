"""Validation of untrusted uploaded ZIPs.

Reads **central-directory metadata only** — the archive is never extracted and
no entry contents are decompressed here. Error messages are static strings,
safe to return to the client and to store (they can never contain message
content or user data).
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path


class ZipRejectedError(Exception):
    """Base class for archive rejections; `code` is a stable, machine-readable slug."""

    code = "zip_rejected"


class NotAZipError(ZipRejectedError):
    code = "not_a_zip"


class ZipSlipError(ZipRejectedError):
    code = "zip_slip"


class ZipBombError(ZipRejectedError):
    code = "zip_bomb"


@dataclass(frozen=True)
class ZipLimits:
    max_entries: int
    max_total_uncompressed_bytes: int
    max_compression_ratio: int
    # Tiny entries have noisy ratios; only entries at least this large are checked.
    ratio_check_min_bytes: int = 1_048_576


@dataclass(frozen=True)
class ZipReport:
    entry_count: int
    total_uncompressed_bytes: int
    entry_names: tuple[str, ...]


_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")
_SEPARATORS = re.compile(r"[/\\]")


def is_unsafe_entry_name(name: str) -> bool:
    """True for absolute paths, drive-letter paths, or `..` traversal (any separator)."""
    if name.startswith(("/", "\\")):
        return True
    if _DRIVE_PREFIX.match(name):
        return True
    return ".." in _SEPARATORS.split(name)


def validate_zip(path: Path, limits: ZipLimits) -> ZipReport:
    """Validate the archive at `path` against slip/bomb attacks.

    Raises a `ZipRejectedError` subclass on any violation; returns a report of
    central-directory metadata otherwise.
    """
    try:
        archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, zipfile.LargeZipFile, EOFError, ValueError) as exc:
        raise NotAZipError("file is not a valid ZIP archive") from exc
    with archive:
        infos = archive.infolist()
        if len(infos) > limits.max_entries:
            raise ZipBombError("archive rejected: too many entries")
        total_uncompressed = 0
        for info in infos:
            if is_unsafe_entry_name(info.filename):
                raise ZipSlipError("archive rejected: unsafe entry path")
            total_uncompressed += info.file_size
            if (
                info.file_size >= limits.ratio_check_min_bytes
                and info.file_size / max(info.compress_size, 1) > limits.max_compression_ratio
            ):
                raise ZipBombError("archive rejected: suspicious compression ratio")
        if total_uncompressed > limits.max_total_uncompressed_bytes:
            raise ZipBombError("archive rejected: declared uncompressed size too large")
    return ZipReport(
        entry_count=len(infos),
        total_uncompressed_bytes=total_uncompressed,
        entry_names=tuple(info.filename for info in infos),
    )
