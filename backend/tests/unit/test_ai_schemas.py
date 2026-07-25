"""ProjectFields list-field deduplication: seen live against a real Anthropic
generation (`domains` repeated the same entry, which broke a React list key
downstream in project-card.tsx) — the model isn't asked to fail generation
over a cosmetic repeat, just silently deduped, order preserved."""

from app.services.ai.schemas import CombinedProject, ProjectIdea

BASE_SCORES = {
    "career_alignment": {"score": 5, "rationale": "r"},
    "technical_depth": {"score": 5, "rationale": "r"},
    "originality": {"score": 5, "rationale": "r"},
    "feasibility": {"score": 5, "rationale": "r"},
    "recruiter_appeal": {"score": 5, "rationale": "r"},
}


def _project_idea(**overrides: object) -> ProjectIdea:
    fields = {
        "title": "t",
        "one_liner": "o",
        "summary_md": "s",
        "domains": ["applied_ai"],
        "difficulty": "intermediate",
        "duration_estimate": "2 weeks",
        "tech_stack": ["python"],
        "skills_demonstrated": ["ml"],
        "scores": BASE_SCORES,
        "source_item_ids": [1],
    }
    fields.update(overrides)
    return ProjectIdea.model_validate(fields)


def test_duplicate_domain_deduplicated() -> None:
    idea = _project_idea(domains=["applied_ai", "applied_ai"])
    assert idea.domains == ["applied_ai"]


def test_dedup_preserves_first_occurrence_order() -> None:
    idea = _project_idea(domains=["healthcare_ai", "applied_ai", "healthcare_ai"])
    assert idea.domains == ["healthcare_ai", "applied_ai"]


def test_no_duplicates_unaffected() -> None:
    idea = _project_idea(domains=["applied_ai", "quant_finance"])
    assert idea.domains == ["applied_ai", "quant_finance"]


def test_dedup_applies_to_every_listed_field() -> None:
    idea = _project_idea(
        tech_stack=["python", "python", "pandas"],
        skills_demonstrated=["ml", "ml"],
        datasets=["synthetic", "synthetic"],
        risks=["overfitting", "overfitting"],
    )
    assert idea.tech_stack == ["python", "pandas"]
    assert idea.skills_demonstrated == ["ml"]
    assert idea.datasets == ["synthetic"]
    assert idea.risks == ["overfitting"]


def test_combined_project_shares_the_same_validator() -> None:
    combined = CombinedProject.model_validate(
        {
            "title": "t",
            "one_liner": "o",
            "summary_md": "s",
            "domains": ["applied_ai", "applied_ai"],
            "difficulty": "intermediate",
            "duration_estimate": "2 weeks",
            "tech_stack": ["python"],
            "skills_demonstrated": ["ml"],
            "scores": BASE_SCORES,
        }
    )
    assert combined.domains == ["applied_ai"]
