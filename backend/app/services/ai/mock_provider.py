"""Deterministic offline LLM provider — the dev/CI default.

Outputs are derived purely from the task + input context (token frequency and
sha256 hashes), so identical inputs always produce identical, schema-valid
results with zero network I/O and zero cost. Topic names and labels come from
the most frequent meaningful tokens of the input texts, which makes fixture
assertions readable ("pasta cooking" rather than an opaque hash).
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections import Counter
from typing import Any, Literal

from pydantic import BaseModel

from app.services.ai.provider import LLMProvider, ModelTier, ProviderError, RawGeneration
from app.services.ai.schemas import (
    TASK_ADVISOR_REVIEW,
    TASK_CLUSTER_LABEL,
    TASK_COMBINE_PROJECTS,
    TASK_GENERATE_PROJECTS,
    TASK_TOPIC_EXTRACTION,
    AdvisorReview,
    ClusterLabel,
    CombinedProject,
    CommonalityVerdict,
    ItemTopics,
    ProjectIdea,
    ProjectIdeas,
    ProjectScores,
    SubScore,
    TopicAssignmentEntry,
    TopicExtraction,
    WeekPlanEntry,
)

MOCK_MODEL = "mock-llm-v1"

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    [
        *("a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from"),
        *("has", "have", "if", "in", "into", "is", "it", "its", "of", "on", "or"),
        *("so", "that", "the", "this", "to", "was", "were", "will", "with", "you"),
        *("your", "check", "out", "look", "reel", "post", "video", "synthetic"),
        *("run", "marker", "about"),
    ]
)


def _meaningful_tokens(text: str) -> list[str]:
    return [
        token
        for token in _TOKEN_RE.findall(text.lower())
        if len(token) >= 3 and token not in _STOPWORDS
    ]


def _top_tokens(texts: list[str], count: int) -> list[str]:
    counter: Counter[str] = Counter()
    for text in texts:
        counter.update(_meaningful_tokens(text))
    # Deterministic order: frequency desc, then alphabetical.
    ranked = sorted(counter.items(), key=lambda pair: (-pair[1], pair[0]))
    return [token for token, _ in ranked[:count]]


def _confidence_for(seed: str) -> float:
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return round(0.6 + (digest[0] / 255) * 0.39, 3)


def _score_for(seed: str) -> float:
    """Deterministic 3.0-9.5 sub-score — spread out so re-rank tests see
    genuinely different orderings under different weights."""
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return round(3.0 + (digest[0] / 255) * 6.5, 1)


class MockProvider(LLMProvider):
    name = "mock"

    def resolve_model(self, tier: ModelTier) -> str:
        return MOCK_MODEL

    def generate_raw(
        self,
        *,
        task: str,
        instructions: str,
        context: dict[str, Any],
        schema: type[BaseModel],
        model: str,
    ) -> RawGeneration:
        started = time.monotonic()
        payload: BaseModel
        if task == TASK_TOPIC_EXTRACTION:
            payload = self._topic_extraction(context)
        elif task == TASK_CLUSTER_LABEL:
            payload = self._cluster_label(context)
        elif task == TASK_GENERATE_PROJECTS:
            payload = self._generate_projects(context)
        elif task == TASK_COMBINE_PROJECTS:
            payload = self._combine_projects(context)
        elif task == TASK_ADVISOR_REVIEW:
            payload = self._advisor_review(context)
        else:
            raise ProviderError(f"mock provider has no generator for task {task!r}")
        text = payload.model_dump_json()
        serialized_input = json.dumps(context, sort_keys=True, ensure_ascii=False)
        return RawGeneration(
            text=text,
            prompt_tokens=max(1, (len(instructions) + len(serialized_input)) // 4),
            completion_tokens=max(1, len(text) // 4),
            latency_ms=int((time.monotonic() - started) * 1000),
        )

    def _topic_extraction(self, context: dict[str, Any]) -> TopicExtraction:
        assignments: list[ItemTopics] = []
        for entry in context.get("items", []):
            text = str(entry.get("text", ""))
            tokens = _top_tokens([text], 2)
            names = [" ".join(tokens)] if tokens else ["uncategorized"]
            assignments.append(
                ItemTopics(
                    item_id=int(entry["item_id"]),
                    topics=[
                        TopicAssignmentEntry(
                            name=name, confidence=_confidence_for(f"topic:{name}:{text}")
                        )
                        for name in names
                    ],
                )
            )
        return TopicExtraction(assignments=assignments)

    def _cluster_label(self, context: dict[str, Any]) -> ClusterLabel:
        texts = [str(entry.get("text", "")) for entry in context.get("items", [])]
        tokens = _top_tokens(texts, 2)
        label = " ".join(tokens).title() if tokens else "Unlabeled Cluster"
        description = (
            f"Items in this cluster share text about {' and '.join(tokens)}."
            if tokens
            else "Items in this cluster carry no dominant shared vocabulary."
        )
        return ClusterLabel(label=label, description_md=description)

    def _project_scores(self, seed: str) -> ProjectScores:
        return ProjectScores(
            **{
                dimension: SubScore(
                    score=_score_for(f"{dimension}:{seed}"),
                    rationale=(
                        f"Deterministic mock assessment of {dimension.replace('_', ' ')} "
                        f"for this idea."
                    ),
                )
                for dimension in ProjectScores.model_fields
            }
        )

    def _generate_projects(self, context: dict[str, Any]) -> ProjectIdeas:
        items = list(context.get("items", []))
        if not items:
            raise ProviderError("mock generate_projects requires at least one context item")
        count = max(1, int(context.get("count", 1)))
        profile = context.get("career_profile") or {}
        profile_domains = [
            str(domain) for domain in profile.get("target_domains", []) if str(domain).strip()
        ]
        cluster_ids = [int(entry["cluster_id"]) for entry in context.get("clusters", [])]
        ideas: list[ProjectIdea] = []
        for index in range(count):
            # Round-robin partition so each idea grounds in a distinct subset;
            # once ideas outnumber items, reuse the full set.
            subset = items[index::count] or items
            texts = [str(entry.get("text", "")) for entry in subset]
            tokens = _top_tokens(texts, 3) or ["general"]
            theme = " ".join(tokens)
            title = f"{theme.title()} Project {index + 1}"[:256]
            ideas.append(
                ProjectIdea(
                    title=title,
                    one_liner=f"A portfolio project grounded in saved items about {theme}."[:300],
                    summary_md=(
                        f"## {title}\n\nBuild a project around **{theme}**, grounded in "
                        f"{len(subset)} saved inspiration item(s). This deterministic mock "
                        f"summary is derived purely from the provided item texts."
                    ),
                    domains=profile_domains[:2] or ["applied ai"],
                    difficulty="intermediate",
                    duration_estimate="4-6 weeks",
                    datasets=[],
                    tech_stack=["python", "postgresql"],
                    skills_demonstrated=tokens,
                    risks=["scope creep"],
                    scores=self._project_scores(f"{theme}:{index}"),
                    source_item_ids=[int(entry["item_id"]) for entry in subset],
                    source_cluster_ids=cluster_ids,
                )
            )
        return ProjectIdeas(ideas=ideas)

    def _combine_projects(self, context: dict[str, Any]) -> CombinedProject:
        parents = list(context.get("parents", []))
        if len(parents) != 2:
            raise ProviderError("mock combine_projects requires exactly two parents")
        parent_texts = [
            f"{parent.get('title', '')} {parent.get('one_liner', '')}" for parent in parents
        ]
        tokens = _top_tokens(parent_texts, 3) or ["combined"]
        theme = " ".join(tokens)
        first = str(parents[0].get("title", "Parent A"))[:100]
        second = str(parents[1].get("title", "Parent B"))[:100]
        title = f"Combined: {first} x {second}"[:256]
        tech_stack = sorted(
            {
                str(entry)
                for parent in parents
                for entry in parent.get("tech_stack", [])
                if str(entry).strip()
            }
        ) or ["python"]
        skills = (
            sorted(
                {
                    str(entry)
                    for parent in parents
                    for entry in parent.get("skills_demonstrated", [])
                    if str(entry).strip()
                }
            )
            or tokens
        )
        return CombinedProject(
            title=title,
            one_liner=f"A combined project merging both parent ideas around {theme}."[:300],
            summary_md=(
                f"## {title}\n\nMerges **{first}** and **{second}** into one project "
                f"about {theme}. This deterministic mock summary is derived purely "
                f"from the two parent descriptions."
            ),
            domains=[
                str(domain)
                for parent in parents
                for domain in parent.get("domains", [])
                if str(domain).strip()
            ][:4]
            or ["applied ai"],
            difficulty="advanced",
            duration_estimate="6-8 weeks",
            datasets=[],
            tech_stack=tech_stack[:15],
            skills_demonstrated=skills[:15],
            risks=["combined scope is larger than either parent"],
            scores=self._project_scores(f"combine:{theme}"),
        )

    def _advisor_review(self, context: dict[str, Any]) -> AdvisorReview:
        project = context.get("project") or {}
        title = str(project.get("title", "the project"))
        library = list(context.get("library", []))
        tokens = _top_tokens(
            [f"{title} {project.get('one_liner', '')} {project.get('summary_md', '')}"], 3
        ) or ["project"]
        verdicts: tuple[Literal["very_common", "common", "uncommon", "novel"], ...] = (
            "very_common",
            "common",
            "uncommon",
            "novel",
        )
        digest = hashlib.sha256(f"verdict:{title}".encode()).digest()
        verdict = verdicts[digest[0] % len(verdicts)]
        return AdvisorReview(
            commonality=CommonalityVerdict(
                verdict=verdict,
                reasoning=(
                    f"Deterministic mock verdict for '{title}' derived from its "
                    f"token profile ({', '.join(tokens)})."
                ),
            ),
            comparative_strength=(
                f"Compared against {len(library)} other project(s) in the library, "
                f"'{title}' is assessed deterministically on its {', '.join(tokens)} focus."
            ),
            recruiter_impact=(
                f"A recruiter scanning for {', '.join(tokens)} work would register "
                f"'{title}' as a concrete, explainable build."
            ),
            prerequisites=[f"Fundamentals of {token}" for token in tokens],
            week_by_week=[
                WeekPlanEntry(
                    week=week,
                    focus=f"Mock week {week} focus on {tokens[(week - 1) % len(tokens)]}",
                    deliverable=f"Mock deliverable {week} for '{title}'"[:300],
                )
                for week in range(1, 5)
            ],
        )
