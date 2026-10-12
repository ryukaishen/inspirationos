"""Evenly spaced JPEG frames from a video, via PyAV + Pillow (optional
`media` extra; PyAV is installed by faster-whisper). Frames are held in
memory only and downscaled so the vision call stays cheap."""

from __future__ import annotations

import io
from pathlib import Path

MAX_FRAME_EDGE_PX = 1024
JPEG_QUALITY = 80


def sample_frames(video_path: Path, count: int) -> list[bytes]:
    import av

    frames: list[bytes] = []
    with av.open(str(video_path)) as container:
        if not container.streams.video or count <= 0:
            return frames
        stream = container.streams.video[0]
        if stream.duration is not None and stream.time_base is not None:
            duration = float(stream.duration * stream.time_base)
        elif container.duration is not None:
            duration = container.duration / av.time_base
        else:
            duration = 0.0

        # Midpoints of `count` equal slices: skips black first/last frames.
        for index in range(count):
            target_seconds = duration * (index + 0.5) / count
            if stream.time_base is not None:
                container.seek(int(target_seconds / stream.time_base), stream=stream)
            # Seeking lands on the keyframe at or before the target; decode
            # forward to the first frame at the target time.
            frame = None
            for candidate in container.decode(stream):
                frame = candidate
                if candidate.time is None or candidate.time >= target_seconds:
                    break
            if frame is None:
                continue
            image = frame.to_image()  # type: ignore[no-untyped-call,unused-ignore]
            image.thumbnail((MAX_FRAME_EDGE_PX, MAX_FRAME_EDGE_PX))
            buffer = io.BytesIO()
            image.convert("RGB").save(buffer, format="JPEG", quality=JPEG_QUALITY)
            frames.append(buffer.getvalue())
    return frames
