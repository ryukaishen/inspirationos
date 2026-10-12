"""Real media adapters without the network: the yt-dlp adapter against a
stand-in `yt_dlp` module, and frame sampling / audio detection against a
synthetic video generated on the fly. The frame tests need the optional
`media` extra (PyAV + Pillow) and skip with an explicit reason without it —
CI doesn't install that extra; run `pip install -e ".[dev,media]"` locally."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import pytest

from app.services.media.pipeline import (
    MediaBlockedError,
    MediaTooLongError,
    MediaUnavailableError,
)
from app.services.media.ytdlp import YtDlpDownloader

URL = "https://www.instagram.com/reel/SYNTH1/"


class _FakeDownloadError(Exception):
    pass


def _install_fake_ytdlp(
    monkeypatch: pytest.MonkeyPatch,
    *,
    info: dict[str, Any] | None = None,
    error: str | None = None,
    write_file: bool = True,
) -> list[dict[str, Any]]:
    seen_params: list[dict[str, Any]] = []

    class FakeYoutubeDL:
        def __init__(self, params: dict[str, Any]) -> None:
            seen_params.append(params)
            self.params = params

        def __enter__(self) -> FakeYoutubeDL:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def extract_info(self, url: str, download: bool = True) -> dict[str, Any] | None:
            if error is not None:
                raise _FakeDownloadError(error)
            if write_file:
                target = Path(self.params["outtmpl"].replace("%(id)s.%(ext)s", "SYNTH1.mp4"))
                target.write_bytes(b"fake video")
            return info

    module = types.ModuleType("yt_dlp")
    module.YoutubeDL = FakeYoutubeDL  # type: ignore[attr-defined]
    utils = types.ModuleType("yt_dlp.utils")
    utils.DownloadError = _FakeDownloadError  # type: ignore[attr-defined]
    utils.match_filter_func = lambda expr: expr  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "yt_dlp", module)
    monkeypatch.setitem(sys.modules, "yt_dlp.utils", utils)
    return seen_params


def _downloader(cookies: Path | None = None) -> YtDlpDownloader:
    return YtDlpDownloader(cookies_file=cookies, cookies_from_browser=None, max_duration_seconds=60)


def test_download_returns_file_and_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    params = _install_fake_ytdlp(
        monkeypatch,
        info={"description": "a caption", "uploader": "creator", "title": "Video", "duration": 30},
    )
    reel = _downloader(cookies=Path("cookies.txt")).download(URL, tmp_path)
    assert reel.video_path.name == "SYNTH1.mp4"
    assert (reel.caption, reel.author, reel.title) == ("a caption", "creator", "Video")
    assert params[0]["cookiefile"] == "cookies.txt"
    assert params[0]["quiet"] is True
    assert params[0]["match_filter"] == "!duration | duration <= 60"


def test_carousel_metadata_comes_from_first_entry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_fake_ytdlp(monkeypatch, info={"entries": [{"description": "entry caption"}]})
    assert _downloader().download(URL, tmp_path).caption == "entry caption"


def test_login_wall_is_blocked(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _install_fake_ytdlp(monkeypatch, error="ERROR: [Instagram] SYNTH1: login required")
    with pytest.raises(MediaBlockedError):
        _downloader().download(URL, tmp_path)


def test_filtered_long_video_is_too_long(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _install_fake_ytdlp(monkeypatch, info={"duration": 3600}, write_file=False)
    with pytest.raises(MediaTooLongError):
        _downloader().download(URL, tmp_path)


def test_no_file_is_unavailable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _install_fake_ytdlp(monkeypatch, info={"duration": 10}, write_file=False)
    with pytest.raises(MediaUnavailableError):
        _downloader().download(URL, tmp_path)


def _make_video(path: Path, *, with_audio: bool) -> None:
    """4s, 10fps; each second shows a different solid colour, so sampled
    frames are distinguishable by their pixels."""
    av = pytest.importorskip("av", reason="needs the optional `media` extra (PyAV)")
    np = pytest.importorskip("numpy")
    colours = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]
    container = av.open(str(path), "w")
    video = container.add_stream("libx264", rate=10)
    video.width, video.height, video.pix_fmt = 64, 64, "yuv420p"
    audio = container.add_stream("aac", rate=16000) if with_audio else None
    for index in range(40):
        pixels = np.full((64, 64, 3), colours[index // 10], dtype=np.uint8)
        for packet in video.encode(av.VideoFrame.from_ndarray(pixels, format="rgb24")):
            container.mux(packet)
    for packet in video.encode():
        container.mux(packet)
    if audio is not None:
        silence = np.zeros((1, 1024), dtype=np.float32)
        for _ in range(60):
            frame = av.AudioFrame.from_ndarray(silence, format="flt", layout="mono")
            frame.sample_rate = 16000
            for packet in audio.encode(frame):
                container.mux(packet)
        for packet in audio.encode():
            container.mux(packet)
    container.close()


def test_sample_frames_are_spread_across_the_video(tmp_path: Path) -> None:
    pytest.importorskip("PIL", reason="needs the optional `media` extra (Pillow)")
    from io import BytesIO

    from PIL import Image

    from app.services.media.frames import sample_frames

    video = tmp_path / "synthetic.mp4"
    _make_video(video, with_audio=False)

    frames = sample_frames(video, 4)

    assert len(frames) == 4
    dominant = []
    for data in frames:
        red, green, blue = Image.open(BytesIO(data)).convert("RGB").getpixel((32, 32))
        dominant.append(max(("r", red), ("g", green), ("b", blue), key=lambda c: c[1])[0])
    # red, green, blue, yellow (r and g both high -> either may win the max)
    assert dominant[:3] == ["r", "g", "b"]


def test_audio_detection(tmp_path: Path) -> None:
    from app.services.media.whisper import FasterWhisperTranscriber, has_audio_stream

    silent = tmp_path / "silent.mp4"
    voiced = tmp_path / "voiced.mp4"
    _make_video(silent, with_audio=False)
    _make_video(voiced, with_audio=True)

    assert has_audio_stream(voiced) is True
    assert has_audio_stream(silent) is False
    # No audio track -> empty transcript without ever loading a Whisper model.
    assert FasterWhisperTranscriber("tiny").transcribe(silent) == ""
