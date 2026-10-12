"""Local speech-to-text via faster-whisper (optional `media` extra).

Runs entirely on the operator's machine — audio never leaves it. The model
(`small` by default) is downloaded once by faster-whisper on first use.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def has_audio_stream(media_path: Path) -> bool:
    import av

    with av.open(str(media_path)) as container:
        return len(container.streams.audio) > 0


class FasterWhisperTranscriber:
    def __init__(self, model_size: str) -> None:
        self._model_size = model_size
        self._model: Any = None

    def transcribe(self, media_path: Path) -> str:
        # Silent/music-free text reels have no audio track at all; that's an
        # empty transcript, not a failure to retry.
        if not has_audio_stream(media_path):
            return ""
        if self._model is None:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(self._model_size, device="auto", compute_type="int8")
        segments, _info = self._model.transcribe(str(media_path), vad_filter=True)
        return " ".join(str(segment.text).strip() for segment in segments).strip()
