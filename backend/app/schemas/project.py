"""Request/response schemas for the project workspace (M7).

`scores` is returned raw (per-dimension sub-scores + rationales); the final
weighted score is computed at read time by the client from
`settings.scoring_weights`, so re-ranking never touches the API.
"""

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.project import MilestoneStatus, ProjectStatus


class GenerateProjectsRequest(BaseModel):
    """Sources for one generation batch; at least one id must be given.
    Cluster ids expand server-side to their member items."""

    cluster_ids: list[int] = []
    item_ids: list[int] = []
    count: int | None = Field(default=None, ge=1)


class CombineRequest(BaseModel):
    parent_project_ids: list[int] = Field(min_length=2, max_length=2)


class GenerateAccepted(BaseModel):
    job_id: int


class MilestoneRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    title: str
    description: str | None
    sort_order: int
    status: MilestoneStatus
    target_date: date | None


class MilestoneCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=256)
    description: str | None = None
    status: MilestoneStatus = MilestoneStatus.todo
    target_date: date | None = None


class MilestoneUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=256)
    description: str | None = None
    status: MilestoneStatus | None = None
    target_date: date | None = None


class MilestoneOrderRequest(BaseModel):
    """Full ordered id list — must be an exact permutation of the project's
    milestones; the server rewrites sort_order 0..n."""

    milestone_ids: list[int] = Field(min_length=1)


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    one_liner: str
    summary_md: str
    domains: list[str]
    difficulty: str | None
    duration_estimate: str | None
    datasets: list[Any]
    tech_stack: list[Any]
    skills_demonstrated: list[Any]
    risks: list[Any]
    scores: dict[str, Any]
    status: ProjectStatus
    source: dict[str, Any]
    parent_project_ids: list[int]
    created_at: datetime
    updated_at: datetime


class ProjectDetail(ProjectRead):
    milestones: list[MilestoneRead] = []


class ProjectListResponse(BaseModel):
    projects: list[ProjectRead]
    total: int


class ProjectUpdateRequest(BaseModel):
    """Partial update; only fields present in the body are applied. Generated
    provenance (`scores`, `source`, `parent_project_ids`) is not editable."""

    title: str | None = Field(default=None, min_length=1, max_length=256)
    one_liner: str | None = Field(default=None, min_length=1)
    summary_md: str | None = Field(default=None, min_length=1)
    domains: list[str] | None = None
    difficulty: str | None = Field(default=None, max_length=32)
    duration_estimate: str | None = Field(default=None, max_length=128)
    datasets: list[Any] | None = None
    tech_stack: list[Any] | None = None
    skills_demonstrated: list[Any] | None = None
    risks: list[Any] | None = None
    status: ProjectStatus | None = None


class AdvisorReviewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    version: int
    content_md: str
    payload: dict[str, Any] | None
    provider: str
    model: str
    prompt_version: str
    created_at: datetime
