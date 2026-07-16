"""Demo job loop against real Redis + Postgres: the production enqueue path
(dotted string), drained synchronously with an RQ SimpleWorker."""

from collections.abc import Generator

import pytest
from redis import Redis
from rq import Queue, SimpleWorker
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.models.job import Job, JobKind, JobStatus
from app.queues import QUEUE_IMPORTS
from app.workers.jobs import run_demo_job

pytestmark = pytest.mark.integration


@pytest.fixture
def make_job(pg_engine: Engine) -> Generator:
    """Creates really-committed job rows (the worker uses its own connection),
    deleting them afterwards."""
    created: list[int] = []

    def _make(total: int) -> Job:
        with Session(pg_engine, expire_on_commit=False) as session:
            job = Job(kind=JobKind.demo, status=JobStatus.queued, total=total, payload={})
            session.add(job)
            session.commit()
            created.append(job.id)
            return job

    yield _make
    with Session(pg_engine) as session:
        for job_id in created:
            row = session.get(Job, job_id)
            if row is not None:
                session.delete(row)
        session.commit()


# Dedicated queue name: a running dev compose worker also consumes "imports"
# and must not race this test's SimpleWorker for the enqueued job.
TEST_QUEUE = f"{QUEUE_IMPORTS}-test-demo"


@pytest.fixture
def imports_queue(redis_client: Redis) -> Generator[Queue, None, None]:
    queue = Queue(TEST_QUEUE, connection=redis_client)
    yield queue
    queue.empty()


def _reload(pg_engine: Engine, job_id: int) -> Job:
    with Session(pg_engine) as session:
        job = session.get(Job, job_id)
        assert job is not None
        return job


def test_demo_job_transitions_to_succeeded(
    make_job, imports_queue: Queue, redis_client: Redis, pg_engine: Engine
) -> None:
    job = make_job(3)
    imports_queue.enqueue("app.workers.jobs.run_demo_job", job.id, 3, 0)

    SimpleWorker([imports_queue], connection=redis_client).work(burst=True)

    row = _reload(pg_engine, job.id)
    assert row.status is JobStatus.succeeded
    assert row.progress == row.total == 3
    assert row.started_at is not None
    assert row.finished_at is not None
    assert row.error is None


def test_demo_job_failure_records_redacted_error(make_job, pg_engine: Engine) -> None:
    job = make_job(3)
    with pytest.raises(RuntimeError):
        run_demo_job(job.id, steps=3, step_seconds=0, fail_at_step=2)

    row = _reload(pg_engine, job.id)
    assert row.status is JobStatus.failed
    assert row.error == "RuntimeError"  # class name only — never message text
    assert row.progress == 1
    assert row.finished_at is not None


def test_demo_job_rerun_of_finished_job_is_noop(make_job, pg_engine: Engine) -> None:
    job = make_job(2)
    run_demo_job(job.id, steps=2, step_seconds=0)
    first = _reload(pg_engine, job.id)

    run_demo_job(job.id, steps=2, step_seconds=0)
    second = _reload(pg_engine, job.id)

    assert second.status is JobStatus.succeeded
    assert second.finished_at == first.finished_at
    assert second.progress == first.progress
