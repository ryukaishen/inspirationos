"""Shared Pydantic task schemas every LLM provider must validate against.

M6 tasks (topic extraction, cluster labeling) + M7 tasks (project generation,
combination, advisor review); M8 adds the career-artifact tasks. Providers
never define their own output shapes — the same schema drives the Anthropic
tool input_schema, the OpenAI json_schema response format, and the Mock
provider's constructed output.
"""

from typing import Literal

from pydantic import BaseModel, Field

TASK_TOPIC_EXTRACTION = "topic_extraction"
TASK_CLUSTER_LABEL = "cluster_label"
TASK_GENERATE_PROJECTS = "generate_projects"
TASK_COMBINE_PROJECTS = "combine_projects"
TASK_ADVISOR_REVIEW = "advisor_review"


class TopicAssignmentEntry(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    confidence: float = Field(ge=0.0, le=1.0)


class ItemTopics(BaseModel):
    item_id: int
    topics: list[TopicAssignmentEntry] = Field(min_length=1, max_length=5)


class TopicExtraction(BaseModel):
    """Per-item topic assignments; item_ids are echoed and verified server-side."""

    assignments: list[ItemTopics]


class ClusterLabel(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    description_md: str = Field(min_length=1)


class SubScore(BaseModel):
    """One scoring dimension: 0-10 plus a one-line rationale (M7 transparent
    scoring — a bare number without a reason is not acceptable output)."""

    score: float = Field(ge=0.0, le=10.0)
    rationale: str = Field(min_length=1, max_length=400)


class ProjectScores(BaseModel):
    """The five fixed scoring dimensions. Fixed fields (not a dict) so the
    comparison view aligns and the weights UI never meets unknown keys.
    `services/generation/scoring.py` derives SCORE_DIMENSIONS from these."""

    career_alignment: SubScore
    technical_depth: SubScore
    originality: SubScore
    feasibility: SubScore
    recruiter_appeal: SubScore


class ProjectFields(BaseModel):
    """Generated project fields shared by fresh ideas and combined ideas."""

    title: str = Field(min_length=1, max_length=256)
    one_liner: str = Field(min_length=1, max_length=300)
    summary_md: str = Field(min_length=1)
    domains: list[str] = Field(min_length=1, max_length=4)
    difficulty: Literal["beginner", "intermediate", "advanced"]
    duration_estimate: str = Field(min_length=1, max_length=128)
    datasets: list[str] = Field(default_factory=list, max_length=10)
    tech_stack: list[str] = Field(min_length=1, max_length=15)
    skills_demonstrated: list[str] = Field(min_length=1, max_length=15)
    risks: list[str] = Field(default_factory=list, max_length=10)
    scores: ProjectScores


class ProjectIdea(ProjectFields):
    """One grounded idea; source ids are echoed and verified server-side."""

    source_item_ids: list[int] = Field(min_length=1)
    source_cluster_ids: list[int] = Field(default_factory=list)


class ProjectIdeas(BaseModel):
    ideas: list[ProjectIdea] = Field(min_length=1)


class CombinedProject(ProjectFields):
    """Combination of two parents; provenance comes from the parents
    server-side, so the model echoes no ids here."""


class WeekPlanEntry(BaseModel):
    week: int = Field(ge=1, le=52)
    focus: str = Field(min_length=1, max_length=300)
    deliverable: str = Field(min_length=1, max_length=300)


class CommonalityVerdict(BaseModel):
    verdict: Literal["very_common", "common", "uncommon", "novel"]
    reasoning: str = Field(min_length=1)


class AdvisorReview(BaseModel):
    """The five structured advisor sections (M7)."""

    commonality: CommonalityVerdict
    comparative_strength: str = Field(min_length=1)
    recruiter_impact: str = Field(min_length=1)
    prerequisites: list[str] = Field(min_length=1, max_length=15)
    week_by_week: list[WeekPlanEntry] = Field(min_length=1, max_length=52)
