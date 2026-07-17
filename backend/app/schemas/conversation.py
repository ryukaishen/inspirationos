from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ConversationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    import_id: int
    thread_path: str
    title: str | None
    participant_names: list[str]
    message_count: int
    link_count: int
    is_self_dm_candidate: bool
    is_selected: bool
    first_message_at: datetime | None
    last_message_at: datetime | None
    created_at: datetime


class SelectionRequest(BaseModel):
    """Replace-semantics selection: listed conversations become selected,
    every other conversation of the import is deselected."""

    conversation_ids: list[int] = Field(min_length=1)


class ExtractAccepted(BaseModel):
    job_id: int
