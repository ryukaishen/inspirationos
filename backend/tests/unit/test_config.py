from pathlib import Path

import pytest

from app.config import AppConfig


def test_defaults_load_without_env_file_or_services() -> None:
    cfg = AppConfig(_env_file=None)
    assert cfg.env == "development"
    assert cfg.log_level == "INFO"
    assert cfg.database_url.startswith("postgresql+psycopg://")
    assert cfg.redis_url.startswith("redis://")
    assert cfg.data_dir == Path("./var/data")
    assert cfg.max_upload_size_mb == 2048


def test_environment_variables_override_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@example:5432/other")
    monkeypatch.setenv("REDIS_URL", "redis://example:6379/3")
    monkeypatch.setenv("MAX_UPLOAD_SIZE_MB", "16")
    monkeypatch.setenv("DATA_DIR", "/srv/data")
    cfg = AppConfig(_env_file=None)
    assert cfg.env == "test"
    assert cfg.database_url == "postgresql+psycopg://u:p@example:5432/other"
    assert cfg.redis_url == "redis://example:6379/3"
    assert cfg.max_upload_size_mb == 16
    assert cfg.data_dir == Path("/srv/data")
