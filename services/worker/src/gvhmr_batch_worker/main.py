from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock

from gvhmr_batch_common.control_plane import ControlPlaneStore, JobExecutionPayload
from gvhmr_batch_common.database import create_engine_from_dsn, create_session_factory
from gvhmr_batch_common.enums import ArtifactKind, WorkerStatus
from gvhmr_batch_common.queue import RedisDispatchQueue
from gvhmr_batch_common.storage import MinIOStorage
from gvhmr_runner import GVHMRRunner, RunnerCancelled, RunnerJobSpec
from gvhmr_batch_worker.config import WorkerSettings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gvhmr_batch_worker")


@dataclass(slots=True)
class WorkerRuntimeState:
    _lock: Lock = field(default_factory=Lock)
    running_job_id: str | None = None

    def get_running_job_id(self) -> str | None:
        with self._lock:
            return self.running_job_id

    def set_running_job_id(self, job_id: str | None) -> None:
        with self._lock:
            self.running_job_id = job_id


def execute_assigned_job(
    *,
    settings: WorkerSettings,
    store: ControlPlaneStore,
    runner: GVHMRRunner,
    payload: JobExecutionPayload,
    state: WorkerRuntimeState,
) -> None:
    job = payload.job
    upload = payload.upload
    scratch_dir = settings.scratch_root / "jobs" / job.id
    scratch_dir.mkdir(parents=True, exist_ok=True)

    input_path = scratch_dir / upload.filename
    store.download_upload(upload=upload, destination=input_path)

    spec = RunnerJobSpec(
        upload_id=upload.id,
        video_sha256=upload.sha256,
        static_camera=job.static_camera,
        video_render=job.video_render,
        video_type=job.video_type,
        f_mm=job.f_mm,
        upstream_version=settings.upstream_gvhmr_ref,
    )

    try:
        if settings.runner_backend == "mock":
            result = runner.run_mock(
                spec,
                workdir=scratch_dir,
                duration_seconds=settings.mock_duration_seconds,
                should_fail=settings.mock_fail,
                is_cancel_requested=lambda: store.is_cancel_requested(job.id),
            )
        else:
            result = runner.run(
                spec,
                input_video_path=input_path,
                workdir=scratch_dir,
                timeout_seconds=settings.runner_timeout_seconds,
                is_cancel_requested=lambda: store.is_cancel_requested(job.id),
            )

        uploaded_artifacts = [
            store.upload_file_artifact(
                job_id=job.id,
                file_path=artifact.file_path,
                artifact_kind=ArtifactKind(artifact.kind),
                subdir=artifact.subdir,
                content_type=artifact.content_type,
            )
            for artifact in result.artifacts
        ]
        store.complete_job_success(
            job_id=job.id,
            worker_id=settings.worker_id,
            artifacts=uploaded_artifacts,
        )
        logger.info("Completed job=%s successfully.", job.id)
    except RunnerCancelled as exc:
        store.complete_job_failure(
            job_id=job.id,
            worker_id=settings.worker_id,
            error_message=str(exc),
            canceled=True,
        )
        logger.info("Canceled job=%s during execution.", job.id)
    except Exception as exc:
        store.complete_job_failure(
            job_id=job.id,
            worker_id=settings.worker_id,
            error_message=str(exc),
            canceled=False,
        )
        logger.exception("Job=%s failed.", job.id)
    finally:
        state.set_running_job_id(None)


async def heartbeat_loop(
    *,
    settings: WorkerSettings,
    store: ControlPlaneStore,
    state: WorkerRuntimeState,
) -> None:
    while True:
        try:
            running_job_id = state.get_running_job_id()
            status = WorkerStatus.BUSY if running_job_id else WorkerStatus.IDLE
            store.upsert_worker_heartbeat(
                worker_id=settings.worker_id,
                node_name=settings.node_name,
                gpu_slot=settings.gpu_slot,
                status=status,
                running_job_id=running_job_id,
            )
        except Exception:
            logger.exception("Failed to write worker heartbeat.")
        await asyncio.sleep(settings.heartbeat_interval_seconds)


async def work_loop(
    *,
    settings: WorkerSettings,
    store: ControlPlaneStore,
    state: WorkerRuntimeState,
) -> None:
    queue = RedisDispatchQueue(settings.redis_url, namespace=settings.redis_namespace)
    runner = GVHMRRunner(
        settings.upstream_gvhmr_ref,
        gvhmr_root=settings.gvhmr_root,
        runner_entry_module=settings.runner_entry_module,
    )
    idle_announced = False
    while True:
        if state.get_running_job_id():
            idle_announced = False
            await asyncio.sleep(1)
            continue

        try:
            if not idle_announced:
                await asyncio.to_thread(queue.announce_worker_idle, settings.worker_id)
                idle_announced = True

            job_id = await asyncio.to_thread(
                queue.pop_worker_job,
                worker_id=settings.worker_id,
                timeout_seconds=settings.job_poll_interval_seconds,
            )
            if job_id is None:
                continue

            payload = store.get_scheduled_job_by_id_for_worker(
                worker_id=settings.worker_id,
                job_id=job_id,
            )
            if payload is None:
                logger.warning(
                    "Received redis dispatch for job=%s but no scheduled assignment remained for worker=%s.",
                    job_id,
                    settings.worker_id,
                )
                idle_announced = False
                continue

            await asyncio.to_thread(queue.mark_worker_busy, settings.worker_id)
            state.set_running_job_id(payload.job.id)
            store.mark_job_running(job_id=payload.job.id, worker_id=settings.worker_id)
            idle_announced = False
            logger.info("Worker claimed job=%s.", payload.job.id)
            await asyncio.to_thread(
                execute_assigned_job,
                settings=settings,
                store=store,
                runner=runner,
                payload=payload,
                state=state,
            )
        except Exception:
            state.set_running_job_id(None)
            logger.exception("Worker loop failed.")
            await asyncio.sleep(1)


async def run_worker(settings: WorkerSettings) -> None:
    engine = create_engine_from_dsn(settings.postgres_dsn)
    session_factory = create_session_factory(engine)
    storage = MinIOStorage(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        bucket=settings.minio_bucket,
        secure=settings.minio_secure,
    )
    store = ControlPlaneStore(session_factory, storage)
    state = WorkerRuntimeState()
    store.upsert_worker_heartbeat(
        worker_id=settings.worker_id,
        node_name=settings.node_name,
        gpu_slot=settings.gpu_slot,
        status=WorkerStatus.IDLE,
        running_job_id=None,
    )

    logger.info(
        "Worker started: worker_id=%s node=%s gpu_slot=%s backend=%s gvhmr_root=%s model_root=%s scratch_root=%s redis_namespace=%s",
        settings.worker_id,
        settings.node_name,
        settings.gpu_slot,
        settings.runner_backend,
        settings.gvhmr_root,
        settings.model_root,
        settings.scratch_root,
        settings.redis_namespace,
    )
    await asyncio.gather(
        heartbeat_loop(settings=settings, store=store, state=state),
        work_loop(settings=settings, store=store, state=state),
    )


def main() -> None:
    asyncio.run(run_worker(WorkerSettings()))


if __name__ == "__main__":
    main()
