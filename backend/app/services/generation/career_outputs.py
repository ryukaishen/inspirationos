"""Career artifacts (M8): README plan, resume bullets, portfolio description,
interview answer, likely technical questions — one generation-tier call per
kind, grounded in the project's own already-generated fields (the same
verified representation `services/generation/advisor.py` uses), never a
re-fetch of raw source item text.

Each kind pairs a Pydantic schema (`services/ai/schemas.py`) with a markdown
renderer for `content_md`. `workers/jobs.py::run_generate_career_artifact` is
the single dispatcher that looks these up by `ArtifactKind` instead of
duplicating `run_advisor_review`'s shape five times.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.artifact import Artifact, ArtifactKind
from app.models.project import Project
from app.services.ai.schemas import (
    TASK_INTERVIEW_ANSWER,
    TASK_PORTFOLIO_DESC,
    TASK_README,
    TASK_RESUME_BULLETS,
    TASK_TECH_QUESTIONS,
    InterviewAnswer,
    PortfolioDescription,
    ReadmePlan,
    ResumeBullets,
    TechQuestions,
)


def build_career_artifact_context(
    project: Project, career_profile: dict[str, Any]
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
            "scores": dict(project.scores or {}),
        },
        "career_profile": career_profile,
    }


def render_readme_markdown(plan: ReadmePlan) -> str:
    features = "\n".join(f"- {feature}" for feature in plan.features)
    return (
        f"# {plan.title}\n\n"
        f"{plan.overview_md}\n\n"
        f"## Features\n\n{features}\n\n"
        f"## Architecture\n\n{plan.architecture_md}\n\n"
        f"## Setup\n\n{plan.setup_md}\n\n"
        f"## Roadmap\n\n{plan.roadmap_md}\n"
    )


def render_resume_bullets_markdown(bullets: ResumeBullets) -> str:
    return "\n".join(f"- {bullet}" for bullet in bullets.bullets) + "\n"


def render_portfolio_desc_markdown(description: PortfolioDescription) -> str:
    highlights = "\n".join(f"- {highlight}" for highlight in description.highlights)
    return (
        f"## {description.headline}\n\n"
        f"{description.description_md}\n\n"
        f"### Highlights\n\n{highlights}\n"
    )


def render_interview_answer_markdown(answer: InterviewAnswer) -> str:
    points = "\n".join(f"- {point}" for point in answer.talking_points)
    return f"**Q: {answer.prompt}**\n\n{answer.answer_md}\n\n### Talking points\n\n{points}\n"


def render_tech_questions_markdown(questions: TechQuestions) -> str:
    sections = "\n\n".join(
        f"**Q: {entry.question}**\n\n{entry.answer_md}" for entry in questions.questions
    )
    return f"{sections}\n"


@dataclass(frozen=True)
class CareerArtifactSpec:
    task: str
    schema: type[BaseModel]
    render_markdown: Any


CAREER_ARTIFACT_SPECS: dict[ArtifactKind, CareerArtifactSpec] = {
    ArtifactKind.readme: CareerArtifactSpec(TASK_README, ReadmePlan, render_readme_markdown),
    ArtifactKind.resume_bullets: CareerArtifactSpec(
        TASK_RESUME_BULLETS, ResumeBullets, render_resume_bullets_markdown
    ),
    ArtifactKind.portfolio_desc: CareerArtifactSpec(
        TASK_PORTFOLIO_DESC, PortfolioDescription, render_portfolio_desc_markdown
    ),
    ArtifactKind.interview_answer: CareerArtifactSpec(
        TASK_INTERVIEW_ANSWER, InterviewAnswer, render_interview_answer_markdown
    ),
    ArtifactKind.tech_questions: CareerArtifactSpec(
        TASK_TECH_QUESTIONS, TechQuestions, render_tech_questions_markdown
    ),
}


def latest_artifacts_by_kind(session: Session, project_id: int) -> list[Artifact]:
    """The latest version of every generated artifact kind for a project
    (one row per kind that has at least one version) — used by the artifact
    summary endpoint and by export."""
    latest_versions = (
        select(Artifact.kind, func.max(Artifact.version).label("version"))
        .where(Artifact.project_id == project_id)
        .group_by(Artifact.kind)
        .subquery()
    )
    rows = session.scalars(
        select(Artifact)
        .join(
            latest_versions,
            (Artifact.kind == latest_versions.c.kind)
            & (Artifact.version == latest_versions.c.version),
        )
        .where(Artifact.project_id == project_id)
        .order_by(Artifact.kind)
    )
    return list(rows)
