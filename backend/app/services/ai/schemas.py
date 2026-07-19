"""Shared Pydantic task schemas every LLM provider must validate against.

M6 tasks only (topic extraction, cluster labeling); M7/M8 add their own here.
Providers never define their own output shapes — the same schema drives the
Anthropic tool input_schema, the OpenAI json_schema response format, and the
Mock provider's constructed output.
"""

from pydantic import BaseModel, Field

TASK_TOPIC_EXTRACTION = "topic_extraction"
TASK_CLUSTER_LABEL = "cluster_label"


class TopicAssignmentEntry(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    confidence: float = Field(ge=0.0, le=1.0)


class ItemTopics(BaseModel):
    item_id: int
    topics: list[TopicAssignmentEntry] = Field(min_length=1, max_length=5)


class TopicExtraction(BaseModel):
    """Per-item topic assignments; item_ids are echoed and verified server-side."""

    assignments: list[ItemTopics]


class ClusterLabel(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    description_md: str = Field(min_length=1)
