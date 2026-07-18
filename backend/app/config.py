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

    # Metadata enrichment (off by default; consent-gated in Settings — see
    # services/enrichment/). Ceilings/defaults only, not the on/off switch.
    enrichment_requests_per_minute: int = 20
    enrichment_timeout_seconds: int = 10
    # Consecutive "blocked" (401/403/429/999) responses within one batch run
    # that trip the circuit breaker; remaining items are recorded `disabled`
    # with zero further HTTP calls.
    enrichment_circuit_breaker_threshold: int = 5
    enrichment_user_agent: str = "InspirationOS/1.0 (personal project; anonymous metadata fetch)"


@lru_cache
def get_config() -> AppConfig:
    return AppConfig()
