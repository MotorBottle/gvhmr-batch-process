from pydantic_settings import BaseSettings, SettingsConfigDict

from gvhmr_batch_common.queue import DEFAULT_REDIS_NAMESPACE


class SchedulerSettings(BaseSettings):
    scheduler_id: str = "scheduler-0"
    poll_interval_seconds: int = 2
    postgres_dsn: str = "postgresql://postgres:postgres@postgres:5432/gvhmr_batch_process"
    redis_url: str = "redis://redis:6379/0"
    redis_namespace: str = DEFAULT_REDIS_NAMESPACE
    worker_offline_after_seconds: int = 15

    model_config = SettingsConfigDict(env_prefix="GVHMR_BATCH_SCHEDULER_", case_sensitive=False)
