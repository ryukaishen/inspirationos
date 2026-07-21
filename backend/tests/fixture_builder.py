"""Synthetic Instagram-export ZIP builder — the only source of export-like test data.

Every string here is invented; no real export content may ever be added (see
docs/TESTING_STRATEGY.md). ZIPs are written at test time into temp directories
and are never committed (`*.zip` is gitignored).

Deliberately **stdlib-only** so the Playwright global setup can run this file
as a script on any host with a Python interpreter, without installing backend
dependencies:

    python backend/tests/fixture_builder.py --out e2e/.fixtures --unique 12345
"""

from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path
from typing import Any

OWNER_NAME = "Synthetic Owner"
FRIEND_NAME = "Synthetic Friend"
THREAD_DIR = "syntheticfriend_1234567890"
SELF_THREAD_DIR = "syntheticowner_9876543210"
REEL_URL = "https://www.instagram.com/reel/SYNTHAAA111/"
POST_URL = "https://www.instagram.com/p/SYNTHBBB222/"

VARIANT_A_MESSAGES_PREFIX = "your_instagram_activity/messages"
VARIANT_B_MESSAGES_PREFIX = "messages"

# --- rich export fixture (Milestone 3 parser) -------------------------------
#
# Every constant below is an **expected decoded value**; the builder writes the
# mojibake form (UTF-8 bytes reinterpreted as latin-1, exactly like Instagram)
# and parser tests assert the round-trip back to these exact strings.

RICH_BASE_MS = 1_720_000_000_000

RICH_FRIEND_THREAD_PATH = f"inbox/{THREAD_DIR}"
RICH_SELF_THREAD_PATH = f"inbox/{SELF_THREAD_DIR}"

RICH_FRIEND_TITLE = "Synthetic Friend \U0001f60a"
RICH_MOJIBAKE_NOTE = "Check this reel \U0001f60a"
RICH_ADJACENT_AFTER = "More context after"
RICH_LATE_NOTE = "Too late to be adjacent"
RICH_SHARE_TEXT = "Synthetic share caption café"
RICH_POST_NOTE = f"Synthetic note about {POST_URL}"
RICH_EXTERNAL_URL = "https://example.com/synthetic-article?utm_source=synthetic&id=42"
RICH_EXTERNAL_NOTE = f"External link {RICH_EXTERNAL_URL}"
RICH_EXTERNAL_CANONICAL = "https://example.com/synthetic-article?id=42"
RICH_SELF_SHARE_TEXT = "Synthetic self reminder"
RICH_SELF_NOTE = "Synthetic self note"

REEL_A_SHORTCODE = "SYNTHAAA111"
REEL_A_CANONICAL = REEL_URL
REEL_A_TRACKING_URL = (
    "https://www.instagram.com/reel/SYNTHAAA111/?igsh=synthetictrack&utm_source=synthetic"
)
POST_B_SHORTCODE = "SYNTHBBB222"
POST_B_CANONICAL = POST_URL
REEL_SELF_URL = "https://www.instagram.com/reel/SYNTHCCC333/"
REEL_SELF_SHORTCODE = "SYNTHCCC333"

# Same sender within the default ±120s window of the first REEL_A share.
EXPECTED_ADJACENT_REEL_A = f"{RICH_MOJIBAKE_NOTE}\n{RICH_ADJACENT_AFTER}"

RICH_FRIEND_MESSAGE_COUNT = 11
RICH_FRIEND_LINK_COUNT = 5
RICH_SELF_MESSAGE_COUNT = 2
RICH_SELF_LINK_COUNT = 1
RICH_DUPLICATE_GROUP_SIZE = 3  # REEL_A shared three times (one a tracking variant)

RICH_FRIEND_FIRST_MS = RICH_BASE_MS
RICH_FRIEND_LAST_MS = RICH_BASE_MS + 5_000_000
RICH_SELF_FIRST_MS = RICH_BASE_MS + 2_000_000
RICH_SELF_LAST_MS = RICH_BASE_MS + 2_050_000


def _thread_json(unique: str) -> bytes:
    thread = {
        "participants": [{"name": OWNER_NAME}, {"name": FRIEND_NAME}],
        "messages": [
            {
                "sender_name": FRIEND_NAME,
                "timestamp_ms": 1_710_000_200_000,
                "share": {"link": REEL_URL, "share_text": "Synthetic share caption"},
            },
            {
                "sender_name": OWNER_NAME,
                "timestamp_ms": 1_710_000_100_000,
                "content": f"Synthetic note about {POST_URL} run-{unique}",
            },
        ],
        "title": FRIEND_NAME,
        "thread_path": f"inbox/{THREAD_DIR}",
    }
    return json.dumps(thread).encode()


def _personal_information_json() -> bytes:
    return json.dumps(
        {"profile_user": [{"string_map_data": {"Name": {"value": OWNER_NAME}}}]}
    ).encode()


def build_variant_a_zip(path: Path, unique: str = "") -> Path:
    """Current export layout: `your_instagram_activity/messages/inbox/...`."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            f"{VARIANT_A_MESSAGES_PREFIX}/inbox/{THREAD_DIR}/message_1.json",
            _thread_json(unique),
        )
        zf.writestr("personal_information/personal_information.json", _personal_information_json())
    return path


def build_variant_b_zip(path: Path, unique: str = "") -> Path:
    """Legacy export layout: `messages/inbox/...`."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            f"{VARIANT_B_MESSAGES_PREFIX}/inbox/{THREAD_DIR}/message_1.json",
            _thread_json(unique),
        )
    return path


def _mojibake(value: str) -> str:
    """Encode the way Instagram exports do: UTF-8 bytes read back as latin-1."""
    return value.encode("utf-8").decode("latin-1")


def _rich_message(
    sender: str, offset_seconds: int, content: str | None = None, **extra: Any
) -> dict[str, Any]:
    message: dict[str, Any] = {
        "sender_name": _mojibake(sender),
        "timestamp_ms": RICH_BASE_MS + offset_seconds * 1000,
    }
    if content is not None:
        message["content"] = _mojibake(content)
    message.update(extra)
    return message


def _rich_friend_messages(unique: str) -> list[dict[str, Any]]:
    """Chronological messages covering every parser case: shares with and
    without share_text, URLs inside content, adjacent-window hits and misses,
    exact + tracking-parameter duplicates, an external link, mojibake/emoji,
    and media-only/unsent messages."""
    return [
        _rich_message(FRIEND_NAME, 0, content=RICH_MOJIBAKE_NOTE),
        _rich_message(
            FRIEND_NAME,
            60,
            share={"link": REEL_URL, "share_text": _mojibake(RICH_SHARE_TEXT)},
        ),
        _rich_message(FRIEND_NAME, 120, content=RICH_ADJACENT_AFTER),
        _rich_message(FRIEND_NAME, 400, content=RICH_LATE_NOTE),
        _rich_message(OWNER_NAME, 500, content=RICH_POST_NOTE),
        _rich_message(FRIEND_NAME, 700, share={"link": REEL_A_TRACKING_URL}),
        _rich_message(FRIEND_NAME, 900, share={"link": REEL_URL}),
        _rich_message(OWNER_NAME, 1000, content=RICH_EXTERNAL_NOTE),
        _rich_message(FRIEND_NAME, 1100, photos=[{"uri": "synthetic/photo_1.jpg"}]),
        _rich_message(FRIEND_NAME, 1200, is_unsent=True),
        _rich_message(OWNER_NAME, 5000, content=f"Synthetic run marker {unique}".strip()),
    ]


def _rich_page(
    title: str, participants: list[str], thread_dir: str, messages: list[dict[str, Any]]
) -> bytes:
    return json.dumps(
        {
            "participants": [{"name": _mojibake(name)} for name in participants],
            "messages": messages,
            "title": _mojibake(title),
            "thread_path": f"inbox/{thread_dir}",
        }
    ).encode()


def build_rich_export_zip(
    path: Path,
    variant: str = "a",
    include_self_dm: bool = True,
    include_personal_info: bool = True,
    unique: str = "",
) -> Path:
    """Rich multi-thread export with identical logical content in both layouts.

    The friend thread is paginated: `message_1.json` holds the newest messages
    and `message_2.json` the oldest, each page reverse-chronological — exactly
    how real exports paginate.
    """
    prefix = VARIANT_A_MESSAGES_PREFIX if variant == "a" else VARIANT_B_MESSAGES_PREFIX
    friend = _rich_friend_messages(unique)
    newest_page = list(reversed(friend[5:]))
    oldest_page = list(reversed(friend[:5]))
    participants = [OWNER_NAME, FRIEND_NAME]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            f"{prefix}/inbox/{THREAD_DIR}/message_1.json",
            _rich_page(RICH_FRIEND_TITLE, participants, THREAD_DIR, newest_page),
        )
        zf.writestr(
            f"{prefix}/inbox/{THREAD_DIR}/message_2.json",
            _rich_page(RICH_FRIEND_TITLE, participants, THREAD_DIR, oldest_page),
        )
        if include_self_dm:
            self_messages = [
                _rich_message(
                    OWNER_NAME,
                    2050,
                    content=RICH_SELF_NOTE,
                ),
                _rich_message(
                    OWNER_NAME,
                    2000,
                    share={"link": REEL_SELF_URL, "share_text": _mojibake(RICH_SELF_SHARE_TEXT)},
                ),
            ]
            zf.writestr(
                f"{prefix}/inbox/{SELF_THREAD_DIR}/message_1.json",
                _rich_page(OWNER_NAME, [OWNER_NAME], SELF_THREAD_DIR, self_messages),
            )
        if include_personal_info:
            zf.writestr(
                "personal_information/personal_information.json", _personal_information_json()
            )
    return path


# --- clusterable export fixture (Milestone 6 analysis) -----------------------
#
# One friend thread with two clearly-themed groups of shares (high token
# overlap within a theme, none across) plus a near-duplicate text pair with
# distinct URLs. Deterministic clusters under both the mock and the real local
# embedding provider; kept separate from the rich export so M4/M5 count
# assertions stay untouched.

CLUSTER_THREAD_DIR = "syntheticclusters_1122334455"
CLUSTER_THREAD_PATH = f"inbox/{CLUSTER_THREAD_DIR}"

CLUSTER_SOURDOUGH_SHARES = [
    ("https://www.instagram.com/reel/CLUSTAAA001/", "Sourdough bread baking starter guide"),
    ("https://www.instagram.com/reel/CLUSTAAA002/", "Sourdough bread baking starter tips"),
    ("https://www.instagram.com/reel/CLUSTAAA003/", "Sourdough bread baking starter schedule"),
]
CLUSTER_CLIMBING_SHARES = [
    ("https://www.instagram.com/reel/CLUSTBBB001/", "Climbing bouldering grip strength drills"),
    ("https://www.instagram.com/reel/CLUSTBBB002/", "Climbing bouldering grip strength training"),
    ("https://www.instagram.com/reel/CLUSTBBB003/", "Climbing bouldering grip strength practice"),
]
# Identical text on two different URLs: no exact duplicate, but a near_text
# duplicate group once embeddings exist.
CLUSTER_NEAR_DUP_TEXT = "Perfect espresso tamping pressure demo"
CLUSTER_NEAR_DUP_SHARES = [
    ("https://www.instagram.com/reel/CLUSTCCC001/", CLUSTER_NEAR_DUP_TEXT),
    ("https://www.instagram.com/reel/CLUSTCCC002/", CLUSTER_NEAR_DUP_TEXT),
]

CLUSTER_ITEM_COUNT = 8
CLUSTER_MESSAGE_COUNT = 9  # 8 shares + 1 run marker


def build_cluster_export_zip(path: Path, unique: str = "") -> Path:
    """Current-layout export whose items form deterministic semantic clusters."""
    shares = [*CLUSTER_SOURDOUGH_SHARES, *CLUSTER_CLIMBING_SHARES, *CLUSTER_NEAR_DUP_SHARES]
    messages = [
        _rich_message(FRIEND_NAME, index * 300, share={"link": link, "share_text": text})
        for index, (link, text) in enumerate(shares)
    ]
    # Far outside every adjacent-text window, so item texts stay exactly the
    # share texts; carries the per-run marker for distinct checksums.
    messages.append(
        _rich_message(OWNER_NAME, 100_000, content=f"Synthetic run marker {unique}".strip())
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            f"{VARIANT_A_MESSAGES_PREFIX}/inbox/{CLUSTER_THREAD_DIR}/message_1.json",
            _rich_page(
                "Synthetic Clusters",
                [OWNER_NAME, FRIEND_NAME],
                CLUSTER_THREAD_DIR,
                list(reversed(messages)),
            ),
        )
        zf.writestr("personal_information/personal_information.json", _personal_information_json())
    return path


def build_html_export_zip(path: Path) -> Path:
    """HTML-format export — must be rejected with the "re-request as JSON" message."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            f"{VARIANT_A_MESSAGES_PREFIX}/inbox/{THREAD_DIR}/message_1.html",
            b"<!DOCTYPE html><html><body>Synthetic HTML export body</body></html>",
        )
    return path


def build_zip_with_entry(path: Path, entry_name: str, data: bytes = b"synthetic") -> Path:
    """Generic builder for malicious entry names (zip-slip variants)."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(entry_name, data)
    return path


def build_zip_slip_zip(path: Path, entry_name: str = "../../evil.txt") -> Path:
    return build_zip_with_entry(path, entry_name)


def build_ratio_bomb_zip(path: Path, payload_bytes: int = 2 * 1024 * 1024) -> Path:
    """One large, extremely compressible entry (zeros) — huge compression ratio."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            f"{VARIANT_A_MESSAGES_PREFIX}/inbox/{THREAD_DIR}/message_1.json",
            b"\0" * payload_bytes,
        )
    return path


def build_entry_count_bomb_zip(path: Path, entries: int = 200) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for index in range(entries):
            zf.writestr(f"padding/entry_{index}.txt", b"x")
    return path


def build_total_size_bomb_zip(path: Path, entries: int = 8, entry_bytes: int = 512 * 1024) -> Path:
    """Many entries each below the per-entry ratio floor, huge declared total."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for index in range(entries):
            zf.writestr(f"padding/blob_{index}.bin", b"\0" * entry_bytes)
    return path


def build_not_a_zip(path: Path) -> Path:
    path.write_bytes(b"this is not a zip archive, just synthetic filler bytes")
    return path


def build_corrupted_zip(path: Path) -> Path:
    """Valid ZIP whose end-of-central-directory record is clobbered."""
    build_variant_a_zip(path)
    data = bytearray(path.read_bytes())
    data[-30:] = b"\0" * 30
    path.write_bytes(bytes(data))
    return path


def build_empty_zip(path: Path) -> Path:
    with zipfile.ZipFile(path, "w"):
        pass
    return path


def build_unrecognized_zip(path: Path) -> Path:
    """Valid ZIP with no Instagram-export structure at all."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("random/notes.txt", b"synthetic unrelated content")
    return path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path, help="output directory")
    parser.add_argument(
        "--unique",
        default="",
        help="marker mixed into message text so each run's ZIPs get distinct checksums",
    )
    args = parser.parse_args(argv)
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)

    build_variant_a_zip(out / "variant_a.zip", unique=args.unique)
    build_variant_b_zip(out / "variant_b.zip", unique=args.unique)
    build_rich_export_zip(out / "rich_a.zip", variant="a", unique=args.unique)
    build_rich_export_zip(out / "rich_b.zip", variant="b", unique=args.unique)
    build_cluster_export_zip(out / "clusters.zip", unique=args.unique)
    # Same logical content, distinct checksum: projects.spec.ts uploads its
    # own archive so checksum dedupe can't 409 against clusters.spec.ts.
    build_cluster_export_zip(out / "projects.zip", unique=f"{args.unique}-projects")
    build_html_export_zip(out / "html_export.zip")
    build_zip_slip_zip(out / "zip_slip.zip")
    build_ratio_bomb_zip(out / "zip_bomb_ratio.zip")
    build_entry_count_bomb_zip(out / "zip_bomb_entries.zip")
    build_not_a_zip(out / "not_a_zip.zip")
    build_empty_zip(out / "empty.zip")
    build_unrecognized_zip(out / "unrecognized.zip")
    print(f"synthetic fixtures written to {out}")


if __name__ == "__main__":
    main()
