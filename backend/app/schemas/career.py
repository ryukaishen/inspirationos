"""Career-profile schemas (M7). The profile is user-authored context injected
into generation prompts — it is private data, never logged."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CareerProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    background_md: str | None
    skills: list[Any]
    target_domains: list[str]
    experience_level: str | None
    constraints: dict[str, Any]
    interests_md: str | None


class CareerProfileUpdate(BaseModel):
    """Full replace of the singleton's editable fields (PUT semantics)."""

    model_config = ConfigDict(extra="forbid")

    background_md: str | None = None
    skills: list[str] = []
    target_domains: list[str] = []
    experience_level: str | None = Field(default=None, max_length=64)
    constraints: dict[str, Any] = {}
    interests_md: str | None = None
