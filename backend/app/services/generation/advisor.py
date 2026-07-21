"""Project Advisor (M7): structured critique of one project, versioned.

The review is stored as an `artifacts` row (`kind=advisor_review`): the
validated AdvisorReview payload in `payload` (the UI renders the five
sections from it) plus a markdown rendering in `content_md` (reused by the M8
export). Regeneration appends the next version; earlier versions stay.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.artifact import Artifact, ArtifactKind
from app.models.project import Project
from app.services.ai.schemas import AdvisorReview


def build_advisor_context(
    project: Project, library: list[Project], career_profile: dict[str, Any]
) -> dict[str, Any]:
    return {
        "project": {
            "title": project.title,
            "one_liner": project.one_liner,
            "summary_md": project.summary_md,
            "domains": list(project.domains or []),
            "difficulty": project.difficulty or "",
            "duration_estimate": project.duration_estimate or "",
            "datasets": list(project.datasets or []),
            "tech_stack": list(project.tech_stack or []),
            "skills_demonstrated": list(project.skills_demonstrated or []),
            "risks": list(project.risks or []),
        },
        "library": [
            {"project_id": other.id, "title": other.title, "one_liner": other.one_liner}
            for other in library
            if other.id != project.id
        ],
        "career_profile": career_profile,
    }


def render_advisor_markdown(review: AdvisorReview) -> str:
    """Human-readable rendering of the five sections for content_md."""
    weeks = "\n".join(
        f"- **Week {entry.week}:** {entry.focus} — _{entry.deliverable}_"
        for entry in review.week_by_week
    )
    prerequisites = "\n".join(f"- {entry}" for entry in review.prerequisites)
    return (
        f"## Commonality: {review.commonality.verdict.replace('_', ' ')}\n\n"
        f"{review.commonality.reasoning}\n\n"
        f"## Comparative strength\n\n{review.comparative_strength}\n\n"
        f"## Recruiter impact\n\n{review.recruiter_impact}\n\n"
        f"## Prerequisites\n\n{prerequisites}\n\n"
        f"## Week-by-week plan\n\n{weeks}\n"
    )


def next_artifact_version(session: Session, project_id: int, kind: ArtifactKind) -> int:
    current = session.scalar(
        select(func.max(Artifact.version)).where(
            Artifact.project_id == project_id, Artifact.kind == kind
        )
    )
    return (current or 0) + 1
