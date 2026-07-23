"""Stale-job reconciliation.

A worker that dies hard mid-job (OOM-kill, host reboot, container crash —
anything other than a clean exception or a graceful SIGTERM) leaves its
`jobs` row stuck at `running` forever: RQ's own dead-worker bookkeeping is
internal to Redis and never writes back to this table, so nothing else
would ever notice (confirmed empirically in a live drill — see
docs/REAL_DATA_VERIFICATION.md). Rather than run a separate always-on
scheduler process to watch for this (unnecessary complexity for a
single-user app), every read of a job's status lazily checks for staleness
and self-heals in place — the same pattern session/cache expiry commonly
uses. A graceful worker restart is unaffected: RQ's warm shutdown finishes
the in-flight job before the process exits, so it never reaches this path.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.config import get_config
from app.models.job import Job, JobStatus

STALE_JOB_ERROR = "JobStalledError"


def reconcile_stale_job(session: Session, job: Job) -> Job:
    """No-op unless `job` is `running` and has been for longer than
    `AppConfig.job_stale_after_seconds` — then marks it `failed` in place
    (commits) so the UI stops showing "running" forever."""
    if job.status is not JobStatus.running or job.started_at is None:
        return job
    age_seconds = (datetime.now(UTC) - job.started_at).total_seconds()
    if age_seconds <= get_config().job_stale_after_seconds:
        return job
    job.status = JobStatus.failed
    job.error = STALE_JOB_ERROR
    job.finished_at = datetime.now(UTC)
    session.commit()
    return job
