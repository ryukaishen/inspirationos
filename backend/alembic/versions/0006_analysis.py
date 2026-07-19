"""AI analysis tables for Milestone 6

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-18

Purely additive, no backfill: items gain nullable pgvector `embedding` /
`embedding_model` columns; new tables `topics`, `item_topics`, `cluster_runs`,
`clusters`, `item_clusters`, and `ai_requests`. The `vector` extension has
existed since migration 0001. `ai_requests` has no content columns at all —
counts, cost, and latency only (PRIVACY_SECURITY.md). Membership FKs cascade
on item deletion so the extract pass's delete-and-reinsert never blocks.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CLUSTER_RUN_STATUSES = ("running", "succeeded", "failed")
AI_REQUEST_STATUSES = ("success", "invalid_output", "error")

JSONB_EMPTY = sa.text("'{}'::jsonb")


def upgrade() -> None:
    op.add_column("items", sa.Column("embedding", Vector(384), nullable=True))
    op.add_column("items", sa.Column("embedding_model", sa.String(128), nullable=True))

    op.create_table(
        "topics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("slug", sa.String(128), nullable=False, unique=True),
    )

    op.create_table(
        "item_topics",
        sa.Column(
            "item_id",
            sa.Integer(),
            sa.ForeignKey("items.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "topic_id",
            sa.Integer(),
            sa.ForeignKey("topics.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("confidence", sa.Float(), nullable=False),
    )

    op.create_table(
        "cluster_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("method", sa.String(64), nullable=False),
        sa.Column("params", postgresql.JSONB(), nullable=False, server_default=JSONB_EMPTY),
        sa.Column("embedding_model", sa.String(128), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(*CLUSTER_RUN_STATUSES, name="cluster_run_status"),
            nullable=False,
            server_default="running",
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_table(
        "clusters",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("cluster_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.String(256), nullable=True),
        sa.Column("description_md", sa.Text(), nullable=True),
        sa.Column("size", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_clusters_run_id", "clusters", ["run_id"])

    op.create_table(
        "item_clusters",
        sa.Column(
            "item_id",
            sa.Integer(),
            sa.ForeignKey("items.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "cluster_id",
            sa.Integer(),
            sa.ForeignKey("clusters.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_index("ix_item_clusters_cluster_id", "item_clusters", ["cluster_id"])

    op.create_table(
        "ai_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id"), nullable=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("task", sa.String(64), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("est_cost_usd", sa.Numeric(10, 6), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "status",
            postgresql.ENUM(*AI_REQUEST_STATUSES, name="ai_request_status"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    # Backs the monthly-budget SUM over the current calendar month.
    op.create_index("ix_ai_requests_created_at", "ai_requests", ["created_at"])


def downgrade() -> None:
    op.drop_table("ai_requests")
    op.drop_table("item_clusters")
    op.drop_table("clusters")
    op.drop_table("cluster_runs")
    op.drop_table("item_topics")
    op.drop_table("topics")
    op.drop_column("items", "embedding_model")
    op.drop_column("items", "embedding")
    op.execute("DROP TYPE IF EXISTS ai_request_status")
    op.execute("DROP TYPE IF EXISTS cluster_run_status")
