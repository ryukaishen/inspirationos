"""Streamed export reading: layout variants, pagination, tolerance, mojibake."""

import zipfile
from pathlib import Path

from fixture_builder import (
    FRIEND_NAME,
    OWNER_NAME,
    RICH_FRIEND_MESSAGE_COUNT,
    RICH_FRIEND_THREAD_PATH,
    RICH_FRIEND_TITLE,
    RICH_MOJIBAKE_NOTE,
    RICH_SELF_THREAD_PATH,
    RICH_SHARE_TEXT,
    build_rich_export_zip,
)

from app.services.ingest.instagram.export_reader import (
    ParsedThread,
    iter_threads,
    read_owner_name,
    thread_entries,
)


def _threads(path: Path) -> list[ParsedThread]:
    with zipfile.ZipFile(path) as archive:
        return list(iter_threads(archive))


def test_variant_a_and_b_parse_identically(tmp_path: Path) -> None:
    variant_a = _threads(build_rich_export_zip(tmp_path / "a.zip", variant="a"))
    variant_b = _threads(build_rich_export_zip(tmp_path / "b.zip", variant="b"))
    assert variant_a == variant_b  # frozen dataclasses compare by value


def test_paginated_thread_merges_ascending(tmp_path: Path) -> None:
    threads = {t.thread_path: t for t in _threads(build_rich_export_zip(tmp_path / "a.zip"))}
    friend = threads[RICH_FRIEND_THREAD_PATH]
    stamps = [message.timestamp_ms for message in friend.messages]
    assert stamps == sorted(stamps)
    assert len(friend.messages) == RICH_FRIEND_MESSAGE_COUNT


def test_thread_entries_maps_pages(tmp_path: Path) -> None:
    with zipfile.ZipFile(build_rich_export_zip(tmp_path / "a.zip")) as archive:
        entries = thread_entries(archive)
    assert set(entries) == {RICH_FRIEND_THREAD_PATH, RICH_SELF_THREAD_PATH}
    assert [page for page, _ in entries[RICH_FRIEND_THREAD_PATH]] == [1, 2]


def test_mojibake_fixed_everywhere(tmp_path: Path) -> None:
    threads = {t.thread_path: t for t in _threads(build_rich_export_zip(tmp_path / "a.zip"))}
    friend = threads[RICH_FRIEND_THREAD_PATH]
    assert friend.title == RICH_FRIEND_TITLE
    assert friend.participant_names == (OWNER_NAME, FRIEND_NAME)
    assert friend.messages[0].content == RICH_MOJIBAKE_NOTE
    share_texts = [m.share_text for m in friend.messages if m.share_text]
    assert RICH_SHARE_TEXT in share_texts


def test_media_only_and_unsent_messages_tolerated(tmp_path: Path) -> None:
    threads = {t.thread_path: t for t in _threads(build_rich_export_zip(tmp_path / "a.zip"))}
    friend = threads[RICH_FRIEND_THREAD_PATH]
    quiet = [m for m in friend.messages if m.content is None and m.share_link is None]
    assert len(quiet) == 2  # the media-only and the unsent message


def test_owner_name_read_from_personal_information(tmp_path: Path) -> None:
    with zipfile.ZipFile(build_rich_export_zip(tmp_path / "a.zip")) as archive:
        assert read_owner_name(archive) == OWNER_NAME


def test_owner_name_missing_returns_none(tmp_path: Path) -> None:
    path = build_rich_export_zip(tmp_path / "a.zip", include_personal_info=False)
    with zipfile.ZipFile(path) as archive:
        assert read_owner_name(archive) is None
