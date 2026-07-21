"""Hybrid scoring (M7): the LLM produces per-dimension sub-scores with
rationales; the final score is `sum(weight * sub_score)` computed at read
time from `settings.scoring_weights`. Changing weights re-ranks instantly and
stored data never changes (DATA_MODEL.md modeling rule). The frontend mirrors
this exact math in `lib/scoring.ts` for the instant client-side re-rank; both
sides share the same unit-test cases.
"""

from typing import Any

from app.services.ai.schemas import ProjectScores

# Single source of truth for the dimension set is the ProjectScores schema.
SCORE_DIMENSIONS: tuple[str, ...] = tuple(ProjectScores.model_fields)
DEFAULT_WEIGHT = 1.0
MIN_WEIGHT = 0.0
MAX_WEIGHT = 2.0


class InvalidWeightsError(ValueError):
    """A weights mapping referenced an unknown dimension or a bad value."""


def validate_weights(weights: dict[str, Any]) -> dict[str, float]:
    """Validate a scoring_weights mapping; returns the cleaned float mapping.

    Missing dimensions are fine (they default to DEFAULT_WEIGHT at read
    time); unknown keys and out-of-range or non-numeric values are rejected.
    """
    clean: dict[str, float] = {}
    for key, value in weights.items():
        if key not in SCORE_DIMENSIONS:
            raise InvalidWeightsError(f"unknown scoring dimension: {key!r}")
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise InvalidWeightsError(f"weight for {key!r} is not a number")
        weight = float(value)
        if not MIN_WEIGHT <= weight <= MAX_WEIGHT:
            raise InvalidWeightsError(
                f"weight for {key!r} outside [{MIN_WEIGHT}, {MAX_WEIGHT}]: {weight}"
            )
        clean[key] = weight
    return clean


def compute_score(scores: dict[str, Any], weights: dict[str, Any] | None = None) -> float:
    """Weighted sum over whichever known dimensions are present in `scores`.

    `scores` is the stored JSONB (`{dimension: {"score": float, "rationale":
    str}}`); malformed entries are skipped rather than crashing a read path.
    """
    effective = weights or {}
    total = 0.0
    for dimension in SCORE_DIMENSIONS:
        entry = scores.get(dimension)
        if not isinstance(entry, dict):
            continue
        raw = entry.get("score")
        if isinstance(raw, bool) or not isinstance(raw, int | float):
            continue
        weight = effective.get(dimension, DEFAULT_WEIGHT)
        if isinstance(weight, bool) or not isinstance(weight, int | float):
            weight = DEFAULT_WEIGHT
        total += float(weight) * float(raw)
    return round(total, 2)
