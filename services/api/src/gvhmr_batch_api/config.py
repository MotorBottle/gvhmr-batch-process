from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from gvhmr_batch_common.queue import DEFAULT_REDIS_NAMESPACE


class APISettings(BaseSettings):
    app_name: str = "GVHMR Batch Process"
    app_env: str = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    control_plane_backend: str = "postgres+minio"
    storage_root: Path = Path(".data")
    max_upload_size_mb: int = 2048
    postgres_dsn: str = "postgresql://postgres:postgres@postgres:5432/gvhmr_batch_process"
    redis_url: str = "redis://redis:6379/0"
    redis_namespace: str = DEFAULT_REDIS_NAMESPACE
    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "gvhmr-batch-process"
    minio_secure: bool = False
    worker_offline_after_seconds: int = 15

    model_config = SettingsConfigDict(env_prefix="GVHMR_BATCH_API_", case_sensitive=False)
