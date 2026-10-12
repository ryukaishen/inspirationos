"""On-screen text reader: sampled frames -> Claude vision -> plain text.

Used only for reels with little or no speech (text-on-screen reels, slides,
code, diagrams). Every call is budget-checked first and leaves a content-free
`ai_requests` audit row, like every other provider call in the app. The
response text is returned to the caller and never logged.
"""

from __future__ import annotations

import base64
import time
from typing import Any

from sqlalchemy.orm import Session

from app.config import AppConfig
from app.models.ai_request import AiRequest, AiRequestStatus
from app.models.app_settings import AppSettings
from app.services.ai import budget

TASK = "reel_visual_text"
NO_TEXT_SENTINEL = "NONE"
MAX_OUTPUT_TOKENS = 2048

INSTRUCTIONS = (
    "The images are frames sampled in order from one short social-media video.\n"
    "1. Transcribe all readable on-screen text verbatim (titles, captions, lists,"
    " steps, code, tool or product names, URLs), in reading order, without"
    " repeating text that appears in several frames.\n"
    "2. If a frame shows a diagram, app UI, chart, or code editor, add one to"
    " three factual sentences starting with 'Visual:' describing what it shows.\n"
    "Only report what is visible — never guess what the video is about.\n"
    f"If there is no readable text and nothing informative to describe, reply"
    f" exactly {NO_TEXT_SENTINEL}."
)


class AnthropicFrameReader:
    def __init__(self, session: Session, config: AppConfig, client: Any) -> None:
        self._session = session
        self._config = config
        self._client = client
        self._model = config.anthropic_fast_model

    def _record(
        self,
        *,
        status: AiRequestStatus,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        latency_ms: int = 0,
    ) -> None:
        self._session.add(
            AiRequest(
                job_id=None,
                provider="anthropic",
                model=self._model,
                task=TASK,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                est_cost_usd=budget.estimate_cost_usd(
                    "anthropic", self._model, prompt_tokens, completion_tokens
                ),
                latency_ms=latency_ms,
                status=status,
            )
        )
        self._session.commit()

    def read_frames(self, frames: list[bytes]) -> str:
        settings = self._session.get(AppSettings, 1)
        budget.check_monthly_budget(self._session, settings, self._config)

        content: list[dict[str, Any]] = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": base64.standard_b64encode(frame).decode("ascii"),
                },
            }
            for frame in frames
        ]
        content.append({"type": "text", "text": "Extract the on-screen text."})

        started = time.monotonic()
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=MAX_OUTPUT_TOKENS,
                system=INSTRUCTIONS,
                messages=[{"role": "user", "content": content}],
            )
        except Exception:
            self._record(
                status=AiRequestStatus.error,
                latency_ms=int((time.monotonic() - started) * 1000),
            )
            raise
        self._record(
            status=AiRequestStatus.success,
            prompt_tokens=int(response.usage.input_tokens),
            completion_tokens=int(response.usage.output_tokens),
            latency_ms=int((time.monotonic() - started) * 1000),
        )

        if response.stop_reason == "refusal":
            return ""
        text = "".join(
            str(block.text) for block in response.content if block.type == "text"
        ).strip()
        return "" if text == NO_TEXT_SENTINEL else text
