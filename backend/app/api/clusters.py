"""Analysis triggers (embed → cluster → topics) and cluster browsing/editing.

Triggers follow the repo convention: jobs row first, then enqueue onto the
`ai` queue, 503 + failed job when the queue is unreachable. Payloads carry IDs
and scalar knobs only — never item text. Reads collapse to the latest data the
jobs produced; PATCH lets the user edit AI-generated labels/descriptions
(edits survive topic-job re-runs, which only fill NULL fields).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from redis import Redis
from rq import Queue
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db_session
from app.models.analysis import Cluster, ClusterRun, ClusterRunStatus, ItemCluster, ItemTopic, Topic
from app.models.item import Item
from app.models.job import Job, JobKind, JobStatus
from app.queues import QUEUE_AI
from app.redis_client import get_redis
from app.schemas.cluster import (
    AnalysisAccepted,
    ClusterItemsResponse,
    ClusterRead,
    ClusterRunDetail,
    ClusterRunRead,
    ClusterTriggerRequest,
    ClusterUpdateRequest,
    EmbedRequest,
    TopicsTriggerRequest,
)
from app.schemas.item import ItemRead

router = APIRouter(tags=["analysis"])

CLUSTER_NOT_FOUND_MESSAGE = "cluster not found"
RUN_NOT_FOUND_MESSAGE = "cluster run not found"
NO_SUCCEEDED_RUN_MESSAGE = "no succeeded cluster run exists yet — run clustering first"
QUEUE_UNAVAILABLE_MESSAGE = "job queue unavailable"

DbSession = Annotated[Session, Depends(get_db_session)]
RedisDep = Annotated[Redis, Depends(get_redis)]


def _enqueue_job(
    db: Session, redis: Redis, *, kind: JobKind, payload: dict[str, object], func_path: str
) -> Job:
    """Jobs-row-then-enqueue; enqueue failure marks the row failed and 503s."""
    job = Job(kind=kind, status=JobStatus.queued, payload=payload)
    db.add(job)
    db.commit()
    db.refresh(job)
    try:
        rq_job = Queue(QUEUE_AI, connection=redis).enqueue(func_path, job.id, **payload)
    except Exception as exc:
        job.status = JobStatus.failed
        job.error = type(exc).__name__
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "queue_unavailable", "message": QUEUE_UNAVAILABLE_MESSAGE},
        ) from exc
    job.rq_job_id = rq_job.id
    db.commit()
    return job


@router.post(
    "/analysis/embed", response_model=AnalysisAccepted, status_code=status.HTTP_202_ACCEPTED
)
def trigger_embed(body: EmbedRequest, db: DbSession, redis: RedisDep) -> AnalysisAccepted:
    job = _enqueue_job(
        db,
        redis,
        kind=JobKind.embed_batch,
        payload={"item_ids": body.item_ids, "force": body.force},
        func_path="app.workers.jobs.run_embed_batch",
    )
    return AnalysisAccepted(job_id=job.id)


@router.post(
    "/analysis/cluster", response_model=AnalysisAccepted, status_code=status.HTTP_202_ACCEPTED
)
def trigger_cluster(
    body: ClusterTriggerRequest, db: DbSession, redis: RedisDep
) -> AnalysisAccepted:
    job = _enqueue_job(
        db,
        redis,
        kind=JobKind.cluster,
        payload={"distance_threshold": body.distance_threshold},
        func_path="app.workers.jobs.run_cluster",
    )
    return AnalysisAccepted(job_id=job.id)


@router.post(
    "/analysis/topics", response_model=AnalysisAccepted, status_code=status.HTTP_202_ACCEPTED
)
def trigger_topics(body: TopicsTriggerRequest, db: DbSession, redis: RedisDep) -> AnalysisAccepted:
    if body.cluster_run_id is not None:
        if db.get(ClusterRun, body.cluster_run_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=RUN_NOT_FOUND_MESSAGE)
    else:
        latest_succeeded = db.scalar(
            select(ClusterRun.id)
            .where(ClusterRun.status == ClusterRunStatus.succeeded)
            .order_by(ClusterRun.id.desc())
            .limit(1)
        )
        if latest_succeeded is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "no_cluster_run", "message": NO_SUCCEEDED_RUN_MESSAGE},
            )
    job = _enqueue_job(
        db,
        redis,
        kind=JobKind.topics,
        payload={"cluster_run_id": body.cluster_run_id},
        func_path="app.workers.jobs.run_topics",
    )
    return AnalysisAccepted(job_id=job.id)


def _cluster_counts(db: Session, run_ids: list[int]) -> dict[int, int]:
    if not run_ids:
        return {}
    rows = db.execute(
        select(Cluster.run_id, func.count())
        .where(Cluster.run_id.in_(run_ids))
        .group_by(Cluster.run_id)
    ).all()
    return {run_id: count for run_id, count in rows}


@router.get("/cluster-runs", response_model=list[ClusterRunRead])
def list_cluster_runs(db: DbSession) -> list[ClusterRunRead]:
    runs = list(db.scalars(select(ClusterRun).order_by(ClusterRun.id.desc())))
    counts = _cluster_counts(db, [run.id for run in runs])
    entries = []
    for run in runs:
        entry = ClusterRunRead.model_validate(run)
        entry.cluster_count = counts.get(run.id, 0)
        entries.append(entry)
    return entries


@router.get("/cluster-runs/{run_id}", response_model=ClusterRunDetail)
def get_cluster_run(run_id: int, db: DbSession) -> ClusterRunDetail:
    run = db.get(ClusterRun, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=RUN_NOT_FOUND_MESSAGE)
    clusters = list(
        db.scalars(select(Cluster).where(Cluster.run_id == run.id).order_by(Cluster.id))
    )
    # Distinct topic names per cluster, one query for the whole run.
    topic_rows = db.execute(
        select(ItemCluster.cluster_id, Topic.name)
        .join(ItemTopic, ItemTopic.item_id == ItemCluster.item_id)
        .join(Topic, Topic.id == ItemTopic.topic_id)
        .where(ItemCluster.cluster_id.in_([cluster.id for cluster in clusters]))
        .distinct()
        .order_by(ItemCluster.cluster_id, Topic.name)
    ).all()
    topics_by_cluster: dict[int, list[str]] = {}
    for cluster_id, topic_name in topic_rows:
        topics_by_cluster.setdefault(cluster_id, []).append(topic_name)

    detail = ClusterRunDetail.model_validate(run)
    detail.cluster_count = len(clusters)
    detail.clusters = []
    for cluster in clusters:
        entry = ClusterRead.model_validate(cluster)
        entry.topics = topics_by_cluster.get(cluster.id, [])
        detail.clusters.append(entry)
    return detail


@router.get("/clusters/{cluster_id}/items", response_model=ClusterItemsResponse)
def get_cluster_items(cluster_id: int, db: DbSession) -> ClusterItemsResponse:
    cluster = db.get(Cluster, cluster_id)
    if cluster is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=CLUSTER_NOT_FOUND_MESSAGE)
    items = list(
        db.scalars(
            select(Item)
            .join(ItemCluster, ItemCluster.item_id == Item.id)
            .where(ItemCluster.cluster_id == cluster.id)
            .order_by(Item.id)
        )
    )
    return ClusterItemsResponse(items=[ItemRead.model_validate(item) for item in items])


@router.patch("/clusters/{cluster_id}", response_model=ClusterRead)
def update_cluster(cluster_id: int, body: ClusterUpdateRequest, db: DbSession) -> ClusterRead:
    cluster = db.get(Cluster, cluster_id)
    if cluster is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=CLUSTER_NOT_FOUND_MESSAGE)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(cluster, field, value)
    db.commit()
    return ClusterRead.model_validate(cluster)
