"""Request/response schemas for the analysis triggers and cluster browsing."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.analysis import ClusterRunStatus
from app.schemas.item import ItemRead


class EmbedRequest(BaseModel):
    # None = every item still missing an embedding for the active model.
    item_ids: list[int] | None = None
    force: bool = False


class ClusterTriggerRequest(BaseModel):
    distance_threshold: float | None = Field(default=None, gt=0.0, lt=2.0)


class TopicsTriggerRequest(BaseModel):
    # None = the latest succeeded cluster run.
    cluster_run_id: int | None = None


class AnalysisAccepted(BaseModel):
    job_id: int


class ClusterRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int
    label: str | None
    description_md: str | None
    size: int
    # Distinct topic names of member items (filled by the topics job).
    topics: list[str] = []


class ClusterRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    method: str
    params: dict[str, Any]
    embedding_model: str
    status: ClusterRunStatus
    created_at: datetime
    cluster_count: int = 0


class ClusterRunDetail(ClusterRunRead):
    clusters: list[ClusterRead] = []


class ClusterUpdateRequest(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=256)
    description_md: str | None = None


class ClusterItemsResponse(BaseModel):
    items: list[ItemRead]
