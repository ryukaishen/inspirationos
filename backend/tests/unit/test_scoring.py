"""Scoring math (M7): pure unit tests, no services.

`lib/scoring.ts` mirrors compute_score on the frontend; these cases and the
vitest cases assert the same numbers so the two implementations cannot drift
silently.
"""

import pytest

from app.services.ai.schemas import ProjectScores
from app.services.generation.scoring import (
    DEFAULT_WEIGHT,
    SCORE_DIMENSIONS,
    InvalidWeightsError,
    compute_score,
    validate_weights,
)


def _scores(**values: float) -> dict:
    return {
        dimension: {"score": value, "rationale": f"because {dimension}"}
        for dimension, value in values.items()
    }


FULL_SCORES = _scores(
    career_alignment=8.0,
    technical_depth=6.0,
    originality=4.0,
    feasibility=9.0,
    recruiter_appeal=5.0,
)


def test_dimensions_come_from_the_schema() -> None:
    assert tuple(ProjectScores.model_fields) == SCORE_DIMENSIONS
    assert len(SCORE_DIMENSIONS) == 5


def test_default_weights_sum_all_dimensions() -> None:
    # 8 + 6 + 4 + 9 + 5, every weight defaulting to 1.0.
    assert compute_score(FULL_SCORES) == 32.0
    assert DEFAULT_WEIGHT == 1.0


def test_weight_change_shifts_the_total() -> None:
    weights = {"originality": 2.0, "feasibility": 0.0}
    # 8 + 6 + (2 * 4) + (0 * 9) + 5
    assert compute_score(FULL_SCORES, weights) == 27.0


def test_weight_change_reorders_two_projects() -> None:
    deep = _scores(
        career_alignment=5.0,
        technical_depth=9.0,
        originality=5.0,
        feasibility=4.0,
        recruiter_appeal=5.0,
    )
    safe = _scores(
        career_alignment=5.0,
        technical_depth=4.0,
        originality=5.0,
        feasibility=9.0,
        recruiter_appeal=5.0,
    )
    assert compute_score(deep) == compute_score(safe)  # tied under default weights
    feasibility_first = {"feasibility": 2.0, "technical_depth": 0.5}
    depth_first = {"technical_depth": 2.0, "feasibility": 0.5}
    assert compute_score(safe, feasibility_first) > compute_score(deep, feasibility_first)
    assert compute_score(deep, depth_first) > compute_score(safe, depth_first)


def test_missing_dimensions_are_skipped_not_crashed() -> None:
    partial = _scores(career_alignment=7.0)
    assert compute_score(partial) == 7.0
    assert compute_score({}) == 0.0


def test_malformed_stored_entries_are_ignored() -> None:
    scores = {
        "career_alignment": {"score": "high", "rationale": "not numeric"},
        "technical_depth": "not a dict",
        "originality": {"rationale": "score missing"},
        "feasibility": {"score": True, "rationale": "bool is not a score"},
        "recruiter_appeal": {"score": 6.0, "rationale": "fine"},
    }
    assert compute_score(scores) == 6.0


def test_validate_weights_accepts_partial_mappings() -> None:
    assert validate_weights({}) == {}
    assert validate_weights({"originality": 1.5}) == {"originality": 1.5}
    assert validate_weights({"feasibility": 0}) == {"feasibility": 0.0}


def test_validate_weights_rejects_unknown_dimension() -> None:
    with pytest.raises(InvalidWeightsError, match="unknown scoring dimension"):
        validate_weights({"vibes": 1.0})


@pytest.mark.parametrize("bad", [-0.1, 2.1, "1.0", True, None])
def test_validate_weights_rejects_bad_values(bad: object) -> None:
    with pytest.raises(InvalidWeightsError):
        validate_weights({"originality": bad})
