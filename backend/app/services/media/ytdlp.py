"""yt-dlp downloader adapter (optional `media` extra).

Uses the operator's own Instagram session cookies — a `cookies.txt` export
(recommended: works for Chrome and Edge, whose on-disk cookies are encrypted
in a way yt-dlp often can't read on Windows) or `--cookies-from-browser`.
Never a password, never an automated login (PRIVACY_SECURITY.md, "Reel media
extraction"). yt-dlp's own output is routed to a silent logger so nothing it
prints can echo private content into the terminal or logs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services.media.pipeline import (
    DownloadedReel,
    MediaBlockedError,
    MediaTooLongError,
    MediaUnavailableError,
)

_VIDEO_SUFFIXES = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}

# Lowercased substrings of yt-dlp error messages. Blocked markers are checked
# first: "login required" responses often also say "not available".
_BLOCKED_MARKERS = (
    "login required",
    "log in",
    "rate-limit",
    "rate limit",
    "429",
    "401",
    "403",
    "checkpoint",
    "challenge",
    "please wait a few minutes",
    "cookies",
)
_UNAVAILABLE_MARKERS = (
    "404",
    "not found",
    "no video",
    "not available",
    "unavailable",
    "private",
    "removed",
    "does not exist",
)


class MediaDownloadError(Exception):
    """yt-dlp failed for a reason that may be transient — retried next run."""


def classify_download_error(message: str) -> Exception:
    """Map a yt-dlp error message to the pipeline's error taxonomy. The
    message itself is never kept — only the returned exception's class."""
    lowered = message.lower()
    if any(marker in lowered for marker in _BLOCKED_MARKERS):
        return MediaBlockedError()
    if any(marker in lowered for marker in _UNAVAILABLE_MARKERS):
        return MediaUnavailableError()
    return MediaDownloadError()


class _SilentLogger:
    def debug(self, msg: str) -> None:
        pass

    def info(self, msg: str) -> None:
        pass

    def warning(self, msg: str) -> None:
        pass

    def error(self, msg: str) -> None:
        pass


def _first_entry(info: dict[str, Any]) -> dict[str, Any]:
    """Carousel posts come back as a playlist; metadata lives on the entries."""
    entries = info.get("entries")
    if entries:
        for entry in entries:
            if isinstance(entry, dict):
                return entry
    return info


def _as_text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _largest_video(workdir: Path) -> Path | None:
    candidates = [
        path
        for path in workdir.iterdir()
        if path.is_file() and path.suffix.lower() in _VIDEO_SUFFIXES
    ]
    return max(candidates, key=lambda path: path.stat().st_size, default=None)


class YtDlpDownloader:
    def __init__(
        self,
        *,
        cookies_file: Path | None,
        cookies_from_browser: str | None,
        max_duration_seconds: int,
    ) -> None:
        self._cookies_file = cookies_file
        self._cookies_from_browser = cookies_from_browser
        self._max_duration_seconds = max_duration_seconds

    def _params(self, workdir: Path) -> dict[str, Any]:
        params: dict[str, Any] = {
            "outtmpl": str(workdir / "%(id)s.%(ext)s"),
            # A single progressive file needs no ffmpeg merge; fall back to
            # merged streams when ffmpeg is installed.
            "format": "b[ext=mp4]/b/bv*+ba",
            "noplaylist": False,
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "logger": _SilentLogger(),
        }
        if self._cookies_file is not None:
            params["cookiefile"] = str(self._cookies_file)
        if self._cookies_from_browser:
            params["cookiesfrombrowser"] = (self._cookies_from_browser,)
        return params

    def download(self, url: str, workdir: Path) -> DownloadedReel:
        import yt_dlp
        from yt_dlp.utils import DownloadError, match_filter_func

        params = self._params(workdir)
        # Over-long videos are skipped by yt-dlp itself (no download, no error).
        params["match_filter"] = match_filter_func(
            f"!duration | duration <= {self._max_duration_seconds}"
        )
        try:
            with yt_dlp.YoutubeDL(params) as ydl:
                info = ydl.extract_info(url, download=True)
        except DownloadError as exc:
            raise classify_download_error(str(exc)) from None

        meta = _first_entry(info) if isinstance(info, dict) else {}
        video = _largest_video(workdir)
        if video is None:
            duration = meta.get("duration")
            if isinstance(duration, int | float) and duration > self._max_duration_seconds:
                raise MediaTooLongError()
            raise MediaUnavailableError()
        return DownloadedReel(
            video_path=video,
            caption=_as_text(meta.get("description")),
            author=_as_text(meta.get("uploader")) or _as_text(meta.get("channel")),
            title=_as_text(meta.get("title")),
        )
