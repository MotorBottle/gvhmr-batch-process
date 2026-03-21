from __future__ import annotations

from collections.abc import Iterable

from redis import Redis

from gvhmr_batch_common.enums import JobPriority


DEFAULT_REDIS_NAMESPACE = "gvhmr-batch-process"


class RedisDispatchQueue:
    def __init__(self, redis_url: str, *, namespace: str = DEFAULT_REDIS_NAMESPACE) -> None:
        self._client = Redis.from_url(redis_url, decode_responses=True)
        self._namespace = namespace

    def ping(self) -> bool:
        return bool(self._client.ping())

    def enqueue_job(self, *, job_id: str, priority: JobPriority) -> None:
        self.enqueue_jobs([(job_id, priority)])

    def enqueue_jobs(self, jobs: Iterable[tuple[str, JobPriority]]) -> None:
        items = list(jobs)
        if not items:
            return

        pipe = self._client.pipeline()
        for job_id, priority in items:
            pipe.rpush(self._priority_queue_key(priority), job_id)
        pipe.rpush(self._scheduler_signal_key(), "jobs_ready")
        pipe.execute()

    def announce_worker_idle(self, worker_id: str) -> None:
        pipe = self._client.pipeline()
        pipe.sadd(self._idle_workers_key(), worker_id)
        pipe.rpush(self._scheduler_signal_key(), f"worker_idle:{worker_id}")
        pipe.execute()

    def mark_worker_busy(self, worker_id: str) -> None:
        self._client.srem(self._idle_workers_key(), worker_id)

    def wait_for_scheduler_signal(self, timeout_seconds: int) -> str | None:
        result = self._client.brpop(self._scheduler_signal_key(), timeout=max(timeout_seconds, 1))
        if result is None:
            return None
        _, payload = result
        return payload

    def pop_idle_worker(self) -> str | None:
        worker_id = self._client.spop(self._idle_workers_key())
        return str(worker_id) if worker_id is not None else None

    def requeue_idle_worker(self, worker_id: str) -> None:
        self._client.sadd(self._idle_workers_key(), worker_id)

    def pop_next_job(self) -> tuple[str, JobPriority] | None:
        for priority in (JobPriority.HIGH, JobPriority.NORMAL, JobPriority.LOW):
            job_id = self._client.lpop(self._priority_queue_key(priority))
            if job_id is not None:
                return str(job_id), priority
        return None

    def requeue_job_front(self, *, job_id: str, priority: JobPriority) -> None:
        self._client.lpush(self._priority_queue_key(priority), job_id)

    def push_worker_job(self, *, worker_id: str, job_id: str) -> None:
        self._client.rpush(self._worker_queue_key(worker_id), job_id)

    def pop_worker_job(self, *, worker_id: str, timeout_seconds: int) -> str | None:
        result = self._client.blpop(self._worker_queue_key(worker_id), timeout=max(timeout_seconds, 1))
        if result is None:
            return None
        _, job_id = result
        return str(job_id)

    def clear_dispatch_state(self) -> None:
        keys = [
            self._scheduler_signal_key(),
            self._idle_workers_key(),
            self._priority_queue_key(JobPriority.HIGH),
            self._priority_queue_key(JobPriority.NORMAL),
            self._priority_queue_key(JobPriority.LOW),
        ]
        keys.extend(self._client.scan_iter(match=f"{self._namespace}:worker:*:jobs"))
        if keys:
            self._client.delete(*keys)

    def signal_scheduler(self, reason: str = "dispatch") -> None:
        self._client.rpush(self._scheduler_signal_key(), reason)

    def _priority_queue_key(self, priority: JobPriority) -> str:
        return f"{self._namespace}:jobs:{priority.value}"

    def _worker_queue_key(self, worker_id: str) -> str:
        return f"{self._namespace}:worker:{worker_id}:jobs"

    def _idle_workers_key(self) -> str:
        return f"{self._namespace}:workers:idle"

    def _scheduler_signal_key(self) -> str:
        return f"{self._namespace}:scheduler:signals"
