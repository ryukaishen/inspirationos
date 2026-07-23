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
    VERIFICATION_CONVERSATIONS,
    VERIFICATION_MESSAGE_MISSING_FIELDS,
    VERIFICATION_MESSAGE_NOT_OBJECT,
    VERIFICATION_MESSAGES_PARSED,
    VERIFICATION_NON_DICT_PAGE_PAYLOAD,
    VERIFICATION_UNKNOWN_CATEGORY,
    VERIFICATION_UNRECOGNIZED_MESSAGE_PATH,
    build_rich_export_zip,
    build_verification_export_zip,
)

from app.services.ingest.instagram.export_reader import (
    ParsedThread,
    ScanIssues,
    iter_threads,
    read_owner_name,
    scan_unrecognized_message_paths,
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


# --- M10: skip categorization, nothing silent -------------------------------


def test_known_non_inbox_categories_parse_like_inbox(tmp_path: Path) -> None:
    """message_requests/filtered_threads threads parse and count exactly
    like inbox threads — not a special case (M10)."""
    with zipfile.ZipFile(build_verification_export_zip(tmp_path / "verification.zip")) as archive:
        threads = {t.thread_path: t for t in iter_threads(archive)}
    assert len(threads) == VERIFICATION_CONVERSATIONS
    requests_thread = next(t for path, t in threads.items() if path.startswith("message_requests/"))
    assert len(requests_thread.messages) == 1
    filtered_thread = next(t for path, t in threads.items() if path.startswith("filtered_threads/"))
    assert len(filtered_thread.messages) == 1


def test_scan_issues_categorize_every_skip(tmp_path: Path) -> None:
    """Every M10 skip category is counted exactly once by the fixture, and
    nothing is silently dropped."""
    with zipfile.ZipFile(build_verification_export_zip(tmp_path / "verification.zip")) as archive:
        issues = ScanIssues()
        scan_unrecognized_message_paths(archive.namelist(), issues)
        threads = list(iter_threads(archive, issues))

    assert sum(len(t.messages) for t in threads) == VERIFICATION_MESSAGES_PARSED
    assert issues.non_dict_page_payload == VERIFICATION_NON_DICT_PAGE_PAYLOAD
    assert issues.message_not_object == VERIFICATION_MESSAGE_NOT_OBJECT
    assert issues.message_missing_sender_or_timestamp == VERIFICATION_MESSAGE_MISSING_FIELDS
    assert issues.unrecognized_message_path == VERIFICATION_UNRECOGNIZED_MESSAGE_PATH
    assert issues.unrecognized_categories == {VERIFICATION_UNKNOWN_CATEGORY}
    assert issues.as_dict() == {
        "non_dict_page_payload": VERIFICATION_NON_DICT_PAGE_PAYLOAD,
        "message_not_object": VERIFICATION_MESSAGE_NOT_OBJECT,
        "message_missing_sender_or_timestamp": VERIFICATION_MESSAGE_MISSING_FIELDS,
        "unrecognized_message_path": VERIFICATION_UNRECOGNIZED_MESSAGE_PATH,
        "unrecognized_message_path_categories": [VERIFICATION_UNKNOWN_CATEGORY],
    }


def test_scan_issues_without_tracking_is_optional(tmp_path: Path) -> None:
    """`issues` stays optional — existing callers that don't pass one see no
    behavior change (backward compatible)."""
    with zipfile.ZipFile(build_verification_export_zip(tmp_path / "verification.zip")) as archive:
        threads = list(iter_threads(archive))
    assert sum(len(t.messages) for t in threads) == VERIFICATION_MESSAGES_PARSED
