from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from gvhmr_batch_common.queue import DEFAULT_REDIS_NAMESPACE

PINNED_GVHMR_REF = "088caff492aa38c2d82cea363b78a3c65a83118f"


class WorkerSettings(BaseSettings):
    worker_id: str = "worker-gpu0"
    node_name: str = "local-node"
    gpu_slot: int = 0
    runner_backend: str = "real"
    runner_entry_module: str = "gvhmr_runner.bridge.demo_with_skeleton"
    runner_timeout_seconds: int = 3600
    infra_retry_delay_seconds: int = 30
    heartbeat_interval_seconds: int = 5
    job_poll_interval_seconds: int = 2
    postgres_dsn: str = "postgresql://postgres:postgres@postgres:5432/gvhmr_batch_process"
    redis_url: str = "redis://redis:6379/0"
    redis_namespace: str = DEFAULT_REDIS_NAMESPACE
    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "gvhmr-batch-process"
    minio_secure: bool = False
    model_root: Path = Path("/app/gvhmr/inputs/checkpoints")
    gvhmr_root: Path = Path("/app/gvhmr")
    scratch_root: Path = Path("/var/lib/gvhmr-batch-process")
    healthcheck_file: Path = Path("/tmp/gvhmr-batch-worker-health.json")
    healthcheck_max_age_seconds: int = 30
    identity_stale_after_seconds: int = 30
    clock_skew_warn_seconds: int = 5
    clock_skew_fail_seconds: int = 30
    scratch_min_free_bytes: int = 4 * 1024 * 1024 * 1024
    scratch_cleanup_interval_seconds: int = 300
    scratch_success_ttl_seconds: int = 3600
    scratch_failed_ttl_seconds: int = 7 * 24 * 3600
    scratch_orphan_ttl_seconds: int = 24 * 3600
    upstream_gvhmr_ref: str = PINNED_GVHMR_REF
    mock_duration_seconds: int = 5
    mock_fail: bool = False

    model_config = SettingsConfigDict(env_prefix="GVHMR_BATCH_WORKER_", case_sensitive=False)
