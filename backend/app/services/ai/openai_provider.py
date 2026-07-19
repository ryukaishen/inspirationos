"""OpenAI adapter: structured output via json_schema response_format.

Same central validation/repair semantics as every provider (structured.py).
API key from the environment only. The SDK is httpx-based, so respx contract
tests intercept it without live keys.
"""

from __future__ import annotations

import json
import time
from typing import Any

from openai import OpenAI
from pydantic import BaseModel

from app.services.ai.provider import (
    LLMProvider,
    ModelTier,
    ProviderNotConfiguredError,
    RawGeneration,
)


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(
        self,
        *,
        api_key: str | None,
        generation_model: str,
        fast_model: str,
        max_output_tokens: int,
    ) -> None:
        if not api_key:
            raise ProviderNotConfiguredError("OPENAI_API_KEY is not set")
        self._client = OpenAI(api_key=api_key)
        self._models = {ModelTier.generation: generation_model, ModelTier.fast: fast_model}
        self._max_output_tokens = max_output_tokens

    def resolve_model(self, tier: ModelTier) -> str:
        return self._models[tier]

    def generate_raw(
        self,
        *,
        task: str,
        instructions: str,
        context: dict[str, Any],
        schema: type[BaseModel],
        model: str,
    ) -> RawGeneration:
        started = time.monotonic()
        response = self._client.chat.completions.create(
            model=model,
            max_completion_tokens=self._max_output_tokens,
            messages=[
                {"role": "system", "content": instructions},
                {
                    "role": "user",
                    "content": json.dumps(context, sort_keys=True, ensure_ascii=False),
                },
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": task, "schema": schema.model_json_schema()},
            },
        )
        latency_ms = int((time.monotonic() - started) * 1000)
        text = response.choices[0].message.content or ""
        usage = response.usage
        return RawGeneration(
            text=text,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            latency_ms=latency_ms,
        )
