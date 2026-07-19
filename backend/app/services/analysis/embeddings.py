"""Embedding providers (M6): local fastembed (default), OpenAI, and a
deterministic mock for tests/CI.

The pgvector column is fixed at 384 dimensions, so every provider must emit
384-dim vectors (the OpenAI adapter requests dimensions=384). Embedding input
is the item's real text only — items with no text at all are never embedded,
which keeps the anti-hallucination invariant: nothing without text ever enters
semantic analysis.
"""

from __future__ import annotations

import hashlib
import re
from typing import Protocol

import numpy as np

from app.config import AppConfig
from app.models.item import Item
from app.services.ai.provider import ProviderNotConfiguredError

EMBEDDING_DIM = 384

MOCK_EMBEDDING_MODEL = "mock-embedding-v1"

_TOKEN_RE = re.compile(r"[a-z0-9]+")


class EmbeddingProvider(Protocol):
    model_name: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def embedding_text_for(item: Item) -> str | None:
    """The text an item is embedded from: every real text field it carries,
    concatenated. Returns None when the item has no text at all."""
    parts = [item.share_text, item.adjacent_text, item.enriched_caption, item.context_note]
    joined = "\n".join(part.strip() for part in parts if part is not None and part.strip())
    return joined or None


class FastembedEmbeddingProvider:
    """Local ONNX embeddings via fastembed. The model file is downloaded once
    on first use (an infra download — no user data leaves the machine); loading
    is lazy so constructing the provider for its model_name stays cheap."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self._model: object | None = None

    def embed(self, texts: list[str]) -> list[list[float]]:
        from fastembed import TextEmbedding

        if self._model is None:
            self._model = TextEmbedding(model_name=self.model_name)
        model: TextEmbedding = self._model  # type: ignore[assignment]
        return [np.asarray(vector, dtype=np.float64).tolist() for vector in model.embed(texts)]


class OpenAIEmbeddingProvider:
    """OpenAI embeddings shortened to 384 dims to fit the pgvector column."""

    def __init__(self, *, api_key: str | None, model_name: str) -> None:
        if not api_key:
            raise ProviderNotConfiguredError("OPENAI_API_KEY is not set")
        from openai import OpenAI

        self.model_name = model_name
        self._client = OpenAI(api_key=api_key)

    def embed(self, texts: list[str]) -> list[list[float]]:
        response = self._client.embeddings.create(
            model=self.model_name, input=texts, dimensions=EMBEDDING_DIM
        )
        return [list(entry.embedding) for entry in response.data]


class MockEmbeddingProvider:
    """Deterministic, offline: each vector is the normalized sum of per-token
    sha256-seeded unit vectors, so texts sharing vocabulary are cosine-close.
    Used by tests/CI so cluster memberships are exactly assertable."""

    model_name = MOCK_EMBEDDING_MODEL

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector_for(text).tolist() for text in texts]

    @staticmethod
    def _token_vector(token: str) -> np.ndarray:
        seed = int.from_bytes(hashlib.sha256(token.encode("utf-8")).digest()[:8], "big")
        rng = np.random.default_rng(seed)
        vector = rng.standard_normal(EMBEDDING_DIM)
        return vector / np.linalg.norm(vector)

    def _vector_for(self, text: str) -> np.ndarray:
        tokens = _TOKEN_RE.findall(text.lower())
        if not tokens:
            tokens = ["empty"]
        total = np.zeros(EMBEDDING_DIM)
        for token in tokens:
            total += self._token_vector(token)
        norm = float(np.linalg.norm(total))
        if norm == 0.0:
            return self._token_vector("empty")
        return total / norm


def get_embedding_provider(config: AppConfig) -> EmbeddingProvider:
    if config.embedding_provider == "local":
        return FastembedEmbeddingProvider(config.embedding_model)
    if config.embedding_provider == "openai":
        return OpenAIEmbeddingProvider(
            api_key=config.openai_api_key, model_name=config.openai_embedding_model
        )
    if config.embedding_provider == "mock":
        return MockEmbeddingProvider()
    raise ProviderNotConfiguredError(
        f"unknown embedding provider {config.embedding_provider!r} (local|openai|mock)"
    )
