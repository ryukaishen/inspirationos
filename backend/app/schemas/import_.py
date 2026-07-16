from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.import_ import ExportFormat, ImportStatus
from app.schemas.job import JobRead


class ImportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    filename: str
    size_bytes: int
    checksum_sha256: str
    export_format: ExportFormat
    status: ImportStatus
    counts: dict[str, Any]
    error: str | None
    created_at: datetime


class ImportDetail(ImportRead):
    latest_job: JobRead | None = None


class UploadAccepted(BaseModel):
    import_id: int
    job_id: int
