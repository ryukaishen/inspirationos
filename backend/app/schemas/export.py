"""Request/response schemas for career-artifact/library export (M8).

`ProjectExport`/`LibraryExport` are the *published* JSON export schema
(`schema_version`): the export test validates round-trip via
`ProjectExport.model_validate_json(...)`/`LibraryExport.model_validate_json(...)`,
the same way the rest of the codebase treats Pydantic validation as the
contract for structured output.
"""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.export import ExportBundleFormat
from app.models.project import MilestoneStatus, ProjectStatus


class ExportRequest(BaseModel):
    """`project_id=None` requests a full-library export."""

    format: ExportBundleFormat
    project_id: int | None = None


class ExportAccepted(BaseModel):
    export_id: int
    job_id: int


class ExportRead(BaseModel):
    id: int
    project_id: int | None
    format: ExportBundleFormat
    ready: bool
    size_bytes: int | None
    error: str | None
    created_at: datetime


class MilestoneExport(BaseModel):
    title: str
    description: str | None
    status: MilestoneStatus
    sort_order: int
    target_date: date | None


class ArtifactExport(BaseModel):
    kind: str
    version: int
    content_md: str
    payload: dict[str, Any] | None
    claims_flags: list[str]
    provider: str
    model: str
    created_at: datetime


class ProjectExport(BaseModel):
    model_config = ConfigDict(from_attributes=False)

    schema_version: Literal["1"] = "1"
    id: int
    title: str
    one_liner: str
    summary_md: str
    domains: list[str]
    difficulty: str | None
    duration_estimate: str | None
    tech_stack: list[Any]
    skills_demonstrated: list[Any]
    risks: list[Any]
    scores: dict[str, Any]
    status: ProjectStatus
    milestones: list[MilestoneExport] = Field(default_factory=list)
    artifacts: list[ArtifactExport] = Field(default_factory=list)


class LibraryExport(BaseModel):
    schema_version: Literal["1"] = "1"
    generated_at: datetime
    projects: list[ProjectExport] = Field(default_factory=list)
