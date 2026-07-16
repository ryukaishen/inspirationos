import enum
from typing import Any

from sqlalchemy import BigInteger, Enum, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin


class ImportStatus(enum.Enum):
    uploaded = "uploaded"
    scanning = "scanning"
    scanned = "scanned"
    extracting = "extracting"
    extracted = "extracted"
    failed = "failed"
    deleted = "deleted"


class ExportFormat(enum.Enum):
    json = "json"
    html_detected = "html_detected"


class Import(Base, CreatedAtMixin):
    """One uploaded export ZIP, retained in private storage until deleted.

    `storage_key` is NULL only for rejected uploads that keep no file (HTML
    exports). `error` holds static messages or exception class names only —
    never message content. The partial unique index is the authoritative,
    race-safe checksum dedupe; failed/deleted rows never block a re-upload.
    """

    __tablename__ = "imports"
    __table_args__ = (
        Index(
            "uq_imports_checksum_active",
            "checksum_sha256",
            unique=True,
            postgresql_where=text("status NOT IN ('failed', 'deleted')"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, default="instagram", server_default="instagram"
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str | None] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    export_format: Mapped[ExportFormat] = mapped_column(
        Enum(ExportFormat, name="export_format", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    status: Mapped[ImportStatus] = mapped_column(
        Enum(ImportStatus, name="import_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=ImportStatus.uploaded,
        server_default="uploaded",
    )
    counts: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    error: Mapped[str | None] = mapped_column(Text)
