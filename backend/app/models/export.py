"""Career-artifact / project-library export bundles (M8).

An `exports` row is created (with `storage_key=NULL`) in the same
transaction as its `jobs` row, before enqueue — mirroring `imports.py`'s
accept sequence. The `export_bundle` worker renders content, writes it
through the `Storage` abstraction, and fills in `storage_key`/`size_bytes`
(or `error` on failure), so `GET /api/exports/{id}` reports readiness without
needing to cross-reference the job. `project_id IS NULL` means a full-library
export. Rendered content (`content_md`/JSON) is generated text derived from
already-AI-generated project/artifact fields — never raw message text.
"""

import enum

from sqlalchemy import BigInteger, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin


class ExportBundleFormat(enum.Enum):
    """Distinct from `models.import_.ExportFormat` (the Instagram export's
    own json/html_detected format detection) — this is the output format of
    a career-artifact/library export bundle."""

    markdown = "markdown"
    json = "json"


class Export(Base, CreatedAtMixin):
    __tablename__ = "exports"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    format: Mapped[ExportBundleFormat] = mapped_column(
        Enum(
            ExportBundleFormat,
            name="export_bundle_format",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )
    storage_key: Mapped[str | None] = mapped_column(String(255))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    error: Mapped[str | None] = mapped_column(Text)
