"""Local-filesystem storage rooted at DATA_DIR (gitignored `var/data/`)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import BinaryIO


class LocalStorage:
    """Files live under a single root; the spool directory shares the same volume
    so `save_file` promotion via `os.replace` is atomic."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._spool = self._root / "tmp"
        self._spool.mkdir(parents=True, exist_ok=True)

    def _path_for(self, key: str) -> Path:
        # Keys are server-generated, but contain the resolved path anyway.
        # Backslashes are rejected outright: on POSIX they are literal filename
        # characters, so resolve() alone would not catch `..\` traversal there.
        if "\\" in key or ".." in key.split("/"):
            raise ValueError("storage key escapes the storage root")
        resolved = (self._root / key).resolve()
        if resolved == self._root or not resolved.is_relative_to(self._root):
            raise ValueError("storage key escapes the storage root")
        return resolved

    def spool_dir(self) -> Path:
        return self._spool

    def save_file(self, key: str, src: Path) -> None:
        dest = self._path_for(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.replace(src, dest)

    def open(self, key: str) -> BinaryIO:
        return self._path_for(key).open("rb")

    def exists(self, key: str) -> bool:
        return self._path_for(key).is_file()

    def size(self, key: str) -> int:
        return self._path_for(key).stat().st_size

    def delete(self, key: str) -> None:
        self._path_for(key).unlink(missing_ok=True)
