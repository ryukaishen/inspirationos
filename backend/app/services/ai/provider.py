"""Provider-agnostic LLM interface (M6).

`LLMProvider.generate_raw` returns the provider's raw structured attempt as a
JSON string plus usage/latency; parsing, validation, the single repair retry,
budget checks, and `ai_requests` logging all live in `structured.py` so every
provider gets identical semantics. Switching providers is configuration-only
(see `factory.py`).
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel


class ModelTier(enum.Enum):
    generation = "generation"
    fast = "fast"


@dataclass(frozen=True)
class RawGeneration:
    """One raw provider response: JSON text + usage. Never logged."""

    text: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int


class ProviderError(Exception):
    """Base class for provider-level failures."""


class ProviderNotConfiguredError(ProviderError):
    """Selected provider is missing required configuration (e.g. API key)."""


class LLMProvider(ABC):
    """A structured-output LLM backend. Implementations: anthropic, openai, mock."""

    name: str

    @abstractmethod
    def resolve_model(self, tier: ModelTier) -> str:
        """Model identifier used for the given tier (after settings overrides)."""

    @abstractmethod
    def generate_raw(
        self,
        *,
        task: str,
        instructions: str,
        context: dict[str, Any],
        schema: type[BaseModel],
        model: str,
    ) -> RawGeneration:
        """One structured-output attempt. Returns raw JSON text; must not
        raise on schema-invalid output (validation happens centrally)."""
