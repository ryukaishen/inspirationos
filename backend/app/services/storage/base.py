"""Storage abstraction — local filesystem now, S3-compatible later (same interface).

Keys are opaque, server-generated strings (never derived from user input).
"""

from __future__ import annotations

from pathlib import Path
from typing import BinaryIO, Protocol


class Storage(Protocol):
    def spool_dir(self) -> Path:
        """Local staging directory; files written here can be promoted via `save_file`."""
        ...

    def save_file(self, key: str, src: Path) -> None:
        """Move the local file `src` into storage under `key` (atomic on local FS)."""
        ...

    def open(self, key: str) -> BinaryIO:
        """Open the stored object for binary reading."""
        ...

    def exists(self, key: str) -> bool: ...

    def size(self, key: str) -> int: ...

    def delete(self, key: str) -> None:
        """Remove `key`; deleting a missing key is a no-op (idempotent)."""
        ...

    def clear(self) -> int:
        """Remove every stored file (used only by the complete-wipe job).
        Returns the number of files removed."""
        ...

    def count_files(self) -> int:
        """Number of files currently stored — the wipe report's post-check."""
        ...
