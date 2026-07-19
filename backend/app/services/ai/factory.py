"""Config-only provider selection.

Effective provider = `settings.ai_provider` (DB singleton, seeded `mock`,
switched via the Settings UI); the AI_PROVIDER env value is only the fallback
when the row is missing. Model names resolve as: settings.model_overrides
("generation"/"fast" keys) → provider-specific env defaults. API keys are
env-only and never pass through the DB or the API.
"""

from __future__ import annotations

from app.config import AppConfig
from app.models.app_settings import AiProvider, AppSettings
from app.services.ai.anthropic_provider import AnthropicProvider
from app.services.ai.mock_provider import MockProvider
from app.services.ai.openai_provider import OpenAIProvider
from app.services.ai.provider import LLMProvider, ProviderNotConfiguredError


def get_llm_provider(settings: AppSettings | None, config: AppConfig) -> LLMProvider:
    provider_name = settings.ai_provider.value if settings is not None else config.ai_provider
    overrides = settings.model_overrides if settings is not None else {}
    generation_override = overrides.get("generation") or None
    fast_override = overrides.get("fast") or None

    if provider_name == AiProvider.mock.value:
        return MockProvider()
    if provider_name == AiProvider.anthropic.value:
        return AnthropicProvider(
            api_key=config.anthropic_api_key,
            generation_model=generation_override or config.anthropic_generation_model,
            fast_model=fast_override or config.anthropic_fast_model,
            max_output_tokens=config.ai_max_output_tokens,
        )
    if provider_name == AiProvider.openai.value:
        return OpenAIProvider(
            api_key=config.openai_api_key,
            generation_model=generation_override or config.openai_generation_model,
            fast_model=fast_override or config.openai_fast_model,
            max_output_tokens=config.ai_max_output_tokens,
        )
    raise ProviderNotConfiguredError(f"unknown AI provider {provider_name!r}")
