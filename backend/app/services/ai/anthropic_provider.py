"""Anthropic adapter: structured output via a single forced tool call.

The task schema's JSON schema becomes the tool's input_schema and tool_choice
forces that tool, so the model's entire answer is the tool input — parsed and
validated centrally in structured.py. The API key comes from the environment
only (never the DB); instructions go in `system`, the JSON context in the user
message. The SDK uses httpx underneath, so respx contract tests intercept it
without live keys.
"""

from __future__ import annotations

import json
import time
from typing import Any

import anthropic
from pydantic import BaseModel

from app.services.ai.provider import (
    LLMProvider,
    ModelTier,
    ProviderNotConfiguredError,
    RawGeneration,
)

RESULT_TOOL_NAME = "emit_result"


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(
        self,
        *,
        api_key: str | None,
        generation_model: str,
        fast_model: str,
        max_output_tokens: int,
    ) -> None:
        if not api_key:
            raise ProviderNotConfiguredError("ANTHROPIC_API_KEY is not set")
        self._client = anthropic.Anthropic(api_key=api_key)
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
        response = self._client.messages.create(
            model=model,
            max_tokens=self._max_output_tokens,
            system=instructions,
            messages=[
                {
                    "role": "user",
                    "content": json.dumps(context, sort_keys=True, ensure_ascii=False),
                }
            ],
            tools=[
                {
                    "name": RESULT_TOOL_NAME,
                    "description": f"Record the {task} result.",
                    "input_schema": schema.model_json_schema(),
                }
            ],
            tool_choice={"type": "tool", "name": RESULT_TOOL_NAME},
        )
        latency_ms = int((time.monotonic() - started) * 1000)
        tool_input: object = next(
            (block.input for block in response.content if block.type == "tool_use"), None
        )
        # A missing tool block yields unparseable text -> the central repair path.
        text = json.dumps(tool_input) if tool_input is not None else ""
        return RawGeneration(
            text=text,
            prompt_tokens=response.usage.input_tokens,
            completion_tokens=response.usage.output_tokens,
            latency_ms=latency_ms,
        )
