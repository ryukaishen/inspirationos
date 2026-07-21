"""LLM provider contracts (M6), no services and no live keys anywhere.

MockProvider: determinism + schema validity. Repair loop: canned bad outputs
against `generate_validated` with a fake session (unit-level — the worker-level
failure path is covered in tests/workers/test_analysis_jobs.py). Anthropic and
OpenAI adapters: respx contract tests over faked HTTP — respx also guarantees
zero real network calls (unmatched requests raise).
"""

import json

import httpx
import pytest
import respx

from app.config import AppConfig
from app.models.app_settings import AiProvider, AppSettings
from app.services.ai.anthropic_provider import RESULT_TOOL_NAME, AnthropicProvider
from app.services.ai.factory import get_llm_provider
from app.services.ai.mock_provider import MOCK_MODEL, MockProvider
from app.services.ai.openai_provider import OpenAIProvider
from app.services.ai.provider import (
    LLMProvider,
    ModelTier,
    ProviderError,
    ProviderNotConfiguredError,
    RawGeneration,
)
from app.services.ai.schemas import (
    TASK_ADVISOR_REVIEW,
    TASK_CLUSTER_LABEL,
    TASK_COMBINE_PROJECTS,
    TASK_GENERATE_PROJECTS,
    TASK_TOPIC_EXTRACTION,
    AdvisorReview,
    ClusterLabel,
    CombinedProject,
    ProjectIdeas,
    ProjectScores,
    TopicExtraction,
)
from app.services.ai.structured import StructuredOutputError, generate_validated

TOPIC_CONTEXT = {
    "items": [
        {"item_id": 11, "text": "homemade pasta sauce recipe tonight"},
        {"item_id": 12, "text": "leg day gym workout routine"},
    ]
}
LABEL_CONTEXT = {
    "items": [
        {"item_id": 11, "text": "homemade pasta sauce recipe"},
        {"item_id": 12, "text": "fresh pasta sauce ideas"},
    ]
}


def _config(**overrides: object) -> AppConfig:
    return AppConfig(_env_file=None, **overrides)  # type: ignore[arg-type]


class FakeSession:
    """Just enough Session surface for generate_validated in a unit test:
    no settings row, zero prior spend, records added ai_requests rows."""

    def __init__(self) -> None:
        self.added: list[object] = []

    def get(self, model: type, pk: int) -> None:
        return None

    def scalar(self, stmt: object) -> int:
        return 0

    def add(self, obj: object) -> None:
        self.added.append(obj)

    def commit(self) -> None:
        pass


# --- MockProvider ------------------------------------------------------------


def test_mock_provider_is_deterministic() -> None:
    provider = MockProvider()
    first = provider.generate_raw(
        task=TASK_TOPIC_EXTRACTION,
        instructions="x",
        context=TOPIC_CONTEXT,
        schema=TopicExtraction,
        model=MOCK_MODEL,
    )
    second = provider.generate_raw(
        task=TASK_TOPIC_EXTRACTION,
        instructions="x",
        context=TOPIC_CONTEXT,
        schema=TopicExtraction,
        model=MOCK_MODEL,
    )
    assert first.text == second.text


def test_mock_topic_extraction_is_schema_valid_and_echoes_ids() -> None:
    raw = MockProvider().generate_raw(
        task=TASK_TOPIC_EXTRACTION,
        instructions="x",
        context=TOPIC_CONTEXT,
        schema=TopicExtraction,
        model=MOCK_MODEL,
    )
    parsed = TopicExtraction.model_validate(json.loads(raw.text))
    assert [a.item_id for a in parsed.assignments] == [11, 12]
    for assignment in parsed.assignments:
        assert assignment.topics
        for topic in assignment.topics:
            assert 0.0 <= topic.confidence <= 1.0


def test_mock_cluster_label_derives_from_shared_tokens() -> None:
    raw = MockProvider().generate_raw(
        task=TASK_CLUSTER_LABEL,
        instructions="x",
        context=LABEL_CONTEXT,
        schema=ClusterLabel,
        model=MOCK_MODEL,
    )
    parsed = ClusterLabel.model_validate(json.loads(raw.text))
    assert "Pasta" in parsed.label
    assert parsed.description_md


GENERATE_CONTEXT = {
    "items": [
        {"item_id": 21, "text": "sourdough starter feeding schedule tips"},
        {"item_id": 22, "text": "sourdough scoring patterns for beginners"},
        {"item_id": 23, "text": "bouldering grip strength training plan"},
        {"item_id": 24, "text": "bouldering footwork drills session"},
    ],
    "clusters": [
        {"cluster_id": 5, "label": "Sourdough", "description": "Bread items"},
        {"cluster_id": 6, "label": "Bouldering", "description": "Climbing items"},
    ],
    "career_profile": {"target_domains": ["data science", "applied ai"]},
    "count": 2,
}
COMBINE_CONTEXT = {
    "parents": [
        {
            "project_id": 1,
            "title": "Sourdough Tracker",
            "one_liner": "Track starter health",
            "domains": ["data science"],
            "tech_stack": ["python"],
            "skills_demonstrated": ["time series"],
        },
        {
            "project_id": 2,
            "title": "Climb Coach",
            "one_liner": "Grade climbing sessions",
            "domains": ["applied ai"],
            "tech_stack": ["python", "postgres"],
            "skills_demonstrated": ["classification"],
        },
    ],
    "career_profile": {"target_domains": ["data science"]},
}
ADVISOR_CONTEXT = {
    "project": {
        "title": "Sourdough Tracker",
        "one_liner": "Track starter health over time",
        "summary_md": "Track sourdough starter fermentation with sensors.",
    },
    "library": [{"project_id": 2, "title": "Climb Coach", "one_liner": "Grade sessions"}],
    "career_profile": {"target_domains": ["data science"]},
}


def test_mock_generate_projects_is_schema_valid_and_grounded() -> None:
    raw = MockProvider().generate_raw(
        task=TASK_GENERATE_PROJECTS,
        instructions="x",
        context=GENERATE_CONTEXT,
        schema=ProjectIdeas,
        model=MOCK_MODEL,
    )
    parsed = ProjectIdeas.model_validate(json.loads(raw.text))
    assert len(parsed.ideas) == 2
    given_item_ids = {21, 22, 23, 24}
    for idea in parsed.ideas:
        assert idea.source_item_ids
        assert set(idea.source_item_ids) <= given_item_ids
        assert set(idea.source_cluster_ids) == {5, 6}
        for dimension in ProjectScores.model_fields:
            sub_score = getattr(idea.scores, dimension)
            assert 0.0 <= sub_score.score <= 10.0
            assert sub_score.rationale
    # Career-profile domains flow into the ideas.
    assert parsed.ideas[0].domains == ["data science", "applied ai"]


def test_mock_generate_projects_is_deterministic() -> None:
    provider = MockProvider()
    kwargs: dict = {
        "task": TASK_GENERATE_PROJECTS,
        "instructions": "x",
        "context": GENERATE_CONTEXT,
        "schema": ProjectIdeas,
        "model": MOCK_MODEL,
    }
    assert provider.generate_raw(**kwargs).text == provider.generate_raw(**kwargs).text


def test_mock_generate_projects_requires_items() -> None:
    with pytest.raises(ProviderError):
        MockProvider().generate_raw(
            task=TASK_GENERATE_PROJECTS,
            instructions="x",
            context={"items": [], "count": 1},
            schema=ProjectIdeas,
            model=MOCK_MODEL,
        )


def test_mock_combine_projects_merges_both_parents() -> None:
    raw = MockProvider().generate_raw(
        task=TASK_COMBINE_PROJECTS,
        instructions="x",
        context=COMBINE_CONTEXT,
        schema=CombinedProject,
        model=MOCK_MODEL,
    )
    parsed = CombinedProject.model_validate(json.loads(raw.text))
    assert "Sourdough Tracker" in parsed.title
    assert "Climb Coach" in parsed.title
    # Union of both parents' stacks.
    assert set(parsed.tech_stack) == {"python", "postgres"}
    assert set(parsed.domains) == {"data science", "applied ai"}


def test_mock_advisor_review_has_all_five_sections() -> None:
    raw = MockProvider().generate_raw(
        task=TASK_ADVISOR_REVIEW,
        instructions="x",
        context=ADVISOR_CONTEXT,
        schema=AdvisorReview,
        model=MOCK_MODEL,
    )
    parsed = AdvisorReview.model_validate(json.loads(raw.text))
    assert parsed.commonality.verdict in {"very_common", "common", "uncommon", "novel"}
    assert parsed.commonality.reasoning
    assert parsed.comparative_strength
    assert parsed.recruiter_impact
    assert parsed.prerequisites
    assert parsed.week_by_week
    assert [entry.week for entry in parsed.week_by_week] == sorted(
        entry.week for entry in parsed.week_by_week
    )


def test_mock_provider_rejects_unknown_task() -> None:
    with pytest.raises(ProviderError):
        MockProvider().generate_raw(
            task="no_such_task",
            instructions="x",
            context={},
            schema=ClusterLabel,
            model=MOCK_MODEL,
        )


# --- Validation + repair loop ------------------------------------------------


class ScriptedProvider(LLMProvider):
    """Returns canned outputs in order; counts calls."""

    name = "scripted"

    def __init__(self, outputs: list[str]) -> None:
        self._outputs = outputs
        self.calls = 0
        self.instructions_seen: list[str] = []

    def resolve_model(self, tier: ModelTier) -> str:
        return "scripted-model"

    def generate_raw(self, *, task, instructions, context, schema, model) -> RawGeneration:  # type: ignore[no-untyped-def]
        self.instructions_seen.append(instructions)
        text = self._outputs[min(self.calls, len(self._outputs) - 1)]
        self.calls += 1
        return RawGeneration(text=text, prompt_tokens=10, completion_tokens=5, latency_ms=1)


GOOD_LABEL = json.dumps({"label": "Pasta", "description_md": "About pasta."})


def test_repair_retry_recovers_from_one_bad_output() -> None:
    provider = ScriptedProvider(["{not valid json", GOOD_LABEL])
    session = FakeSession()
    result = generate_validated(
        session,  # type: ignore[arg-type]
        provider,
        task=TASK_CLUSTER_LABEL,
        context=LABEL_CONTEXT,
        schema=ClusterLabel,
        model="scripted-model",
        config=_config(),
    )
    assert result.label == "Pasta"
    assert provider.calls == 2
    # The repair prompt carries the validation errors back to the provider.
    assert "failed validation" in provider.instructions_seen[1]
    statuses = [request.status.value for request in session.added]
    assert statuses == ["invalid_output", "success"]


def test_double_malformed_output_raises_after_exactly_two_calls() -> None:
    provider = ScriptedProvider(['{"label": ""}', '{"wrong_field": 1}'])
    session = FakeSession()
    with pytest.raises(StructuredOutputError):
        generate_validated(
            session,  # type: ignore[arg-type]
            provider,
            task=TASK_CLUSTER_LABEL,
            context=LABEL_CONTEXT,
            schema=ClusterLabel,
            model="scripted-model",
            config=_config(),
        )
    assert provider.calls == 2
    statuses = [request.status.value for request in session.added]
    assert statuses == ["invalid_output", "invalid_output"]


# --- Anthropic adapter (respx contract; no live key) --------------------------

ANTHROPIC_RESPONSE = {
    "id": "msg_test",
    "type": "message",
    "role": "assistant",
    "model": "claude-haiku-4-5",
    "content": [
        {
            "type": "tool_use",
            "id": "toolu_test",
            "name": RESULT_TOOL_NAME,
            "input": {"label": "Pasta", "description_md": "About pasta."},
        }
    ],
    "stop_reason": "tool_use",
    "stop_sequence": None,
    "usage": {"input_tokens": 120, "output_tokens": 30},
}


def test_anthropic_provider_requires_api_key() -> None:
    with pytest.raises(ProviderNotConfiguredError):
        AnthropicProvider(api_key=None, generation_model="g", fast_model="f", max_output_tokens=100)


@respx.mock
def test_anthropic_contract_forced_tool_use() -> None:
    route = respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(200, json=ANTHROPIC_RESPONSE)
    )
    provider = AnthropicProvider(
        api_key="test-key-not-real",
        generation_model="claude-sonnet-5",
        fast_model="claude-haiku-4-5",
        max_output_tokens=1234,
    )
    raw = provider.generate_raw(
        task=TASK_CLUSTER_LABEL,
        instructions="label the cluster",
        context=LABEL_CONTEXT,
        schema=ClusterLabel,
        model=provider.resolve_model(ModelTier.fast),
    )

    request = route.calls.last.request
    assert request.headers["x-api-key"] == "test-key-not-real"
    assert "anthropic-version" in request.headers
    body = json.loads(request.content)
    assert body["model"] == "claude-haiku-4-5"
    assert body["max_tokens"] == 1234
    assert body["system"] == "label the cluster"
    assert body["tool_choice"] == {"type": "tool", "name": RESULT_TOOL_NAME}
    assert body["tools"][0]["input_schema"] == ClusterLabel.model_json_schema()
    # The user message is the JSON context, not free text.
    assert json.loads(body["messages"][0]["content"]) == LABEL_CONTEXT

    assert ClusterLabel.model_validate(json.loads(raw.text)).label == "Pasta"
    assert raw.prompt_tokens == 120
    assert raw.completion_tokens == 30


@respx.mock
def test_anthropic_missing_tool_block_yields_unparseable_text() -> None:
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            200,
            json={
                **ANTHROPIC_RESPONSE,
                "content": [{"type": "text", "text": "I refuse to use the tool."}],
                "stop_reason": "end_turn",
            },
        )
    )
    provider = AnthropicProvider(
        api_key="test-key-not-real",
        generation_model="g",
        fast_model="claude-haiku-4-5",
        max_output_tokens=100,
    )
    raw = provider.generate_raw(
        task=TASK_CLUSTER_LABEL,
        instructions="x",
        context=LABEL_CONTEXT,
        schema=ClusterLabel,
        model="claude-haiku-4-5",
    )
    with pytest.raises(json.JSONDecodeError):
        json.loads(raw.text)


# --- OpenAI adapter (respx contract; no live key) -----------------------------


def test_openai_provider_requires_api_key() -> None:
    with pytest.raises(ProviderNotConfiguredError):
        OpenAIProvider(api_key=None, generation_model="g", fast_model="f", max_output_tokens=100)


@respx.mock
def test_openai_contract_json_schema_response_format() -> None:
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "created": 1,
                "model": "gpt-5-mini",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": GOOD_LABEL},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 77, "completion_tokens": 9, "total_tokens": 86},
            },
        )
    )
    provider = OpenAIProvider(
        api_key="test-key-not-real",
        generation_model="gpt-5.2",
        fast_model="gpt-5-mini",
        max_output_tokens=999,
    )
    raw = provider.generate_raw(
        task=TASK_CLUSTER_LABEL,
        instructions="label the cluster",
        context=LABEL_CONTEXT,
        schema=ClusterLabel,
        model=provider.resolve_model(ModelTier.fast),
    )

    request = route.calls.last.request
    assert request.headers["authorization"] == "Bearer test-key-not-real"
    body = json.loads(request.content)
    assert body["model"] == "gpt-5-mini"
    assert body["max_completion_tokens"] == 999
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["name"] == TASK_CLUSTER_LABEL
    assert body["response_format"]["json_schema"]["schema"] == ClusterLabel.model_json_schema()
    assert body["messages"][0] == {"role": "system", "content": "label the cluster"}

    assert ClusterLabel.model_validate(json.loads(raw.text)).label == "Pasta"
    assert raw.prompt_tokens == 77
    assert raw.completion_tokens == 9


# --- Factory: configuration-only switching ------------------------------------


def _settings(provider: AiProvider, overrides: dict[str, str] | None = None) -> AppSettings:
    return AppSettings(ai_provider=provider, model_overrides=overrides or {})


def test_factory_returns_mock_by_default_settings() -> None:
    provider = get_llm_provider(_settings(AiProvider.mock), _config())
    assert isinstance(provider, MockProvider)


def test_factory_switches_to_anthropic_with_settings_alone() -> None:
    config = _config(anthropic_api_key="test-key-not-real")
    provider = get_llm_provider(_settings(AiProvider.anthropic), config)
    assert isinstance(provider, AnthropicProvider)
    assert provider.resolve_model(ModelTier.generation) == "claude-sonnet-5"
    assert provider.resolve_model(ModelTier.fast) == "claude-haiku-4-5"


def test_factory_applies_model_overrides() -> None:
    config = _config(openai_api_key="test-key-not-real")
    provider = get_llm_provider(
        _settings(AiProvider.openai, {"generation": "gpt-custom", "fast": "gpt-tiny"}), config
    )
    assert provider.resolve_model(ModelTier.generation) == "gpt-custom"
    assert provider.resolve_model(ModelTier.fast) == "gpt-tiny"


def test_factory_raises_without_key_for_real_provider() -> None:
    with pytest.raises(ProviderNotConfiguredError):
        get_llm_provider(_settings(AiProvider.anthropic), _config(anthropic_api_key=None))


def test_factory_falls_back_to_env_provider_without_settings_row() -> None:
    provider = get_llm_provider(None, _config(ai_provider="mock"))
    assert isinstance(provider, MockProvider)
