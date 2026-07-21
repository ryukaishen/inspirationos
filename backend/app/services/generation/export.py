"""Markdown/JSON export bundles (M8): a project (with milestones and its
latest artifact per kind) or the full project library, rendered through the
existing `Storage` abstraction. Content is assembled purely from
already-generated `Project`/`Artifact`/`ProjectMilestone` rows — never raw
message text.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project, ProjectMilestone
from app.schemas.export import ArtifactExport, LibraryExport, MilestoneExport, ProjectExport
from app.services.generation.career_outputs import latest_artifacts_by_kind


def build_project_export(session: Session, project: Project) -> ProjectExport:
    milestones = session.scalars(
        select(ProjectMilestone)
        .where(ProjectMilestone.project_id == project.id)
        .order_by(ProjectMilestone.sort_order)
    )
    artifacts = latest_artifacts_by_kind(session, project.id)
    return ProjectExport(
        id=project.id,
        title=project.title,
        one_liner=project.one_liner,
        summary_md=project.summary_md,
        domains=list(project.domains or []),
        difficulty=project.difficulty,
        duration_estimate=project.duration_estimate,
        tech_stack=list(project.tech_stack or []),
        skills_demonstrated=list(project.skills_demonstrated or []),
        risks=list(project.risks or []),
        scores=dict(project.scores or {}),
        status=project.status,
        milestones=[
            MilestoneExport(
                title=milestone.title,
                description=milestone.description,
                status=milestone.status,
                sort_order=milestone.sort_order,
                target_date=milestone.target_date,
            )
            for milestone in milestones
        ],
        artifacts=[
            ArtifactExport(
                kind=artifact.kind.value,
                version=artifact.version,
                content_md=artifact.content_md,
                payload=artifact.payload,
                claims_flags=list(artifact.claims_flags or []),
                provider=artifact.provider,
                model=artifact.model,
                created_at=artifact.created_at,
            )
            for artifact in artifacts
        ],
    )


def build_library_export(session: Session) -> LibraryExport:
    projects = session.scalars(select(Project).order_by(Project.id))
    return LibraryExport(
        generated_at=datetime.now(UTC),
        projects=[build_project_export(session, project) for project in projects],
    )


def render_project_markdown(export: ProjectExport) -> str:
    sections = [f"# {export.title}\n\n{export.one_liner}\n\n{export.summary_md}"]
    if export.milestones:
        milestone_lines = "\n".join(
            f"- [{milestone.status.value}] {milestone.title}" for milestone in export.milestones
        )
        sections.append(f"## Roadmap\n\n{milestone_lines}")
    for artifact in export.artifacts:
        heading = artifact.kind.replace("_", " ").title()
        warning = (
            f"\n\n> **Claims flagged for review:** {'; '.join(artifact.claims_flags)}"
            if artifact.claims_flags
            else ""
        )
        sections.append(f"## {heading} (v{artifact.version}){warning}\n\n{artifact.content_md}")
    return "\n\n---\n\n".join(sections) + "\n"


def render_library_markdown(export: LibraryExport) -> str:
    if not export.projects:
        return "# Project Library\n\nNo projects yet.\n"
    return "\n\n===\n\n".join(render_project_markdown(project) for project in export.projects)
