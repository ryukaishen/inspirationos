"""Reel media extraction: download -> transcribe -> on-screen text -> item text.

Operator-run on the host via `python -m app.cli transcribe-reels` (never by the
worker, never automatically). The orchestration in `pipeline.py` is pure and
takes its downloader/transcriber/frame reader as injected protocols, so the
heavy optional dependencies (yt-dlp, faster-whisper, Pillow) are imported only
inside the real adapters and the suite runs without them.
"""
