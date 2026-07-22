from pydantic import BaseModel


class ImportDeletionRequest(BaseModel):
    """Typed confirmation: `confirm_text` must exactly match the import's
    filename. `cascade=False` keeps derived items with their source refs
    nulled; `cascade=True` deletes them too."""

    confirm_text: str
    cascade: bool = False


class ImportDeletionReport(BaseModel):
    conversations_deleted: int
    messages_deleted: int
    items_deleted: int
    items_kept: int
    file_deleted: bool


class ProjectDeletionRequest(BaseModel):
    confirm_text: str


class WipeRequest(BaseModel):
    """Typed confirmation: `confirm_email` must exactly match the single
    user's email."""

    confirm_email: str


class WipeAccepted(BaseModel):
    job_id: int
