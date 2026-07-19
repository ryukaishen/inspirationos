"""Topic/label helpers (M6): slugs, topic upserts, and LLM context assembly.

`build_llm_context_items` is the single place item text enters an LLM context
for analysis — it filters through `is_eligible_for_generation` (the
anti-hallucination gate from DATA_MODEL.md), so items without real text can
never reach a provider. `verify_echoed_item_ids` is the server-side grounding
check: the model must only reference item_ids it was given.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.analysis import Topic
from app.models.item import Item
from app.services.analysis.embeddings import embedding_text_for
from app.services.enrichment.policy import is_eligible_for_generation

_SLUG_RE = re.compile(r"[^a-z0-9]+")


class GroundingError(Exception):
    """The model referenced an item_id it was never given."""


def slugify(name: str) -> str:
    slug = _SLUG_RE.sub("-", name.lower()).strip("-")
    return slug[:128] or "topic"


def build_llm_context_items(
    items: list[Item], *, max_chars_per_item: int, max_items: int
) -> list[dict[str, Any]]:
    """[{item_id, text}] for eligible items only, truncated and capped."""
    context: list[dict[str, Any]] = []
    for item in items:
        if len(context) >= max_items:
            break
        if not is_eligible_for_generation(item):
            continue
        text = embedding_text_for(item)
        if text is None:
            continue
        context.append({"item_id": item.id, "text": text[:max_chars_per_item]})
    return context


def verify_echoed_item_ids(echoed: list[int], allowed: set[int]) -> None:
    unknown = sorted(set(echoed) - allowed)
    if unknown:
        # IDs only — never item text (redaction rule).
        raise GroundingError(f"model referenced unknown item_ids: {unknown}")


def get_or_create_topic(session: Session, name: str) -> Topic:
    slug = slugify(name)
    topic = session.scalar(select(Topic).where(Topic.slug == slug))
    if topic is None:
        topic = Topic(name=name.strip()[:128], slug=slug)
        session.add(topic)
        session.flush()
    return topic
