"""Project generation service (M7): source expansion, context assembly,
grounding verification, and persistence.

Context assembly reuses `topics.build_llm_context_items`, so the
anti-hallucination gate (`is_eligible_for_generation`) is the same code path
analysis uses — a `needs_context` item can never reach a provider. Echoed
source ids are verified server-side; a fabricated citation fails the job
(`GroundingError`, ids only in the message).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import AppConfig
from app.models.analysis import Cluster, ItemCluster
from app.models.career_profile import CareerProfile
from app.models.item import Item
from app.models.project import Project
from app.services.ai.schemas import ProjectFields, ProjectIdea
from app.services.analysis.topics import (
    GroundingError,
    build_llm_context_items,
    verify_echoed_item_ids,
)

CAREER_PROFILE_ID = 1


class NoEligibleItemsError(Exception):
    """None of the requested source items carries any real text."""


def resolve_source_item_ids(
    session: Session, *, item_ids: list[int], cluster_ids: list[int]
) -> list[int]:
    """Explicit item ids plus the member items of the given clusters, deduped
    and ordered. Ids only — no text leaves this function."""
    resolved: set[int] = set(item_ids)
    if cluster_ids:
        member_ids = session.scalars(
            select(ItemCluster.item_id).where(ItemCluster.cluster_id.in_(cluster_ids))
        )
        resolved.update(member_ids)
    return sorted(resolved)


def serialize_career_profile(profile: CareerProfile | None) -> dict[str, Any]:
    """Prompt-context representation. Sent to the configured provider only —
    never logged, never stored in ai_requests."""
    if profile is None:
        return {}
    return {
        "background": profile.background_md or "",
        "skills": list(profile.skills or []),
        "target_domains": list(profile.target_domains or []),
        "experience_level": profile.experience_level or "",
        "constraints": dict(profile.constraints or {}),
        "interests": profile.interests_md or "",
    }


def load_career_profile_context(session: Session) -> dict[str, Any]:
    return serialize_career_profile(session.get(CareerProfile, CAREER_PROFILE_ID))


def build_generation_context(
    session: Session,
    config: AppConfig,
    *,
    item_ids: list[int],
    cluster_ids: list[int],
    count: int,
) -> tuple[dict[str, Any], set[int]]:
    """Returns (provider context, allowed item id set for grounding checks).

    Raises NoEligibleItemsError when no requested item passes the
    text-eligibility gate — generation from undescribed reels is refused in
    code, not just in prompts.
    """
    source_item_ids = resolve_source_item_ids(session, item_ids=item_ids, cluster_ids=cluster_ids)
    items = list(
        session.scalars(select(Item).where(Item.id.in_(source_item_ids)).order_by(Item.id))
    )
    context_items = build_llm_context_items(
        items,
        max_chars_per_item=config.projects_max_chars_per_item,
        max_items=config.projects_max_items,
    )
    if not context_items:
        raise NoEligibleItemsError
    clusters = list(
        session.scalars(select(Cluster).where(Cluster.id.in_(cluster_ids)).order_by(Cluster.id))
    )
    context = {
        "items": context_items,
        "clusters": [
            {
                "cluster_id": cluster.id,
                "label": cluster.label or "",
                "description": cluster.description_md or "",
            }
            for cluster in clusters
        ],
        "career_profile": load_career_profile_context(session),
        "count": count,
    }
    allowed_item_ids = {entry["item_id"] for entry in context_items}
    return context, allowed_item_ids


def verify_idea_grounding(
    idea: ProjectIdea, *, allowed_item_ids: set[int], allowed_cluster_ids: set[int]
) -> None:
    verify_echoed_item_ids(idea.source_item_ids, allowed_item_ids)
    unknown = sorted(set(idea.source_cluster_ids) - allowed_cluster_ids)
    if unknown:
        # IDs only — never generated text (redaction rule).
        raise GroundingError(f"model referenced unknown cluster_ids: {unknown}")


def apply_generated_fields(project: Project, fields: ProjectFields) -> None:
    """Write the generated fields onto a Project. Used by both fresh
    generation and regeneration — deliberately does not touch user-owned
    state (status, milestones, parent links)."""
    project.title = fields.title
    project.one_liner = fields.one_liner
    project.summary_md = fields.summary_md
    project.domains = list(fields.domains)
    project.difficulty = fields.difficulty
    project.duration_estimate = fields.duration_estimate
    project.datasets = list(fields.datasets)
    project.tech_stack = list(fields.tech_stack)
    project.skills_demonstrated = list(fields.skills_demonstrated)
    project.risks = list(fields.risks)
    project.scores = fields.scores.model_dump()


def generation_source(
    *,
    item_ids: list[int],
    cluster_ids: list[int],
    prompt_version: str,
    provider: str,
    model: str,
) -> dict[str, Any]:
    """The `projects.source` provenance payload — ids and config only."""
    return {
        "item_ids": sorted(set(item_ids)),
        "cluster_ids": sorted(set(cluster_ids)),
        "prompt_version": prompt_version,
        "provider": provider,
        "model": model,
    }
