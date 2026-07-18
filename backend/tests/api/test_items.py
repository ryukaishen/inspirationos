"""Items API: listing/pagination, filters, full-text search, duplicate-group
collapsing, and status/tag/note editing (single + bulk).

Uses the root conftest's `client`/`db_session` fixtures directly (real
Postgres, per-test savepoint) — no ZIP/worker pipeline needed here, since
these tests only need `Item` rows to already exist. Rows are seeded straight
through the ORM, following the same pattern as `tests/api/test_jobs.py`.

`GET /api/items` is a global, unscoped listing — this suite runs against the
same persistent dev-stack Postgres a developer also uses for manual
verification, which may already hold unrelated items. Every test that
asserts a `total`/count therefore scopes its query with a per-invocation
random tag marker (`MARKER`, applied to every seeded item) rather than
assuming the table starts empty; `conversation_id`/date-range/search-text
assertions are naturally collision-proof since they target freshly created,
auto-incremented or distinctive values.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.conversation import Conversation
from app.models.import_ import ExportFormat, Import, ImportStatus
from app.models.item import DuplicateGroup, DuplicateReason, Item, ItemStatus, ItemType

pytestmark = pytest.mark.integration

DAY1 = datetime(2026, 1, 1, tzinfo=UTC)
DAY2 = datetime(2026, 1, 2, tzinfo=UTC)
DAY2_PLUS_1H = datetime(2026, 1, 2, 1, tzinfo=UTC)
DAY2_PLUS_2H = datetime(2026, 1, 2, 2, tzinfo=UTC)
DAY3 = datetime(2026, 1, 3, tzinfo=UTC)
DAY5 = datetime(2026, 1, 5, tzinfo=UTC)
DAY10 = datetime(2026, 1, 10, tzinfo=UTC)

DISTINCTIVE_TEXT = "distinctive marker text zebra"


class Seeded:
    def __init__(
        self,
        conv_friend_id: int,
        conv_other_id: int,
        item_ids: dict[str, int],
        marker: str,
    ) -> None:
        self.conv_friend_id = conv_friend_id
        self.conv_other_id = conv_other_id
        self.item_ids = item_ids  # name -> id
        self.marker = marker  # unique per-run tag stamped on every seeded item
        self.fun_tag = f"{marker}-fun"
        self.travel_tag = f"{marker}-travel"
        self.work_tag = f"{marker}-work"
        self.dup_tag = f"{marker}-dup"
        self.archive_tag = f"{marker}-archive"


@pytest.fixture
def seeded(db_session: Session) -> Seeded:
    marker = uuid4().hex[:12]
    fun_tag = f"{marker}-fun"
    travel_tag = f"{marker}-travel"
    work_tag = f"{marker}-work"
    dup_tag = f"{marker}-dup"
    archive_tag = f"{marker}-archive"

    import_row = Import(
        filename="rich.zip",
        storage_key=None,
        size_bytes=1,
        checksum_sha256=uuid4().hex + uuid4().hex,
        export_format=ExportFormat.json,
        status=ImportStatus.extracted,
    )
    db_session.add(import_row)
    db_session.flush()

    conv_friend = Conversation(
        import_id=import_row.id,
        thread_path="inbox/friend",
        title="Friend",
        participant_names=["Owner", "Friend"],
        message_count=5,
        link_count=3,
        is_self_dm_candidate=False,
        is_selected=True,
    )
    conv_other = Conversation(
        import_id=import_row.id,
        thread_path="inbox/other",
        title="Other",
        participant_names=["Owner", "Other"],
        message_count=4,
        link_count=3,
        is_self_dm_candidate=False,
        is_selected=True,
    )
    db_session.add_all([conv_friend, conv_other])
    db_session.flush()

    reel_new = Item(
        conversation_id=conv_friend.id,
        url_raw="https://www.instagram.com/reel/ITEMAAA1/",
        url_canonical="https://www.instagram.com/reel/ITEMAAA1/",
        shortcode="ITEMAAA1",
        item_type=ItemType.reel,
        shared_at=DAY1,
        share_text="cool reel",
        adjacent_text=DISTINCTIVE_TEXT,
        status=ItemStatus.new,
        tags=[marker, fun_tag, travel_tag],
    )
    post_reviewed = Item(
        conversation_id=conv_friend.id,
        url_raw="https://www.instagram.com/p/ITEMBBB2/",
        url_canonical="https://www.instagram.com/p/ITEMBBB2/",
        shortcode="ITEMBBB2",
        item_type=ItemType.post,
        shared_at=DAY5,
        share_text="a post",
        status=ItemStatus.reviewed,
        tags=[marker, work_tag],
    )
    external_needs_context = Item(
        conversation_id=conv_friend.id,
        url_raw="https://example.com/article",
        url_canonical="https://example.com/article",
        item_type=ItemType.external,
        shared_at=DAY3,
        status=ItemStatus.needs_context,
        tags=[marker],
    )
    story_archived = Item(
        conversation_id=conv_other.id,
        url_raw="https://www.instagram.com/stories/someone/1/",
        url_canonical="https://www.instagram.com/stories/someone/1/",
        item_type=ItemType.story,
        shared_at=DAY10,
        status=ItemStatus.archived,
        tags=[marker, archive_tag],
    )
    db_session.add_all([reel_new, post_reviewed, external_needs_context, story_archived])
    db_session.flush()

    # duplicate group: three shares of the same reel in the "other" conversation
    dup_canonical = Item(
        conversation_id=conv_other.id,
        url_raw="https://www.instagram.com/reel/ITEMCCC3/",
        url_canonical="https://www.instagram.com/reel/ITEMCCC3/",
        shortcode="ITEMCCC3",
        item_type=ItemType.reel,
        shared_at=DAY2,
        status=ItemStatus.new,
        tags=[marker, fun_tag, dup_tag],
    )
    db_session.add(dup_canonical)
    db_session.flush()

    dup_group = DuplicateGroup(
        canonical_item_id=dup_canonical.id, reason=DuplicateReason.same_shortcode
    )
    db_session.add(dup_group)
    db_session.flush()
    dup_canonical.duplicate_group_id = dup_group.id

    dup_member_2 = Item(
        conversation_id=conv_other.id,
        url_raw="https://www.instagram.com/reel/ITEMCCC3/",
        url_canonical="https://www.instagram.com/reel/ITEMCCC3/",
        shortcode="ITEMCCC3",
        item_type=ItemType.reel,
        shared_at=DAY2_PLUS_1H,
        status=ItemStatus.new,
        tags=[marker],
        duplicate_group_id=dup_group.id,
    )
    dup_member_3 = Item(
        conversation_id=conv_other.id,
        url_raw="https://www.instagram.com/reel/ITEMCCC3/",
        url_canonical="https://www.instagram.com/reel/ITEMCCC3/",
        shortcode="ITEMCCC3",
        item_type=ItemType.reel,
        shared_at=DAY2_PLUS_2H,
        status=ItemStatus.new,
        tags=[marker],
        duplicate_group_id=dup_group.id,
    )
    db_session.add_all([dup_member_2, dup_member_3])
    db_session.commit()

    return Seeded(
        conv_friend_id=conv_friend.id,
        conv_other_id=conv_other.id,
        item_ids={
            "reel_new": reel_new.id,
            "post_reviewed": post_reviewed.id,
            "external_needs_context": external_needs_context.id,
            "story_archived": story_archived.id,
            "dup_canonical": dup_canonical.id,
            "dup_member_2": dup_member_2.id,
            "dup_member_3": dup_member_3.id,
        },
        marker=marker,
    )


def _ids(entries: list[dict]) -> set[int]:
    return {entry["item"]["id"] for entry in entries}


def _entry(entries: list[dict], item_id: int) -> dict:
    return next(entry for entry in entries if entry["item"]["id"] == item_id)


# --- listing, pagination, grouping ------------------------------------------


def test_list_items_collapses_duplicate_group_to_one_entry(
    seeded: Seeded, client: TestClient
) -> None:
    response = client.get("/api/items", params={"tags": seeded.marker, "page_size": 50})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 5  # 7 rows, 3 duplicates collapse to 1
    entries = body["entries"]
    assert len(entries) == 5

    dup_ids = {seeded.item_ids["dup_member_2"], seeded.item_ids["dup_member_3"]}
    assert not dup_ids & _ids(entries)  # duplicate members never appear directly

    canonical_entry = _entry(entries, seeded.item_ids["dup_canonical"])
    assert canonical_entry["duplicate_count"] == 3

    standalone_entry = _entry(entries, seeded.item_ids["reel_new"])
    assert standalone_entry["duplicate_count"] == 1


def test_list_items_paginates(seeded: Seeded, client: TestClient) -> None:
    page1 = client.get(
        "/api/items", params={"tags": seeded.marker, "page": 1, "page_size": 2}
    ).json()
    page2 = client.get(
        "/api/items", params={"tags": seeded.marker, "page": 2, "page_size": 2}
    ).json()
    assert page1["total"] == page2["total"] == 5
    assert len(page1["entries"]) == 2
    assert len(page2["entries"]) == 2
    assert _ids(page1["entries"]).isdisjoint(_ids(page2["entries"]))


# --- filters -----------------------------------------------------------------


def test_status_filter_narrows_results(seeded: Seeded, client: TestClient) -> None:
    response = client.get(
        "/api/items", params={"tags": seeded.marker, "status": "new", "page_size": 50}
    )
    body = response.json()
    assert body["total"] == 2  # reel_new + dup_canonical (group's status)
    assert _ids(body["entries"]) == {seeded.item_ids["reel_new"], seeded.item_ids["dup_canonical"]}


def test_item_type_filter_narrows_results(seeded: Seeded, client: TestClient) -> None:
    response = client.get(
        "/api/items", params={"tags": seeded.marker, "item_type": "reel", "page_size": 50}
    )
    body = response.json()
    assert body["total"] == 2
    assert _ids(body["entries"]) == {seeded.item_ids["reel_new"], seeded.item_ids["dup_canonical"]}


def test_tags_filter_narrows_results(seeded: Seeded, client: TestClient) -> None:
    response = client.get("/api/items", params={"tags": seeded.fun_tag, "page_size": 50})
    body = response.json()
    assert body["total"] == 2
    assert _ids(body["entries"]) == {seeded.item_ids["reel_new"], seeded.item_ids["dup_canonical"]}


def test_conversation_filter_narrows_results(seeded: Seeded, client: TestClient) -> None:
    response = client.get(
        "/api/items", params={"conversation_id": seeded.conv_friend_id, "page_size": 50}
    )
    body = response.json()
    assert body["total"] == 3
    assert _ids(body["entries"]) == {
        seeded.item_ids["reel_new"],
        seeded.item_ids["post_reviewed"],
        seeded.item_ids["external_needs_context"],
    }


def test_date_range_filter_narrows_results(seeded: Seeded, client: TestClient) -> None:
    response = client.get(
        "/api/items",
        params={
            "date_from": DAY2.isoformat(),
            "date_to": DAY3.isoformat(),
            "page_size": 50,
        },
    )
    body = response.json()
    assert body["total"] == 2
    assert _ids(body["entries"]) == {
        seeded.item_ids["dup_canonical"],
        seeded.item_ids["external_needs_context"],
    }


def test_search_finds_item_by_adjacent_text(seeded: Seeded, client: TestClient) -> None:
    response = client.get("/api/items", params={"search": "zebra", "page_size": 50})
    body = response.json()
    assert body["total"] == 1
    assert _ids(body["entries"]) == {seeded.item_ids["reel_new"]}


def test_search_excludes_items_without_a_match(seeded: Seeded, client: TestClient) -> None:
    response = client.get("/api/items", params={"search": "nonexistentword", "page_size": 50})
    body = response.json()
    assert body["total"] == 0
    assert body["entries"] == []


# --- facets -------------------------------------------------------------------


def test_facets_reflect_canonical_items_only(seeded: Seeded, client: TestClient) -> None:
    response = client.get("/api/items/facets")
    assert response.status_code == 200
    body = response.json()

    by_conv = {row["id"]: row["item_count"] for row in body["conversations"]}
    assert by_conv[seeded.conv_friend_id] == 3
    assert by_conv[seeded.conv_other_id] == 2  # dup_canonical (collapsed) + story_archived

    tag_counts = {row["tag"]: row["item_count"] for row in body["tags"]}
    assert tag_counts[seeded.fun_tag] == 2  # reel_new + dup_canonical
    assert tag_counts[seeded.archive_tag] == 1


# --- single-item update --------------------------------------------------------


def test_patch_persists_status_tags_and_note(seeded: Seeded, client: TestClient) -> None:
    item_id = seeded.item_ids["reel_new"]
    response = client.patch(
        f"/api/items/{item_id}",
        json={"status": "reviewed", "tags": ["updated"], "context_note": "my note"},
    )
    assert response.status_code == 200
    updated = response.json()
    assert updated["status"] == "reviewed"
    assert updated["tags"] == ["updated"]
    assert updated["context_note"] == "my note"

    # persistence through a fresh request, not just the mutation's own response.
    # Scoped by conversation (not the tag marker): the PATCH just replaced this
    # item's tags entirely, so it no longer carries the marker tag.
    listing = client.get(
        "/api/items", params={"conversation_id": seeded.conv_friend_id, "page_size": 50}
    ).json()
    persisted = _entry(listing["entries"], item_id)["item"]
    assert persisted["status"] == "reviewed"
    assert persisted["tags"] == ["updated"]
    assert persisted["context_note"] == "my note"


def test_patch_partial_update_leaves_other_fields_untouched(
    seeded: Seeded, client: TestClient
) -> None:
    item_id = seeded.item_ids["post_reviewed"]
    response = client.patch(f"/api/items/{item_id}", json={"status": "archived"})
    assert response.status_code == 200
    updated = response.json()
    assert updated["status"] == "archived"
    # untouched — not present in the request body
    assert set(updated["tags"]) == {seeded.marker, seeded.work_tag}


def test_patch_missing_item_returns_404(client: TestClient) -> None:
    response = client.patch("/api/items/999999999", json={"status": "archived"})
    assert response.status_code == 404


# --- bulk update ----------------------------------------------------------------


def test_bulk_status_update_persists_across_selection(seeded: Seeded, client: TestClient) -> None:
    ids = [seeded.item_ids["reel_new"], seeded.item_ids["post_reviewed"]]
    response = client.post("/api/items/bulk", json={"item_ids": ids, "status": "archived"})
    assert response.status_code == 200
    assert response.json()["updated"] == 2

    listing = client.get("/api/items", params={"tags": seeded.marker, "page_size": 50}).json()
    for item_id in ids:
        assert _entry(listing["entries"], item_id)["item"]["status"] == "archived"


def test_bulk_add_tags_unions_without_duplicates(seeded: Seeded, client: TestClient) -> None:
    item_id = seeded.item_ids["reel_new"]  # already tagged [marker, fun_tag, travel_tag]
    response = client.post(
        "/api/items/bulk", json={"item_ids": [item_id], "add_tags": [seeded.fun_tag, "new-tag"]}
    )
    assert response.status_code == 200
    listing = client.get("/api/items", params={"tags": seeded.marker, "page_size": 50}).json()
    tags = _entry(listing["entries"], item_id)["item"]["tags"]
    assert set(tags) == {seeded.marker, seeded.fun_tag, seeded.travel_tag, "new-tag"}


def test_bulk_requires_status_or_add_tags(seeded: Seeded, client: TestClient) -> None:
    response = client.post("/api/items/bulk", json={"item_ids": [seeded.item_ids["reel_new"]]})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "no_op"


def test_bulk_ignores_nonexistent_ids(seeded: Seeded, client: TestClient) -> None:
    real_id = seeded.item_ids["reel_new"]
    response = client.post(
        "/api/items/bulk", json={"item_ids": [real_id, 999999999], "status": "ignored"}
    )
    assert response.status_code == 200
    assert response.json()["updated"] == 1  # the bogus id was silently skipped

    listing = client.get("/api/items", params={"tags": seeded.marker, "page_size": 50}).json()
    assert _entry(listing["entries"], real_id)["item"]["status"] == "ignored"
