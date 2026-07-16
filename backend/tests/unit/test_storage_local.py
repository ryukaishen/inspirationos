"""LocalStorage behavior — no services needed."""

from pathlib import Path

import pytest

from app.services.storage.local import LocalStorage


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path / "data")


def _spool_file(storage: LocalStorage, content: bytes) -> Path:
    src = storage.spool_dir() / "incoming.part"
    src.write_bytes(content)
    return src


def test_save_file_round_trip(storage: LocalStorage) -> None:
    src = _spool_file(storage, b"synthetic zip bytes")
    storage.save_file("imports/abc123.zip", src)

    assert not src.exists()  # promotion moves, never copies
    assert storage.exists("imports/abc123.zip")
    assert storage.size("imports/abc123.zip") == len(b"synthetic zip bytes")
    with storage.open("imports/abc123.zip") as fh:
        assert fh.read() == b"synthetic zip bytes"


def test_delete_removes_file_and_is_idempotent(storage: LocalStorage) -> None:
    src = _spool_file(storage, b"x")
    storage.save_file("imports/gone.zip", src)
    storage.delete("imports/gone.zip")
    assert not storage.exists("imports/gone.zip")
    # Deleting a missing key must be a no-op, not an error.
    storage.delete("imports/gone.zip")
    storage.delete("never/existed.zip")


@pytest.mark.parametrize("key", ["../escape.zip", "..\\escape.zip", "a/../../escape.zip", ""])
def test_keys_escaping_the_root_are_rejected(storage: LocalStorage, key: str) -> None:
    with pytest.raises(ValueError):
        storage.exists(key)


def test_spool_dir_lives_inside_the_root(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path / "data")
    assert storage.spool_dir().is_dir()
    assert storage.spool_dir().is_relative_to((tmp_path / "data").resolve())
