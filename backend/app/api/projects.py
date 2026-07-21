"""Project workspace API (M7): generation/combine/advisor triggers, the
project library, field editing, and roadmap milestones.

Triggers follow the jobs-row-then-enqueue convention onto the `ai` queue;
payloads carry IDs and scalar knobs only. Reads return stored sub-scores
raw — the final weighted score is computed client-side from
`settings.scoring_weights`, so re-ranking never calls a generation endpoint.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.enqueue import enqueue_job
from app.config import get_config
from app.db import get_db_session
from app.models.analysis import Cluster
from app.models.artifact import Artifact, ArtifactKind
from app.models.item import Item
from app.models.job import JobKind
from app.models.project import Project, ProjectMilestone, ProjectStatus
from app.redis_client import get_redis
from app.schemas.artifact import ArtifactRead, CareerArtifactKind
from app.schemas.project import (
    AdvisorReviewRead,
    CombineRequest,
    GenerateAccepted,
    GenerateProjectsRequest,
    MilestoneCreateRequest,
    MilestoneOrderRequest,
    MilestoneRead,
    MilestoneUpdateRequest,
    ProjectDetail,
    ProjectListResponse,
    ProjectRead,
    ProjectUpdateRequest,
)
from app.services.enrichment.policy import is_eligible_for_generation
from app.services.generation.career_outputs import latest_artifacts_by_kind
from app.services.generation.projects import resolve_source_item_ids

router = APIRouter(prefix="/projects", tags=["projects"])

PROJECT_NOT_FOUND_MESSAGE = "project not found"
MILESTONE_NOT_FOUND_MESSAGE = "milestone not found"

DbSession = Annotated[Session, Depends(get_db_session)]
RedisDep = Annotated[Redis, Depends(get_redis)]


def _get_project_or_404(db: Session, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=PROJECT_NOT_FOUND_MESSAGE)
    return project


@router.post("/generate", response_model=GenerateAccepted, status_code=status.HTTP_202_ACCEPTED)
def generate_projects(
    body: GenerateProjectsRequest, db: DbSession, redis: RedisDep
) -> GenerateAccepted:
    """Start a generation batch from selected clusters and/or items.

    Validates that every referenced id exists and that at least one source
    item passes the text-eligibility gate — `needs_context` items are
    excluded from generation input in code, so a selection of undescribed
    reels is rejected here rather than hallucinated about.
    """
    if not body.cluster_ids and not body.item_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "no_sources", "message": "select at least one cluster or item"},
        )
    known_cluster_ids = set(db.scalars(select(Cluster.id).where(Cluster.id.in_(body.cluster_ids))))
    missing_clusters = sorted(set(body.cluster_ids) - known_cluster_ids)
    if missing_clusters:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "unknown_clusters",
                "message": f"unknown cluster ids: {missing_clusters}",
            },
        )
    known_item_ids = set(db.scalars(select(Item.id).where(Item.id.in_(body.item_ids))))
    missing_items = sorted(set(body.item_ids) - known_item_ids)
    if missing_items:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "unknown_items", "message": f"unknown item ids: {missing_items}"},
        )
    source_item_ids = resolve_source_item_ids(
        db, item_ids=body.item_ids, cluster_ids=body.cluster_ids
    )
    source_items = db.scalars(select(Item).where(Item.id.in_(source_item_ids)))
    if not any(is_eligible_for_generation(item) for item in source_items):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "no_eligible_items",
                "message": "none of the selected items has any real text — "
                "add context notes or enrich them first",
            },
        )
    config = get_config()
    count = body.count if body.count is not None else config.projects_default_count
    count = max(1, min(count, config.projects_max_count))
    job = enqueue_job(
        db,
        redis,
        kind=JobKind.generate_projects,
        payload={"item_ids": body.item_ids, "cluster_ids": body.cluster_ids, "count": count},
        func_path="app.workers.jobs.run_generate_projects",
    )
    return GenerateAccepted(job_id=job.id)


@router.post("/combine", response_model=GenerateAccepted, status_code=status.HTTP_202_ACCEPTED)
def combine_projects(body: CombineRequest, db: DbSession, redis: RedisDep) -> GenerateAccepted:
    parent_ids = body.parent_project_ids
    if len(set(parent_ids)) != 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "bad_parents", "message": "combine requires two distinct projects"},
        )
    for parent_id in parent_ids:
        _get_project_or_404(db, parent_id)
    job = enqueue_job(
        db,
        redis,
        kind=JobKind.generate_projects,
        payload={"parent_project_ids": parent_ids},
        func_path="app.workers.jobs.run_combine_projects",
    )
    return GenerateAccepted(job_id=job.id)


@router.get("", response_model=ProjectListResponse)
def list_projects(
    db: DbSession,
    status: Annotated[ProjectStatus | None, Query()] = None,
    domain: Annotated[str | None, Query(max_length=128)] = None,
) -> ProjectListResponse:
    """The whole library (single-user scale — no pagination). Sorting by the
    weighted score happens client-side from the returned sub-scores."""
    stmt = select(Project).order_by(Project.id.desc())
    if status is not None:
        stmt = stmt.where(Project.status == status)
    if domain is not None:
        stmt = stmt.where(Project.domains.contains([domain]))
    projects = [ProjectRead.model_validate(project) for project in db.scalars(stmt)]
    return ProjectListResponse(projects=projects, total=len(projects))


@router.get("/{project_id}", response_model=ProjectDetail)
def get_project(project_id: int, db: DbSession) -> ProjectDetail:
    project = _get_project_or_404(db, project_id)
    milestones = list(
        db.scalars(
            select(ProjectMilestone)
            .where(ProjectMilestone.project_id == project.id)
            .order_by(ProjectMilestone.sort_order, ProjectMilestone.id)
        )
    )
    detail = ProjectDetail.model_validate(project)
    detail.milestones = [MilestoneRead.model_validate(milestone) for milestone in milestones]
    return detail


@router.patch("/{project_id}", response_model=ProjectRead)
def update_project(project_id: int, body: ProjectUpdateRequest, db: DbSession) -> ProjectRead:
    project = _get_project_or_404(db, project_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(project, field, value)
    db.commit()
    return ProjectRead.model_validate(project)


@router.post(
    "/{project_id}/regenerate",
    response_model=GenerateAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def regenerate_project(project_id: int, db: DbSession, redis: RedisDep) -> GenerateAccepted:
    _get_project_or_404(db, project_id)
    job = enqueue_job(
        db,
        redis,
        kind=JobKind.generate_projects,
        payload={"project_id": project_id},
        func_path="app.workers.jobs.run_regenerate_project",
    )
    return GenerateAccepted(job_id=job.id)


@router.post(
    "/{project_id}/advisor",
    response_model=GenerateAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def request_advisor_review(project_id: int, db: DbSession, redis: RedisDep) -> GenerateAccepted:
    _get_project_or_404(db, project_id)
    job = enqueue_job(
        db,
        redis,
        kind=JobKind.generate_artifact,
        payload={"project_id": project_id},
        func_path="app.workers.jobs.run_advisor_review",
    )
    return GenerateAccepted(job_id=job.id)


@router.get("/{project_id}/advisor", response_model=list[AdvisorReviewRead])
def list_advisor_reviews(project_id: int, db: DbSession) -> list[AdvisorReviewRead]:
    _get_project_or_404(db, project_id)
    reviews = db.scalars(
        select(Artifact)
        .where(Artifact.project_id == project_id, Artifact.kind == ArtifactKind.advisor_review)
        .order_by(Artifact.version.desc())
    )
    return [AdvisorReviewRead.model_validate(review) for review in reviews]


# --- career artifacts (M8) ----------------------------------------------------


@router.post(
    "/{project_id}/artifacts/{kind}",
    response_model=GenerateAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def request_career_artifact(
    project_id: int, kind: CareerArtifactKind, db: DbSession, redis: RedisDep
) -> GenerateAccepted:
    _get_project_or_404(db, project_id)
    job = enqueue_job(
        db,
        redis,
        kind=JobKind.generate_artifact,
        payload={"project_id": project_id, "kind": kind.value},
        func_path="app.workers.jobs.run_generate_career_artifact",
    )
    return GenerateAccepted(job_id=job.id)


@router.get("/{project_id}/artifacts/{kind}", response_model=list[ArtifactRead])
def list_career_artifacts(
    project_id: int, kind: CareerArtifactKind, db: DbSession
) -> list[ArtifactRead]:
    _get_project_or_404(db, project_id)
    artifacts = db.scalars(
        select(Artifact)
        .where(Artifact.project_id == project_id, Artifact.kind == ArtifactKind(kind.value))
        .order_by(Artifact.version.desc())
    )
    return [ArtifactRead.model_validate(artifact) for artifact in artifacts]


@router.get("/{project_id}/artifacts", response_model=list[ArtifactRead])
def list_all_artifacts(project_id: int, db: DbSession) -> list[ArtifactRead]:
    """The latest version of every generated artifact kind (career kinds and
    the advisor review), for a status/summary view."""
    _get_project_or_404(db, project_id)
    return [
        ArtifactRead.model_validate(artifact)
        for artifact in latest_artifacts_by_kind(db, project_id)
    ]


# --- roadmap milestones -------------------------------------------------------


def _get_milestone_or_404(db: Session, project_id: int, milestone_id: int) -> ProjectMilestone:
    milestone = db.get(ProjectMilestone, milestone_id)
    if milestone is None or milestone.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=MILESTONE_NOT_FOUND_MESSAGE
        )
    return milestone


@router.post(
    "/{project_id}/milestones",
    response_model=MilestoneRead,
    status_code=status.HTTP_201_CREATED,
)
def create_milestone(project_id: int, body: MilestoneCreateRequest, db: DbSession) -> MilestoneRead:
    _get_project_or_404(db, project_id)
    max_order = db.scalar(
        select(ProjectMilestone.sort_order)
        .where(ProjectMilestone.project_id == project_id)
        .order_by(ProjectMilestone.sort_order.desc())
        .limit(1)
    )
    milestone = ProjectMilestone(
        project_id=project_id,
        title=body.title,
        description=body.description,
        status=body.status,
        target_date=body.target_date,
        sort_order=(max_order + 1) if max_order is not None else 0,
    )
    db.add(milestone)
    db.commit()
    return MilestoneRead.model_validate(milestone)


@router.patch("/{project_id}/milestones/{milestone_id}", response_model=MilestoneRead)
def update_milestone(
    project_id: int, milestone_id: int, body: MilestoneUpdateRequest, db: DbSession
) -> MilestoneRead:
    milestone = _get_milestone_or_404(db, project_id, milestone_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(milestone, field, value)
    db.commit()
    return MilestoneRead.model_validate(milestone)


@router.delete("/{project_id}/milestones/{milestone_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_milestone(project_id: int, milestone_id: int, db: DbSession) -> None:
    milestone = _get_milestone_or_404(db, project_id, milestone_id)
    db.delete(milestone)
    db.commit()


@router.put("/{project_id}/milestones/order", response_model=list[MilestoneRead])
def reorder_milestones(
    project_id: int, body: MilestoneOrderRequest, db: DbSession
) -> list[MilestoneRead]:
    """Full reorder: the body must list every milestone of the project exactly
    once; sort_order is rewritten 0..n in the given order."""
    _get_project_or_404(db, project_id)
    milestones = {
        milestone.id: milestone
        for milestone in db.scalars(
            select(ProjectMilestone).where(ProjectMilestone.project_id == project_id)
        )
    }
    if sorted(body.milestone_ids) != sorted(milestones) or len(body.milestone_ids) != len(
        set(body.milestone_ids)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "bad_order",
                "message": "milestone_ids must be an exact permutation of the project's milestones",
            },
        )
    for position, milestone_id in enumerate(body.milestone_ids):
        milestones[milestone_id].sort_order = position
    db.commit()
    ordered = sorted(milestones.values(), key=lambda milestone: milestone.sort_order)
    return [MilestoneRead.model_validate(milestone) for milestone in ordered]
