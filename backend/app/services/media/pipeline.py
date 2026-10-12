"""Pure orchestration for reel media extraction (see services/media/__init__).

`extract_reel` turns one reel URL into a `MediaResult` using injected
adapters; the downloaded video lives only inside a temporary directory that is
removed before the function returns. `apply_result` writes a result onto every
item sharing that reel and records one `enrichment_attempts` row per item.
`select_pending_reels` groups items by reel so a reel shared five times is
downloaded once. `run_transcription` drives a whole run with pacing and a
circuit breaker.

Privacy: results carry private content (transcripts, captions). Nothing here
logs or prints it — progress output is item IDs, statuses, and word counts,
and errors are reduced to exception class names.
"""

from __future__ import annotations

import random
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enrichment_attempt import EnrichmentAttempt, EnrichmentSource, EnrichmentStatus
from app.models.item import Item, ItemStatus, ItemType
from app.services.enrichment.policy import CircuitBreaker, is_eligible_for_generation

# Instagram item types that can carry a video; story links expire and
# external links aren't Instagram media.
MEDIA_ITEM_TYPES = (ItemType.reel, ItemType.tv, ItemType.post)

# A cached success/not_found means "done" — errors and blocks are retried on
# the next run, mirroring the enrichment worker's caching rule.
_DONE_STATUSES = (EnrichmentStatus.success, EnrichmentStatus.not_found)


class MediaUnavailableError(Exception):
    """The reel is gone for good: deleted, private, or has no video."""


class MediaTooLongError(MediaUnavailableError):
    """Longer than the configured cap — skipped permanently, not retried."""


class MediaBlockedError(Exception):
    """Instagram refused the session: login required, rate limit, checkpoint."""


@dataclass(frozen=True)
class DownloadedReel:
    video_path: Path
    caption: str | None = None
    author: str | None = None
    title: str | None = None


class Downloader(Protocol):
    def download(self, url: str, workdir: Path) -> DownloadedReel: ...


class Transcriber(Protocol):
    def transcribe(self, media_path: Path) -> str: ...


class FrameReader(Protocol):
    def read_frames(self, frames: list[bytes]) -> str: ...


FrameSampler = Callable[[Path, int], list[bytes]]


@dataclass(frozen=True)
class MediaResult:
    status: EnrichmentStatus
    caption: str | None = None
    author: str | None = None
    title: str | None = None
    transcript: str | None = None
    visual_text: str | None = None
    error: str | None = None  # exception class name only, never its message


@dataclass(frozen=True)
class ExtractionSettings:
    vision_min_transcript_words: int = 25
    vision_frame_count: int = 4


def word_count(text: str | None) -> int:
    return len(text.split()) if text else 0


def _clean(text: str | None) -> str | None:
    if text is None:
        return None
    stripped = text.strip()
    return stripped or None


def extract_reel(
    url: str,
    *,
    downloader: Downloader,
    transcriber: Transcriber,
    frame_reader: FrameReader | None,
    sample_frames: FrameSampler,
    workdir: Path,
    settings: ExtractionSettings,
) -> MediaResult:
    """Download one reel, transcribe it, and (for reels with little speech)
    read its on-screen text. The video never outlives this call."""
    workdir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=workdir) as tmp:
        try:
            reel = downloader.download(url, Path(tmp))
        except MediaUnavailableError as exc:
            return MediaResult(status=EnrichmentStatus.not_found, error=type(exc).__name__)
        except MediaBlockedError as exc:
            return MediaResult(status=EnrichmentStatus.blocked, error=type(exc).__name__)
        except Exception as exc:
            return MediaResult(status=EnrichmentStatus.error, error=type(exc).__name__)

        transcript: str | None = None
        transcribe_error: str | None = None
        try:
            transcript = _clean(transcriber.transcribe(reel.video_path))
        except Exception as exc:
            transcribe_error = type(exc).__name__

        visual_text: str | None = None
        vision_error: str | None = None
        if (
            frame_reader is not None
            and word_count(transcript) < settings.vision_min_transcript_words
        ):
            try:
                frames = sample_frames(reel.video_path, settings.vision_frame_count)
                if frames:
                    visual_text = _clean(frame_reader.read_frames(frames))
            except Exception as exc:
                vision_error = type(exc).__name__

    # A failed step with nothing to show for it is retried next run rather
    # than cached as done.
    failure = transcribe_error or vision_error
    if failure and transcript is None and visual_text is None:
        return MediaResult(status=EnrichmentStatus.error, error=failure)
    return MediaResult(
        status=EnrichmentStatus.success,
        caption=_clean(reel.caption),
        author=_clean(reel.author),
        title=_clean(reel.title),
        transcript=transcript,
        visual_text=visual_text,
    )


def apply_result(session: Session, items: list[Item], result: MediaResult) -> None:
    """Audit every item, and on success copy the extracted text onto it.

    New text invalidates the item's embedding (re-embedded on the next
    embed run) and promotes a `needs_context` item to `new` once it carries
    real text. Captions only fill fields no other enrichment source set.
    """
    for item in items:
        session.add(
            EnrichmentAttempt(
                item_id=item.id,
                source=EnrichmentSource.ytdlp,
                status=result.status,
                fetched_title=result.title,
                fetched_caption=result.caption,
                fetched_author=result.author,
                error=result.error,
            )
        )
        if result.status is not EnrichmentStatus.success:
            continue
        item.transcript = result.transcript
        item.visual_text = result.visual_text
        if item.enriched_source in (None, EnrichmentSource.ytdlp) and (
            result.caption or result.author or result.title
        ):
            item.enriched_caption = result.caption
            item.enriched_author = result.author
            item.enriched_title = result.title
            item.enriched_source = EnrichmentSource.ytdlp
        item.embedding = None
        item.embedding_model = None
        if item.status is ItemStatus.needs_context and is_eligible_for_generation(item):
            item.status = ItemStatus.new


@dataclass
class ReelGroup:
    """Every item that points at the same reel, plus the URL to fetch."""

    url: str
    items: list[Item] = field(default_factory=list)


def select_pending_reels(
    session: Session, *, item_ids: list[int] | None = None, limit: int | None = None
) -> list[ReelGroup]:
    """Reels with no cached success/not_found attempt, newest share first,
    one group per shortcode (or canonical URL when there is no shortcode)."""
    done_item_ids = select(EnrichmentAttempt.item_id).where(
        EnrichmentAttempt.source == EnrichmentSource.ytdlp,
        EnrichmentAttempt.status.in_(_DONE_STATUSES),
    )
    stmt = (
        select(Item)
        .where(Item.item_type.in_(MEDIA_ITEM_TYPES), Item.id.not_in(done_item_ids))
        .order_by(Item.shared_at.desc().nulls_last(), Item.id)
    )
    if item_ids:
        stmt = stmt.where(Item.id.in_(item_ids))

    groups: dict[str, ReelGroup] = {}
    for item in session.scalars(stmt):
        key = item.shortcode or item.url_canonical
        group = groups.get(key)
        if group is None:
            if limit is not None and len(groups) >= limit:
                continue
            group = groups[key] = ReelGroup(url=item.url_canonical)
        group.items.append(item)
    return list(groups.values())


@dataclass
class RunSummary:
    counts: dict[EnrichmentStatus, int] = field(default_factory=dict)
    stopped_by_breaker: bool = False

    def record(self, status: EnrichmentStatus) -> None:
        self.counts[status] = self.counts.get(status, 0) + 1


def run_transcription(
    session: Session,
    groups: list[ReelGroup],
    *,
    downloader: Downloader,
    transcriber: Transcriber,
    frame_reader: FrameReader | None,
    sample_frames: FrameSampler,
    workdir: Path,
    settings: ExtractionSettings,
    delay_seconds: float,
    jitter_seconds: float,
    breaker: CircuitBreaker,
    report: Callable[[str], None] = print,
    sleep: Callable[[float], None] = time.sleep,
) -> RunSummary:
    """Process groups one at a time, committing after each so a run can be
    stopped and resumed. Stops early once the breaker trips."""
    summary = RunSummary()
    for index, group in enumerate(groups, start=1):
        if index > 1:
            sleep(delay_seconds + random.uniform(0, jitter_seconds))
        result = extract_reel(
            group.url,
            downloader=downloader,
            transcriber=transcriber,
            frame_reader=frame_reader,
            sample_frames=sample_frames,
            workdir=workdir,
            settings=settings,
        )
        apply_result(session, group.items, result)
        session.commit()
        summary.record(result.status)
        breaker.record(result.status)

        ids = ",".join(str(item.id) for item in group.items)
        detail = f"{result.status.value}"
        if result.status is EnrichmentStatus.success:
            detail += (
                f" — transcript {word_count(result.transcript)} words,"
                f" on-screen {word_count(result.visual_text)} words"
            )
        elif result.error:
            detail += f" ({result.error})"
        report(f"[{index}/{len(groups)}] items {ids}: {detail}")

        if breaker.is_open:
            summary.stopped_by_breaker = True
            report(
                "Stopping: Instagram refused several reels in a row (login expired or"
                " rate limited). Refresh your cookies and wait before re-running;"
                " finished reels are saved and will be skipped."
            )
            break
    return summary
