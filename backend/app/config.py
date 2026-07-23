"""Application configuration loaded from environment variables (see .env.example)."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: str = "development"
    secret_key: str = "dev-only-secret-change-me"
    log_level: str = "INFO"

    # Auth & sessions (M9). Sessions live in Redis, keyed by an HMAC-signed
    # opaque token (see services/auth/sessions.py) — secret_key signs the
    # cookie, not the Redis-side capability, so revocation stays immediate.
    session_ttl_seconds: int = 60 * 60 * 24 * 14
    login_rate_limit_attempts: int = 5
    login_rate_limit_window_seconds: int = 300
    # Real browsers (and Playwright/Chromium) treat http://localhost as a
    # secure context and happily store/resend a Secure cookie there, so dev
    # and prod both want this True. httpx's TestClient talks plain
    # http://testserver through Python's stdlib http.cookiejar, which has no
    # such exception and silently drops Secure cookies — pytest's conftest
    # sets SESSION_COOKIE_SECURE=false for that process only.
    session_cookie_secure: bool = True

    database_url: str = "postgresql+psycopg://inspiration:inspiration@localhost:5432/inspiration"
    redis_url: str = "redis://localhost:6379/0"

    data_dir: Path = Path("./var/data")
    max_upload_size_mb: int = 2048

    # ZIP-bomb caps for uploaded archives (see services/ingest/zip_safety.py).
    max_zip_entries: int = 100_000
    max_zip_uncompressed_mb: int = 10_240
    max_zip_compression_ratio: int = 100

    # Same-sender messages within ± this window around a shared link are
    # concatenated into the item's adjacent_text (see services/ingest/instagram/).
    adjacent_text_window_seconds: int = 120

    # A worker that crashes hard (OOM-kill, host reboot, container crash —
    # not a clean exception) leaves its in-flight `jobs` row stuck at
    # `running` forever; nothing else notices, since RQ's own dead-worker
    # bookkeeping never writes back to this table. Any read of a `running`
    # job past this age is reconciled to `failed` in place (see
    # services/jobs.py::reconcile_stale_job) — generous enough not to
    # false-positive on legitimately slow batches (large enrichment runs,
    # a first-time local-embedding-model download) while still bounding
    # "stuck forever" to a concrete, visible window.
    job_stale_after_seconds: int = 1800

    # Metadata enrichment (off by default; consent-gated in Settings — see
    # services/enrichment/). Ceilings/defaults only, not the on/off switch.
    enrichment_requests_per_minute: int = 20
    enrichment_timeout_seconds: int = 10
    # Consecutive "blocked" (401/403/429/999) responses within one batch run
    # that trip the circuit breaker; remaining items are recorded `disabled`
    # with zero further HTTP calls.
    enrichment_circuit_breaker_threshold: int = 5
    enrichment_user_agent: str = "InspirationOS/1.0 (personal project; anonymous metadata fetch)"

    # AI providers (M6). Env value is the fallback; the effective provider is
    # settings.ai_provider in the DB (seeded `mock`), switched via the UI —
    # see services/ai/factory.py. API keys are env-only, never stored in the DB.
    ai_provider: str = "mock"
    anthropic_api_key: str | None = None
    anthropic_generation_model: str = "claude-sonnet-5"
    anthropic_fast_model: str = "claude-haiku-4-5"
    openai_api_key: str | None = None
    openai_generation_model: str = "gpt-5.2"
    openai_fast_model: str = "gpt-5-mini"
    # Monthly USD ceiling (env fallback; settings.monthly_budget_usd overrides)
    # and a per-job cumulative token cap — both checked before every LLM call.
    ai_monthly_budget_usd: float = 10.0
    ai_job_token_budget: int = 250_000
    ai_max_output_tokens: int = 4096

    # Embeddings & analysis (M6). `local` is fastembed (no key, offline after a
    # one-time model download); `mock` is the deterministic test/CI provider;
    # `openai` requires OPENAI_API_KEY. The vector column is fixed at 384 dims,
    # so the OpenAI adapter requests dimensions=384.
    embedding_provider: str = "local"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    openai_embedding_model: str = "text-embedding-3-small"
    # Agglomerative clustering cosine-distance cut; pairs closer than
    # (1 - near_duplicate_similarity_threshold) become near_text duplicate groups.
    cluster_distance_threshold: float = 0.4
    near_duplicate_similarity_threshold: float = 0.95
    # Per-item text truncation and per-cluster item cap for LLM topic/label
    # context — cost control, never a correctness knob.
    topics_max_chars_per_item: int = 500
    topics_max_items_per_cluster: int = 30

    # Project generation (M7): context caps mirror the topics caps; count is
    # how many ideas one generation batch asks for (request can override up
    # to the max).
    projects_max_items: int = 60
    projects_max_chars_per_item: int = 400
    projects_default_count: int = 3
    projects_max_count: int = 10


@lru_cache
def get_config() -> AppConfig:
    return AppConfig()
