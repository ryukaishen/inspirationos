"""Combine-two-ideas flow (M7): two parent projects -> one combined child.

The provider sees only the two parents' generated descriptions plus the
career profile; provenance is not echoed — the child's `source` is the union
of the parents' source ids, and `parent_project_ids` links both parents.
"""

from __future__ import annotations

from typing import Any

from app.models.project import Project


def build_combine_context(parents: list[Project], career_profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "parents": [
            {
                "project_id": parent.id,
                "title": parent.title,
                "one_liner": parent.one_liner,
                "summary_md": parent.summary_md,
                "domains": list(parent.domains or []),
                "tech_stack": list(parent.tech_stack or []),
                "skills_demonstrated": list(parent.skills_demonstrated or []),
            }
            for parent in parents
        ],
        "career_profile": career_profile,
    }


def combined_source_ids(parents: list[Project]) -> tuple[list[int], list[int]]:
    """Union of the parents' provenance (item_ids, cluster_ids)."""
    item_ids: set[int] = set()
    cluster_ids: set[int] = set()
    for parent in parents:
        source = parent.source or {}
        item_ids.update(int(value) for value in source.get("item_ids", []))
        cluster_ids.update(int(value) for value in source.get("cluster_ids", []))
    return sorted(item_ids), sorted(cluster_ids)
