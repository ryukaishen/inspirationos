"""Central structured-output loop: budget check → call → validate → one
repair retry → hard failure.

Every provider call (success, invalid output, or error) writes an
`ai_requests` row — provider/model/task/tokens/cost/latency only, never text.
Validation errors are appended to the repair prompt (sent only back to the
same provider) and are never logged or stored; a second failure raises
StructuredOutputError, which the job layer records as a class name only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.config import AppConfig
from app.models.ai_request import AiRequest, AiRequestStatus
from app.models.app_settings import AppSettings
from app.services.ai import budget
from app.services.ai.provider import LLMProvider, RawGeneration

PROMPTS_DIR = Path(__file__).parent / "prompts"
PROMPT_VERSION = "v1"


class StructuredOutputError(Exception):
    """Provider output failed validation twice (initial + repair)."""


def load_prompt(task: str) -> str:
    return (PROMPTS_DIR / f"{task}_{PROMPT_VERSION}.txt").read_text(encoding="utf-8")


def _record_request(
    session: Session,
    *,
    job_id: int | None,
    provider: LLMProvider,
    model: str,
    task: str,
    raw: RawGeneration | None,
    status: AiRequestStatus,
) -> None:
    prompt_tokens = raw.prompt_tokens if raw else 0
    completion_tokens = raw.completion_tokens if raw else 0
    session.add(
        AiRequest(
            job_id=job_id,
            provider=provider.name,
            model=model,
            task=task,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            est_cost_usd=budget.estimate_cost_usd(
                provider.name, model, prompt_tokens, completion_tokens
            ),
            latency_ms=raw.latency_ms if raw else 0,
            status=status,
        )
    )
    # Commit immediately: the audit row must survive even when the job's
    # failure handler rolls the session back (only workers call this path).
    session.commit()


def generate_validated[SchemaT: BaseModel](
    session: Session,
    provider: LLMProvider,
    *,
    task: str,
    context: dict[str, Any],
    schema: type[SchemaT],
    model: str,
    config: AppConfig,
    job_id: int | None = None,
    token_tracker: budget.JobTokenTracker | None = None,
) -> SchemaT:
    """Parse → on failure, one repair retry with the validation errors
    appended → second failure raises StructuredOutputError. Budget caps are
    re-checked before each call; a provider exception is recorded and
    re-raised as-is."""
    settings = session.get(AppSettings, 1)
    instructions = load_prompt(task)

    last_error: Exception | None = None
    for attempt in (1, 2):
        budget.check_monthly_budget(session, settings, config)
        if token_tracker is not None:
            token_tracker.check()

        attempt_instructions = instructions
        if attempt == 2 and last_error is not None:
            attempt_instructions = (
                f"{instructions}\n\nYour previous response failed validation with the"
                f" following errors — return a corrected result that strictly matches"
                f" the schema:\n{str(last_error)[:2000]}"
            )

        try:
            raw = provider.generate_raw(
                task=task,
                instructions=attempt_instructions,
                context=context,
                schema=schema,
                model=model,
            )
        except Exception:
            _record_request(
                session,
                job_id=job_id,
                provider=provider,
                model=model,
                task=task,
                raw=None,
                status=AiRequestStatus.error,
            )
            raise
        if token_tracker is not None:
            token_tracker.record(raw.prompt_tokens, raw.completion_tokens)

        try:
            parsed = schema.model_validate(json.loads(raw.text))
        except (json.JSONDecodeError, ValidationError) as exc:
            last_error = exc
            _record_request(
                session,
                job_id=job_id,
                provider=provider,
                model=model,
                task=task,
                raw=raw,
                status=AiRequestStatus.invalid_output,
            )
            continue

        _record_request(
            session,
            job_id=job_id,
            provider=provider,
            model=model,
            task=task,
            raw=raw,
            status=AiRequestStatus.success,
        )
        return parsed

    raise StructuredOutputError(f"task {task} produced invalid output twice")
