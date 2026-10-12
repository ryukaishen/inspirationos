"""Reel media pipeline (services/media/pipeline.py + ytdlp error mapping):
pure orchestration against fake adapters — no network, no yt-dlp, no
Whisper, no database. All text below is synthetic."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.models.enrichment_attempt import EnrichmentSource, EnrichmentStatus
from app.models.item import Item, ItemStatus, ItemType
from app.services.enrichment.policy import CircuitBreaker
from app.services.media.pipeline import (
    DownloadedReel,
    ExtractionSettings,
    MediaBlockedError,
    MediaUnavailableError,
    ReelGroup,
    apply_result,
    extract_reel,
    run_transcription,
)
from app.services.media.ytdlp import MediaDownloadError, classify_download_error

SETTINGS = ExtractionSettings(vision_min_transcript_words=5, vision_frame_count=3)
LONG_SPEECH = "synthetic speech about building a habit tracker with a weekly review"
SECRET = "synthetic-private-detail-should-never-surface"


class FakeDownloader:
    def __init__(self, error: Exception | None = None, caption: str | None = "a caption") -> None:
        self.error = error
        self.caption = caption
        self.paths: list[Path] = []

    def download(self, url: str, workdir: Path) -> DownloadedReel:
        if self.error is not None:
            raise self.error
        video = workdir / "reel.mp4"
        video.write_bytes(b"fake video")
        self.paths.append(video)
        return DownloadedReel(video_path=video, caption=self.caption, author="creator_handle")


class FakeTranscriber:
    def __init__(self, text: str = LONG_SPEECH, error: Exception | None = None) -> None:
        self.text = text
        self.error = error

    def transcribe(self, media_path: Path) -> str:
        assert media_path.exists(), "transcriber must see the downloaded file"
        if self.error is not None:
            raise self.error
        return self.text


class FakeFrameReader:
    def __init__(self, text: str = "STEP 1 open the app") -> None:
        self.text = text
        self.calls: list[int] = []

    def read_frames(self, frames: list[bytes]) -> str:
        self.calls.append(len(frames))
        return self.text


def fake_sampler(path: Path, count: int) -> list[bytes]:
    return [b"jpeg"] * count


def run(
    tmp_path: Path,
    *,
    downloader: FakeDownloader | None = None,
    transcriber: FakeTranscriber | None = None,
    frame_reader: FakeFrameReader | None = None,
):
    return extract_reel(
        "https://www.instagram.com/reel/SYNTH1/",
        downloader=downloader or FakeDownloader(),
        transcriber=transcriber or FakeTranscriber(),
        frame_reader=frame_reader,
        sample_frames=fake_sampler,
        workdir=tmp_path,
        settings=SETTINGS,
    )


def test_success_keeps_transcript_caption_and_author(tmp_path: Path) -> None:
    result = run(tmp_path)
    assert result.status is EnrichmentStatus.success
    assert result.transcript == LONG_SPEECH
    assert result.caption == "a caption"
    assert result.author == "creator_handle"


def test_video_is_deleted_after_extraction(tmp_path: Path) -> None:
    downloader = FakeDownloader()
    run(tmp_path, downloader=downloader)
    assert downloader.paths and not downloader.paths[0].exists()
    assert list(tmp_path.iterdir()) == []


def test_vision_skipped_when_reel_has_enough_speech(tmp_path: Path) -> None:
    reader = FakeFrameReader()
    result = run(tmp_path, frame_reader=reader)
    assert reader.calls == []
    assert result.visual_text is None


def test_vision_reads_frames_when_speech_is_short(tmp_path: Path) -> None:
    reader = FakeFrameReader()
    result = run(tmp_path, transcriber=FakeTranscriber(text="music"), frame_reader=reader)
    assert reader.calls == [SETTINGS.vision_frame_count]
    assert result.visual_text == "STEP 1 open the app"
    assert result.transcript == "music"


def test_blank_transcript_is_stored_as_none(tmp_path: Path) -> None:
    result = run(tmp_path, transcriber=FakeTranscriber(text="   "))
    assert result.status is EnrichmentStatus.success
    assert result.transcript is None


def test_unavailable_reel_is_not_found(tmp_path: Path) -> None:
    result = run(tmp_path, downloader=FakeDownloader(error=MediaUnavailableError()))
    assert result.status is EnrichmentStatus.not_found


def test_blocked_reel_is_blocked(tmp_path: Path) -> None:
    result = run(tmp_path, downloader=FakeDownloader(error=MediaBlockedError()))
    assert result.status is EnrichmentStatus.blocked


def test_unexpected_download_failure_keeps_class_name_only(tmp_path: Path) -> None:
    result = run(tmp_path, downloader=FakeDownloader(error=RuntimeError(SECRET)))
    assert result.status is EnrichmentStatus.error
    assert result.error == "RuntimeError"
    assert SECRET not in repr(result)


def test_transcription_failure_without_vision_is_retryable_error(tmp_path: Path) -> None:
    result = run(tmp_path, transcriber=FakeTranscriber(error=ValueError(SECRET)))
    assert result.status is EnrichmentStatus.error
    assert result.error == "ValueError"


def test_transcription_failure_rescued_by_vision_is_success(tmp_path: Path) -> None:
    result = run(
        tmp_path,
        transcriber=FakeTranscriber(error=ValueError(SECRET)),
        frame_reader=FakeFrameReader(),
    )
    assert result.status is EnrichmentStatus.success
    assert result.visual_text == "STEP 1 open the app"


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("ERROR: [Instagram] X: Requested content is not available, login required", "blocked"),
        ("ERROR: HTTP Error 429: Too Many Requests", "blocked"),
        ("ERROR: use --cookies-from-browser or --cookies for the authentication", "blocked"),
        ("ERROR: [Instagram] X: There is no video in this post", "unavailable"),
        ("ERROR: HTTP Error 404: Not Found", "unavailable"),
        ("ERROR: unable to download video data: timed out", "other"),
    ],
)
def test_classify_download_error(message: str, expected: str) -> None:
    error = classify_download_error(message)
    expected_type = {
        "blocked": MediaBlockedError,
        "unavailable": MediaUnavailableError,
        "other": MediaDownloadError,
    }[expected]
    assert type(error) is expected_type
    assert str(error) == "", "the yt-dlp message must not be carried along"


def make_item(**overrides: object) -> Item:
    fields: dict[str, object] = {
        "id": 1,
        "url_raw": "https://www.instagram.com/reel/SYNTH1/",
        "url_canonical": "https://www.instagram.com/reel/SYNTH1/",
        "item_type": ItemType.reel,
        "status": ItemStatus.needs_context,
        "embedding": [0.1] * 384,
        "embedding_model": "mock",
    }
    fields.update(overrides)
    return Item(**fields)


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.commits = 0

    def add(self, obj: object) -> None:
        self.added.append(obj)

    def commit(self) -> None:
        self.commits += 1


def test_apply_result_promotes_needs_context_and_clears_embedding(tmp_path: Path) -> None:
    item = make_item()
    session = FakeSession()
    apply_result(session, [item], run(tmp_path))  # type: ignore[arg-type]
    assert item.transcript == LONG_SPEECH
    assert item.enriched_caption == "a caption"
    assert item.enriched_source is EnrichmentSource.ytdlp
    assert item.status is ItemStatus.new
    assert item.embedding is None and item.embedding_model is None
    assert len(session.added) == 1


def test_apply_result_keeps_other_source_caption(tmp_path: Path) -> None:
    item = make_item(enriched_caption="from oembed", enriched_source=EnrichmentSource.oembed)
    apply_result(FakeSession(), [item], run(tmp_path))  # type: ignore[arg-type]
    assert item.enriched_caption == "from oembed"
    assert item.transcript == LONG_SPEECH


def test_apply_result_on_failure_only_audits(tmp_path: Path) -> None:
    item = make_item()
    session = FakeSession()
    result = run(tmp_path, downloader=FakeDownloader(error=MediaBlockedError()))
    apply_result(session, [item], result)  # type: ignore[arg-type]
    assert item.transcript is None
    assert item.status is ItemStatus.needs_context
    assert item.embedding is not None
    assert len(session.added) == 1


def test_run_stops_when_breaker_trips_and_paces_between_reels(tmp_path: Path) -> None:
    groups = [
        ReelGroup(url=f"https://www.instagram.com/reel/S{i}/", items=[make_item(id=i)])
        for i in range(5)
    ]
    sleeps: list[float] = []
    lines: list[str] = []
    summary = run_transcription(
        FakeSession(),  # type: ignore[arg-type]
        groups,
        downloader=FakeDownloader(error=MediaBlockedError()),
        transcriber=FakeTranscriber(),
        frame_reader=None,
        sample_frames=fake_sampler,
        workdir=tmp_path,
        settings=SETTINGS,
        delay_seconds=8.0,
        jitter_seconds=0.0,
        breaker=CircuitBreaker(2),
        report=lines.append,
        sleep=sleeps.append,
    )
    assert summary.stopped_by_breaker
    assert summary.counts == {EnrichmentStatus.blocked: 2}
    assert sleeps == [8.0], "no sleep before the first reel, one between reels"


def test_run_progress_lines_never_contain_text(tmp_path: Path) -> None:
    groups = [ReelGroup(url="https://www.instagram.com/reel/S1/", items=[make_item()])]
    lines: list[str] = []
    run_transcription(
        FakeSession(),  # type: ignore[arg-type]
        groups,
        downloader=FakeDownloader(caption=SECRET),
        transcriber=FakeTranscriber(text=f"{LONG_SPEECH} {SECRET}"),
        frame_reader=None,
        sample_frames=fake_sampler,
        workdir=tmp_path,
        settings=SETTINGS,
        delay_seconds=0.0,
        jitter_seconds=0.0,
        breaker=CircuitBreaker(2),
        report=lines.append,
        sleep=lambda _: None,
    )
    assert lines and all(SECRET not in line for line in lines)
    assert "words" in lines[0]
