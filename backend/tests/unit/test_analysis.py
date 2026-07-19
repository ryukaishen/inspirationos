"""Pure analysis units (M6): mock embeddings, clustering memberships,
near-duplicate components, and the anti-hallucination context assembly."""

import numpy as np
import pytest

from app.models.item import Item, ItemStatus, ItemType
from app.services.analysis.clustering import cluster_embeddings
from app.services.analysis.dedupe import near_duplicate_components
from app.services.analysis.embeddings import (
    EMBEDDING_DIM,
    MockEmbeddingProvider,
    embedding_text_for,
)
from app.services.analysis.topics import (
    GroundingError,
    build_llm_context_items,
    slugify,
    verify_echoed_item_ids,
)

PASTA_TEXTS = [
    "pasta sauce tomato dinner",
    "pasta sauce tomato recipe",
    "pasta sauce tomato cooking",
]
GYM_TEXTS = [
    "gym workout legs squat",
    "gym workout legs training",
    "gym workout legs routine",
]
OUTLIER_TEXT = "quantitative finance modeling paper"


def _item(item_id: int, **fields: object) -> Item:
    item = Item(
        url_raw=f"https://www.instagram.com/reel/UNIT{item_id}/",
        url_canonical=f"https://www.instagram.com/reel/UNIT{item_id}/",
        item_type=ItemType.reel,
        status=ItemStatus.new,
        **fields,  # type: ignore[arg-type]
    )
    item.id = item_id
    return item


# --- mock embeddings ---------------------------------------------------------


def test_mock_embeddings_are_deterministic_384_dim_unit_vectors() -> None:
    provider = MockEmbeddingProvider()
    first, second = provider.embed(["pasta sauce"]), provider.embed(["pasta sauce"])
    assert first == second
    assert len(first[0]) == EMBEDDING_DIM
    assert np.linalg.norm(first[0]) == pytest.approx(1.0)


def test_mock_embeddings_rank_shared_vocabulary_higher() -> None:
    provider = MockEmbeddingProvider()
    vectors = np.array(provider.embed([PASTA_TEXTS[0], PASTA_TEXTS[1], GYM_TEXTS[0]]))
    same_theme = float(vectors[0] @ vectors[1])
    cross_theme = float(vectors[0] @ vectors[2])
    assert same_theme > 0.6
    assert cross_theme < 0.3


def test_mock_embeddings_handle_empty_text() -> None:
    [vector] = MockEmbeddingProvider().embed([""])
    assert len(vector) == EMBEDDING_DIM


# --- clustering --------------------------------------------------------------


def test_cluster_embeddings_groups_themes_and_drops_singletons() -> None:
    provider = MockEmbeddingProvider()
    matrix = np.array(provider.embed([*PASTA_TEXTS, *GYM_TEXTS, OUTLIER_TEXT]))
    groups = cluster_embeddings(matrix, distance_threshold=0.4)
    assert groups == [[0, 1, 2], [3, 4, 5]]


def test_cluster_embeddings_needs_at_least_two_rows() -> None:
    provider = MockEmbeddingProvider()
    assert cluster_embeddings(np.array(provider.embed(["solo"])), distance_threshold=0.4) == []
    assert cluster_embeddings(np.empty((0, EMBEDDING_DIM)), distance_threshold=0.4) == []


# --- near duplicates ---------------------------------------------------------


def test_near_duplicate_components_group_identical_vocabulary() -> None:
    provider = MockEmbeddingProvider()
    matrix = np.array(
        provider.embed(
            [
                "amazing pasta recipe wow",
                "Amazing pasta recipe — wow!",  # same tokens, different punctuation
                "completely different subject entirely",
            ]
        )
    )
    assert near_duplicate_components(matrix, similarity_threshold=0.95) == [[0, 1]]


def test_near_duplicate_components_below_threshold_do_not_group() -> None:
    provider = MockEmbeddingProvider()
    matrix = np.array(provider.embed([PASTA_TEXTS[0], PASTA_TEXTS[1]]))  # ~0.75 similar
    assert near_duplicate_components(matrix, similarity_threshold=0.95) == []


# --- embedding text & anti-hallucination gate --------------------------------


def test_embedding_text_concatenates_all_real_text_fields() -> None:
    item = _item(1, share_text="share", adjacent_text="adjacent", context_note="note")
    item.enriched_caption = "caption"
    assert embedding_text_for(item) == "share\nadjacent\ncaption\nnote"


def test_embedding_text_is_none_without_any_text() -> None:
    assert embedding_text_for(_item(1)) is None
    assert embedding_text_for(_item(2, share_text="   ")) is None


def test_context_items_exclude_ineligible_and_truncate() -> None:
    eligible = _item(1, share_text="pasta " * 200)
    ineligible = _item(2)  # no text at all -> stays out of any LLM context
    context = build_llm_context_items([eligible, ineligible], max_chars_per_item=50, max_items=10)
    assert [entry["item_id"] for entry in context] == [1]
    assert len(context[0]["text"]) == 50


def test_context_items_cap_item_count() -> None:
    items = [_item(index, share_text=f"text {index}") for index in range(1, 6)]
    context = build_llm_context_items(items, max_chars_per_item=100, max_items=3)
    assert [entry["item_id"] for entry in context] == [1, 2, 3]


# --- grounding & slugs -------------------------------------------------------


def test_verify_echoed_item_ids_accepts_subset_and_rejects_unknown() -> None:
    verify_echoed_item_ids([1, 2], {1, 2, 3})
    with pytest.raises(GroundingError):
        verify_echoed_item_ids([1, 99], {1, 2, 3})


def test_slugify_normalizes_names() -> None:
    assert slugify("Pasta & Sauce!") == "pasta-sauce"
    assert slugify("  Déjà vu  ") == "d-j-vu"
    assert slugify("!!!") == "topic"
