"""Analysis tables (M6): topics, versioned cluster runs, and memberships.

Membership FKs cascade on item deletion because the extract pass
delete-and-reinserts items per conversation — analysis rows must never block
a re-extract (embeddings/clusters are simply recomputed afterwards).
"""

import enum
from typing import Any

from sqlalchemy import Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin


class Topic(Base):
    """A topic extracted by the fast-model task; deduplicated by slug."""

    __tablename__ = "topics"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    slug: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)


class ItemTopic(Base):
    __tablename__ = "item_topics"

    item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), primary_key=True
    )
    topic_id: Mapped[int] = mapped_column(
        ForeignKey("topics.id", ondelete="CASCADE"), primary_key=True
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)


class ClusterRunStatus(enum.Enum):
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class ClusterRun(Base, CreatedAtMixin):
    """One versioned clustering execution; re-running creates a new row."""

    __tablename__ = "cluster_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    method: Mapped[str] = mapped_column(String(64), nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    embedding_model: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[ClusterRunStatus] = mapped_column(
        Enum(
            ClusterRunStatus,
            name="cluster_run_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=ClusterRunStatus.running,
        server_default="running",
    )


class Cluster(Base):
    """A cluster within one run. `label`/`description_md` start NULL and are
    filled by the topics job — but only when still NULL, so user edits survive
    re-runs of the topics job."""

    __tablename__ = "clusters"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("cluster_runs.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str | None] = mapped_column(String(256))
    description_md: Mapped[str | None] = mapped_column(Text)
    size: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class ItemCluster(Base):
    __tablename__ = "item_clusters"

    item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), primary_key=True
    )
    cluster_id: Mapped[int] = mapped_column(
        ForeignKey("clusters.id", ondelete="CASCADE"), primary_key=True
    )
