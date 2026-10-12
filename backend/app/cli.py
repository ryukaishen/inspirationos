"""Operator CLI: `python -m app.cli <command>`.

- `create-user` — seeds/updates the single-user account (no open
  registration anywhere in the app).
- `wipe-data` — the complete-wipe scope, run synchronously against the DB
  directly (no worker/Redis required) for ops use on a stuck deployment.
- `transcribe-reels` — download each pending reel with the operator's own
  Instagram session cookies, transcribe it locally, read on-screen text, and
  save the text onto its items (services/media/). Needs the `media` extra and
  runs on the host, not in a container.
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

from sqlalchemy import select

from app.config import get_config
from app.db import get_sessionmaker
from app.models.user import User
from app.services.auth.passwords import hash_password
from app.services.enrichment.policy import CircuitBreaker
from app.services.media.pipeline import (
    ExtractionSettings,
    FrameReader,
    select_pending_reels,
)
from app.services.privacy.deletion import wipe_everything
from app.services.storage.local import LocalStorage


def create_user(email: str, password: str | None) -> None:
    if not password:
        password = getpass.getpass("Password: ")
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            print("passwords do not match", file=sys.stderr)
            raise SystemExit(1)
    password_hash = hash_password(password)
    with get_sessionmaker()() as session:
        existing = session.scalar(select(User).where(User.email == email))
        if existing is not None:
            existing.password_hash = password_hash
            action = "updated"
        else:
            session.add(User(email=email, password_hash=password_hash))
            action = "created"
        session.commit()
    print(f"user {action}: {email}")


def wipe_data(*, confirm: bool) -> None:
    if not confirm:
        typed = input(
            "This permanently deletes ALL application data except the user account. "
            "Type WIPE to continue: "
        )
        if typed != "WIPE":
            print("aborted")
            raise SystemExit(1)
    with get_sessionmaker()() as session:
        storage = LocalStorage(get_config().data_dir)
        report = wipe_everything(session, storage)
    print(json.dumps(report, indent=2))


MEDIA_DISCLOSURE = """\
This will download {count} reel(s) from instagram.com using YOUR logged-in
Instagram session ({cookie_source}). Each video is transcribed on this computer
and deleted right after; only the extracted text is saved to the app's database.
{vision_line}
Downloads are paced ~{delay:.0f}s apart and the run stops if Instagram starts
refusing requests. Bulk downloading may go against Instagram's terms and can get
the account temporarily restricted — a secondary account is safer."""


def transcribe_reels(
    *,
    cookies: Path | None,
    cookies_from_browser: str | None,
    limit: int | None,
    item_ids: list[int] | None,
    vision: bool,
    whisper_model: str | None,
    confirm: bool,
    dry_run: bool,
) -> None:
    if cookies is None and not cookies_from_browser:
        print(
            "Provide --cookies cookies.txt (recommended) or --cookies-from-browser NAME.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if cookies is not None and not cookies.is_file():
        print(f"cookies file not found: {cookies}", file=sys.stderr)
        raise SystemExit(2)

    config = get_config()
    use_vision = vision and bool(config.anthropic_api_key)

    with get_sessionmaker()() as session:
        groups = select_pending_reels(session, item_ids=item_ids, limit=limit)
        item_count = sum(len(group.items) for group in groups)
        print(f"{len(groups)} reel(s) pending ({item_count} item(s) incl. repeat shares).")
        if not groups or dry_run:
            return

        if vision and not use_vision:
            vision_line = "ANTHROPIC_API_KEY is not set, so on-screen text reading is OFF."
        elif use_vision:
            vision_line = (
                "Reels with little speech send a few still frames to the Anthropic API"
                f" ({config.anthropic_fast_model}) to read on-screen text (counts toward"
                " the monthly AI budget)."
            )
        else:
            vision_line = "On-screen text reading is OFF (--no-vision)."
        print(
            MEDIA_DISCLOSURE.format(
                count=len(groups),
                cookie_source=f"cookies file {cookies}"
                if cookies is not None
                else f"{cookies_from_browser} browser cookies",
                vision_line=vision_line,
                delay=config.media_delay_seconds,
            )
        )
        if not confirm and input("Continue? [y/N] ").strip().lower() not in ("y", "yes"):
            print("aborted")
            raise SystemExit(1)

        # Heavy optional imports only once the run is confirmed.
        from app.services.media.frames import sample_frames
        from app.services.media.pipeline import run_transcription
        from app.services.media.whisper import FasterWhisperTranscriber
        from app.services.media.ytdlp import YtDlpDownloader

        frame_reader: FrameReader | None = None
        if use_vision:
            import anthropic

            from app.services.media.vision import AnthropicFrameReader

            frame_reader = AnthropicFrameReader(
                session, config, anthropic.Anthropic(api_key=config.anthropic_api_key)
            )

        summary = run_transcription(
            session,
            groups,
            downloader=YtDlpDownloader(
                cookies_file=cookies,
                cookies_from_browser=cookies_from_browser,
                max_duration_seconds=config.media_max_duration_seconds,
            ),
            transcriber=FasterWhisperTranscriber(whisper_model or config.media_whisper_model),
            frame_reader=frame_reader,
            sample_frames=sample_frames,
            workdir=config.data_dir / "tmp" / "media",
            settings=ExtractionSettings(
                vision_min_transcript_words=config.media_vision_min_transcript_words,
                vision_frame_count=config.media_vision_frame_count,
            ),
            delay_seconds=config.media_delay_seconds,
            jitter_seconds=config.media_delay_jitter_seconds,
            breaker=CircuitBreaker(config.media_circuit_breaker_threshold),
        )

    totals = ", ".join(f"{status.value}: {n}" for status, n in summary.counts.items())
    print(f"Done — {totals or 'nothing processed'}.")
    print(
        "Next: open Clusters in the app and click Run analysis so search, clustering,"
        " and project ideas use the new text."
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_user_parser = subparsers.add_parser("create-user", help="seed or update the account")
    create_user_parser.add_argument("--email", required=True)
    create_user_parser.add_argument(
        "--password", default=None, help="omit to be prompted (recommended)"
    )

    wipe_parser = subparsers.add_parser("wipe-data", help="delete all application data")
    wipe_parser.add_argument(
        "--yes", action="store_true", help="skip the interactive confirmation prompt"
    )

    media_parser = subparsers.add_parser(
        "transcribe-reels", help="download, transcribe, and read on-screen text of reels"
    )
    cookie_group = media_parser.add_mutually_exclusive_group()
    cookie_group.add_argument(
        "--cookies", type=Path, default=None, help="Netscape cookies.txt exported from your browser"
    )
    cookie_group.add_argument(
        "--cookies-from-browser",
        default=None,
        metavar="NAME",
        help="read cookies directly (firefox works best; chrome/edge often fail on Windows)",
    )
    media_parser.add_argument("--limit", type=int, default=None, help="max reels this run")
    media_parser.add_argument(
        "--item-id", type=int, action="append", dest="item_ids", help="only these items"
    )
    media_parser.add_argument(
        "--no-vision", action="store_true", help="skip on-screen text reading (no API calls)"
    )
    media_parser.add_argument(
        "--whisper-model", default=None, help="tiny/base/small/medium/large-v3 (default small)"
    )
    media_parser.add_argument("--dry-run", action="store_true", help="only count pending reels")
    media_parser.add_argument(
        "--yes", action="store_true", help="skip the interactive confirmation prompt"
    )

    args = parser.parse_args(argv)
    if args.command == "create-user":
        create_user(args.email, args.password)
    elif args.command == "wipe-data":
        wipe_data(confirm=args.yes)
    elif args.command == "transcribe-reels":
        transcribe_reels(
            cookies=args.cookies,
            cookies_from_browser=args.cookies_from_browser,
            limit=args.limit,
            item_ids=args.item_ids,
            vision=not args.no_vision,
            whisper_model=args.whisper_model,
            confirm=args.yes,
            dry_run=args.dry_run,
        )


if __name__ == "__main__":
    main()
