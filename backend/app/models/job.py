import enum
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin


class JobKind(enum.Enum):
    demo = "demo"
    import_scan = "import_scan"
    import_extract = "import_extract"
    enrich_batch = "enrich_batch"
    embed_batch = "embed_batch"
    cluster = "cluster"
    topics = "topics"
    generate_projects = "generate_projects"
    generate_artifact = "generate_artifact"
    export_bundle = "export_bundle"
    delete_data = "delete_data"


class JobStatus(enum.Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


class Job(Base, CreatedAtMixin):
    """Mirror of RQ state; the DB row is the source of truth for the UI.

    `payload` holds IDs and counts only — never message content.
    `error` is redacted (exception class name, no message text).
    """

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    rq_job_id: Mapped[str | None] = mapped_column(String(64))
    kind: Mapped[JobKind] = mapped_column(
        Enum(JobKind, name="job_kind", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=JobStatus.queued,
        server_default="queued",
    )
    progress: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    total: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
