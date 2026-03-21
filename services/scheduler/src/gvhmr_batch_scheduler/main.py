from __future__ import annotations

import asyncio
import logging

from gvhmr_batch_common.control_plane import ControlPlaneStore
from gvhmr_batch_common.database import create_engine_from_dsn, create_session_factory
from gvhmr_batch_common.enums import WorkerStatus
from gvhmr_batch_common.queue import RedisDispatchQueue
from gvhmr_batch_scheduler.config import SchedulerSettings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gvhmr_batch_scheduler")


def reconcile_dispatch_state(*, settings: SchedulerSettings, store: ControlPlaneStore, queue: RedisDispatchQueue) -> None:
    failed_job_ids = store.mark_stale_workers_offline(
        offline_after_seconds=settings.worker_offline_after_seconds
    )
    if failed_job_ids:
        logger.warning("Marked jobs failed due to stale workers: %s", ", ".join(failed_job_ids))

    queue.clear_dispatch_state()

    queued_jobs = store.list_queued_jobs()
    if queued_jobs:
        queue.enqueue_jobs([(job.id, job.priority) for job in queued_jobs])

    scheduled_jobs = store.list_scheduled_jobs()
    for job in scheduled_jobs:
        if job.assigned_worker_id:
            queue.push_worker_job(worker_id=job.assigned_worker_id, job_id=job.id)

    workers = store.list_workers(offline_after_seconds=settings.worker_offline_after_seconds)
    for worker in workers:
        if worker.status is WorkerStatus.IDLE and worker.running_job_id is None:
            queue.requeue_idle_worker(worker.id)

    if queued_jobs or scheduled_jobs:
        queue.signal_scheduler("reconciled")


def dispatch_available_work(*, settings: SchedulerSettings, store: ControlPlaneStore, queue: RedisDispatchQueue) -> int:
    dispatched = 0
    while True:
        worker_id = queue.pop_idle_worker()
        if worker_id is None:
            return dispatched

        next_job = queue.pop_next_job()
        if next_job is None:
            queue.requeue_idle_worker(worker_id)
            return dispatched

        job_id, priority = next_job
        decision = store.assign_job_to_worker(
            job_id=job_id,
            worker_id=worker_id,
            offline_after_seconds=settings.worker_offline_after_seconds,
        )
        if decision.scheduled:
            try:
                queue.push_worker_job(worker_id=worker_id, job_id=job_id)
                dispatched += 1
            except Exception:
                store.revert_scheduled_job(job_id=job_id, worker_id=worker_id)
                queue.requeue_job_front(job_id=job_id, priority=priority)
                queue.requeue_idle_worker(worker_id)
                raise
            continue

        if decision.requeue_job:
            queue.requeue_job_front(job_id=job_id, priority=priority)
        if decision.requeue_worker:
            queue.requeue_idle_worker(worker_id)

        logger.info(
            "Skipped dispatch job=%s worker=%s reason=%s requeue_job=%s requeue_worker=%s",
            job_id,
            worker_id,
            decision.reason,
            decision.requeue_job,
            decision.requeue_worker,
        )


async def run_scheduler(settings: SchedulerSettings) -> None:
    engine = create_engine_from_dsn(settings.postgres_dsn)
    session_factory = create_session_factory(engine)
    store = ControlPlaneStore(session_factory)
    queue = RedisDispatchQueue(settings.redis_url, namespace=settings.redis_namespace)

    logger.info(
        "Scheduler started: scheduler_id=%s poll_interval_seconds=%s redis_url=%s redis_namespace=%s",
        settings.scheduler_id,
        settings.poll_interval_seconds,
        settings.redis_url,
        settings.redis_namespace,
    )
    await asyncio.to_thread(reconcile_dispatch_state, settings=settings, store=store, queue=queue)
    while True:
        try:
            signal = await asyncio.to_thread(
                queue.wait_for_scheduler_signal,
                settings.poll_interval_seconds,
            )
            failed_job_ids = store.mark_stale_workers_offline(
                offline_after_seconds=settings.worker_offline_after_seconds
            )
            if failed_job_ids:
                logger.warning("Marked jobs failed due to stale workers: %s", ", ".join(failed_job_ids))

            dispatched = await asyncio.to_thread(
                dispatch_available_work,
                settings=settings,
                store=store,
                queue=queue,
            )
            if dispatched:
                logger.info(
                    "Dispatched %s job(s)%s",
                    dispatched,
                    f' after signal="{signal}"' if signal else "",
                )
        except Exception:
            logger.exception("Scheduler loop failed.")
            await asyncio.sleep(settings.poll_interval_seconds)


def main() -> None:
    asyncio.run(run_scheduler(SchedulerSettings()))


if __name__ == "__main__":
    main()
