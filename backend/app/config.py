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


@lru_cache
def get_config() -> AppConfig:
    return AppConfig()
