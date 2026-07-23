"""Performance benchmark (M10): scan/extract timing + inbox-API p95 latency
against the ~5,000-message *synthetic* perf fixture.

This measures the targets from docs/IMPLEMENTATION_PLAN.md's Milestone 10
against `fixture_builder.build_perf_export_zip` — it does **not** touch a
real Instagram export (none is used or required here). Targets:
scan < 60s, extract < 180s, inbox `GET /api/items` p95 < 300ms.

Requires Postgres + Redis reachable (same services the integration test
suite needs — Redis backs the session used for the inbox-API measurement).
Commits real rows against whatever `DATABASE_URL` is configured, like
`app/cli.py` — never against a rolled-back test transaction — so it cleans
up its own throwaway import in a `finally` block. It never creates or
deletes user accounts: pass `--email`/`--password` for an account already
seeded via `python -m app.cli create-user`, or set
`BENCHMARK_EMAIL`/`BENCHMARK_PASSWORD`. Never logs or prints message
content — only counts and timings.

    cd backend && python scripts/benchmark_import.py --email you@example.com
"""

from __future__ import annotations

import os

# TestClient talks plain http://testserver via stdlib http.cookiejar, which
# (unlike a real browser) has no "localhost is a secure context" exception
# and silently drops Secure-flagged cookies — same fix as tests/conftest.py,
# must be set before the first get_config() call. Real dev/prod are
# unaffected (AppConfig.session_cookie_secure defaults to True there).
os.environ.setdefault("SESSION_COOKIE_SECURE", "false")

import argparse
import getpass
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

# fixture_builder.py is deliberately stdlib-only and lives under tests/, not
# on the normal import path for a standalone script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from fastapi.testclient import TestClient
from fixture_builder import build_perf_export_zip
from sqlalchemy import update

from app.config import get_config
from app.db import get_sessionmaker
from app.main import app
from app.models.conversation import Conversation
from app.models.import_ import ExportFormat, Import, ImportStatus
from app.models.job import Job, JobKind, JobStatus
from app.services.privacy.deletion import delete_raw_import
from app.services.storage.local import LocalStorage
from app.workers.jobs import run_import_extract, run_import_scan

CSRF_HEADERS = {"X-Requested-With": "XMLHttpRequest"}

SCAN_TARGET_SECONDS = 60
EXTRACT_TARGET_SECONDS = 180
INBOX_P95_TARGET_MS = 300
INBOX_SAMPLE_REQUESTS = 50


def _create_throwaway_import(zip_path: Path) -> tuple[int, int]:
    storage = LocalStorage(get_config().data_dir)
    key = f"imports/benchmark-{uuid4().hex}.zip"
    size_bytes = zip_path.stat().st_size  # save_file() moves the file — stat it first
    storage.save_file(key, zip_path)
    try:
        return _insert_import_and_scan_job(storage, key, size_bytes)
    except Exception:
        # No `imports` row exists yet for this key, so the `finally` cleanup
        # in main() can't reach it — delete the just-saved file here instead.
        storage.delete(key)
        raise


def _insert_import_and_scan_job(
    storage: LocalStorage, key: str, size_bytes: int
) -> tuple[int, int]:
    with get_sessionmaker()() as session:
        import_row = Import(
            filename="benchmark.zip",
            storage_key=key,
            size_bytes=size_bytes,
            checksum_sha256=uuid4().hex + uuid4().hex,
            export_format=ExportFormat.json,
            status=ImportStatus.uploaded,
        )
        session.add(import_row)
        session.flush()
        job = Job(
            kind=JobKind.import_scan,
            status=JobStatus.queued,
            total=1,
            payload={"import_id": import_row.id},
        )
        session.add(job)
        session.commit()
        return import_row.id, job.id


def _select_all_conversations(import_id: int) -> None:
    with get_sessionmaker()() as session:
        session.execute(
            update(Conversation).where(Conversation.import_id == import_id).values(is_selected=True)
        )
        session.commit()


def _create_extract_job(import_id: int) -> int:
    with get_sessionmaker()() as session:
        job = Job(
            kind=JobKind.import_extract,
            status=JobStatus.queued,
            total=1,
            payload={"import_id": import_id},
        )
        session.add(job)
        session.commit()
        return job.id


def _timed_scan(job_id: int, import_id: int) -> float:
    start = time.perf_counter()
    run_import_scan(job_id, import_id)
    return time.perf_counter() - start


def _timed_extract(job_id: int, import_id: int) -> float:
    start = time.perf_counter()
    run_import_extract(job_id, import_id)
    return time.perf_counter() - start


def _measure_inbox_p95(email: str, password: str) -> float:
    with TestClient(app) as client:
        client.headers.update(CSRF_HEADERS)
        response = client.post("/api/auth/login", json={"email": email, "password": password})
        if response.status_code != 200:
            raise SystemExit(
                f"login failed ({response.status_code}) — check --email/--password or "
                "BENCHMARK_EMAIL/BENCHMARK_PASSWORD against an account created via "
                "`python -m app.cli create-user`"
            )
        latencies_ms: list[float] = []
        for _ in range(INBOX_SAMPLE_REQUESTS):
            start = time.perf_counter()
            item_response = client.get("/api/items", params={"page_size": 50})
            latencies_ms.append((time.perf_counter() - start) * 1000)
            item_response.raise_for_status()
        client.post("/api/auth/logout")
    latencies_ms.sort()
    index = max(int(len(latencies_ms) * 0.95) - 1, 0)
    return latencies_ms[index]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--message-count", type=int, default=5000)
    parser.add_argument("--email", default=os.environ.get("BENCHMARK_EMAIL"))
    parser.add_argument("--password", default=os.environ.get("BENCHMARK_PASSWORD"))
    args = parser.parse_args(argv)

    if not args.email:
        print(
            "error: --email or BENCHMARK_EMAIL is required — an account already seeded via "
            "`python -m app.cli create-user` (this script never creates or deletes accounts)",
            file=sys.stderr,
        )
        raise SystemExit(1)
    password = args.password or getpass.getpass("Password: ")

    import_id: int | None = None
    try:
        print(f"building perf fixture (~{args.message_count} synthetic messages)...")
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = Path(tmp) / "perf.zip"
            build_perf_export_zip(zip_path, message_count=args.message_count)

            import_id, scan_job_id = _create_throwaway_import(zip_path)
            print("running scan...")
            scan_seconds = _timed_scan(scan_job_id, import_id)

            _select_all_conversations(import_id)
            extract_job_id = _create_extract_job(import_id)
            print("running extract...")
            extract_seconds = _timed_extract(extract_job_id, import_id)

        print("measuring inbox API p95 (50 requests)...")
        inbox_p95_ms = _measure_inbox_p95(args.email, password)

        scan_ok = scan_seconds < SCAN_TARGET_SECONDS
        extract_ok = extract_seconds < EXTRACT_TARGET_SECONDS
        inbox_ok = inbox_p95_ms < INBOX_P95_TARGET_MS

        print()
        print("=== M10 synthetic 5k-fixture benchmark (no real Instagram export used) ===")
        print(
            f"scan:      {scan_seconds:7.2f}s  (target < {SCAN_TARGET_SECONDS}s)   "
            f"{'PASS' if scan_ok else 'FAIL'}"
        )
        print(
            f"extract:   {extract_seconds:7.2f}s  (target < {EXTRACT_TARGET_SECONDS}s)  "
            f"{'PASS' if extract_ok else 'FAIL'}"
        )
        print(
            f"inbox p95: {inbox_p95_ms:7.1f}ms (target < {INBOX_P95_TARGET_MS}ms)  "
            f"{'PASS' if inbox_ok else 'FAIL'}"
        )

        if not (scan_ok and extract_ok and inbox_ok):
            raise SystemExit(1)
    finally:
        if import_id is not None:
            with get_sessionmaker()() as session:
                import_row = session.get(Import, import_id)
                if import_row is not None:
                    storage = LocalStorage(get_config().data_dir)
                    delete_raw_import(session, storage, import_row, cascade=True)
                    session.commit()
            print("cleaned up the throwaway benchmark import.")


if __name__ == "__main__":
    main()
