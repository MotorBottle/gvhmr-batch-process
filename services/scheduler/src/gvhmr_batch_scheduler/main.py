from __future__ import annotations

import asyncio
import logging

from gvhmr_batch_common.control_plane import ControlPlaneStore
from gvhmr_batch_common.database import create_engine_from_dsn, create_session_factory
from gvhmr_batch_scheduler.config import SchedulerSettings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gvhmr_batch_scheduler")


async def run_scheduler(settings: SchedulerSettings) -> None:
    engine = create_engine_from_dsn(settings.postgres_dsn)
    session_factory = create_session_factory(engine)
    store = ControlPlaneStore(session_factory)

    logger.info(
        "Scheduler started: scheduler_id=%s poll_interval_seconds=%s redis_url=%s",
        settings.scheduler_id,
        settings.poll_interval_seconds,
        settings.redis_url,
    )
    while True:
        try:
            failed_job_ids = store.mark_stale_workers_offline(
                offline_after_seconds=settings.worker_offline_after_seconds
            )
            if failed_job_ids:
                logger.warning("Marked jobs failed due to stale workers: %s", ", ".join(failed_job_ids))

            scheduled = store.schedule_next_job(
                offline_after_seconds=settings.worker_offline_after_seconds
            )
            if scheduled is not None:
                job, worker = scheduled
                logger.info(
                    "Scheduled job=%s to worker=%s gpu_slot=%s",
                    job.id,
                    worker.id,
                    worker.gpu_slot,
                )
        except Exception:
            logger.exception("Scheduler loop failed.")
        await asyncio.sleep(settings.poll_interval_seconds)


def main() -> None:
    asyncio.run(run_scheduler(SchedulerSettings()))


if __name__ == "__main__":
    main()
