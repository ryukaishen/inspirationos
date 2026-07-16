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

OWNER_NAME = "Synthetic Owner"
FRIEND_NAME = "Synthetic Friend"
THREAD_DIR = "syntheticfriend_1234567890"
REEL_URL = "https://www.instagram.com/reel/SYNTHAAA111/"
POST_URL = "https://www.instagram.com/p/SYNTHBBB222/"

VARIANT_A_MESSAGES_PREFIX = "your_instagram_activity/messages"
VARIANT_B_MESSAGES_PREFIX = "messages"


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
