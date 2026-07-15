from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.job import JobKind, JobStatus


class DemoJobRequest(BaseModel):
    steps: int = Field(default=10, ge=1, le=1000)
    step_seconds: float = Field(default=0.5, ge=0, le=5)


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    rq_job_id: str | None
    kind: JobKind
    status: JobStatus
    progress: int
    total: int
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
