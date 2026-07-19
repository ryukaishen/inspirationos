"""Deterministic offline LLM provider — the dev/CI default.

Outputs are derived purely from the task + input context (token frequency and
sha256 hashes), so identical inputs always produce identical, schema-valid
results with zero network I/O and zero cost. Topic names and labels come from
the most frequent meaningful tokens of the input texts, which makes fixture
assertions readable ("pasta cooking" rather than an opaque hash).
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections import Counter
from typing import Any

from pydantic import BaseModel

from app.services.ai.provider import LLMProvider, ModelTier, ProviderError, RawGeneration
from app.services.ai.schemas import (
    TASK_CLUSTER_LABEL,
    TASK_TOPIC_EXTRACTION,
    ClusterLabel,
    ItemTopics,
    TopicAssignmentEntry,
    TopicExtraction,
)

MOCK_MODEL = "mock-llm-v1"

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    [
        *("a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from"),
        *("has", "have", "if", "in", "into", "is", "it", "its", "of", "on", "or"),
        *("so", "that", "the", "this", "to", "was", "were", "will", "with", "you"),
        *("your", "check", "out", "look", "reel", "post", "video", "synthetic"),
        *("run", "marker", "about"),
    ]
)


def _meaningful_tokens(text: str) -> list[str]:
    return [
        token
        for token in _TOKEN_RE.findall(text.lower())
        if len(token) >= 3 and token not in _STOPWORDS
    ]


def _top_tokens(texts: list[str], count: int) -> list[str]:
    counter: Counter[str] = Counter()
    for text in texts:
        counter.update(_meaningful_tokens(text))
    # Deterministic order: frequency desc, then alphabetical.
    ranked = sorted(counter.items(), key=lambda pair: (-pair[1], pair[0]))
    return [token for token, _ in ranked[:count]]


def _confidence_for(seed: str) -> float:
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return round(0.6 + (digest[0] / 255) * 0.39, 3)


class MockProvider(LLMProvider):
    name = "mock"

    def resolve_model(self, tier: ModelTier) -> str:
        return MOCK_MODEL

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
        payload: BaseModel
        if task == TASK_TOPIC_EXTRACTION:
            payload = self._topic_extraction(context)
        elif task == TASK_CLUSTER_LABEL:
            payload = self._cluster_label(context)
        else:
            raise ProviderError(f"mock provider has no generator for task {task!r}")
        text = payload.model_dump_json()
        serialized_input = json.dumps(context, sort_keys=True, ensure_ascii=False)
        return RawGeneration(
            text=text,
            prompt_tokens=max(1, (len(instructions) + len(serialized_input)) // 4),
            completion_tokens=max(1, len(text) // 4),
            latency_ms=int((time.monotonic() - started) * 1000),
        )

    def _topic_extraction(self, context: dict[str, Any]) -> TopicExtraction:
        assignments: list[ItemTopics] = []
        for entry in context.get("items", []):
            text = str(entry.get("text", ""))
            tokens = _top_tokens([text], 2)
            names = [" ".join(tokens)] if tokens else ["uncategorized"]
            assignments.append(
                ItemTopics(
                    item_id=int(entry["item_id"]),
                    topics=[
                        TopicAssignmentEntry(
                            name=name, confidence=_confidence_for(f"topic:{name}:{text}")
                        )
                        for name in names
                    ],
                )
            )
        return TopicExtraction(assignments=assignments)

    def _cluster_label(self, context: dict[str, Any]) -> ClusterLabel:
        texts = [str(entry.get("text", "")) for entry in context.get("items", [])]
        tokens = _top_tokens(texts, 2)
        label = " ".join(tokens).title() if tokens else "Unlabeled Cluster"
        description = (
            f"Items in this cluster share text about {' and '.join(tokens)}."
            if tokens
            else "Items in this cluster carry no dominant shared vocabulary."
        )
        return ClusterLabel(label=label, description_md=description)
