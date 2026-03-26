from __future__ import annotations

import asyncio
import importlib
import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from datetime import timezone
from pathlib import Path
from threading import Lock

from gvhmr_batch_common.control_plane import ControlPlaneStore, JobExecutionPayload, UploadedArtifact
from gvhmr_batch_common.database import create_engine_from_dsn, create_session_factory
from gvhmr_batch_common.enums import ArtifactKind, FailureCategory, JobStatus, WorkerStatus
from gvhmr_batch_common.queue import RedisDispatchQueue
from gvhmr_batch_common.storage import MinIOStorage
from gvhmr_batch_common.utils import utcnow
from gvhmr_batch_worker.config import WorkerSettings
from gvhmr_runner import (
    GVHMRRunner,
    RunnerCancelled,
    RunnerInfrastructureError,
    RunnerJobSpec,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gvhmr_batch_worker")


class WorkerFatalError(RuntimeError):
    pass


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


def _write_healthcheck_state(
    *,
    settings: WorkerSettings,
    status: str,
    running_job_id: str | None,
    detail: str | None = None,
) -> None:
    settings.healthcheck_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "worker_id": settings.worker_id,
        "node_name": settings.node_name,
        "gpu_slot": settings.gpu_slot,
        "status": status,
        "running_job_id": running_job_id,
        "updated_at": utcnow().isoformat(),
        "detail": detail,
    }
    settings.healthcheck_file.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _ensure_runner_entry_exists(module_name: str) -> None:
    importlib.import_module(module_name)


def _ensure_cuda_available(settings: WorkerSettings) -> str:
    if settings.runner_backend == "mock":
        return "mock-backend"

    import torch

    if not torch.cuda.is_available() or torch.cuda.device_count() < 1:
        raise WorkerFatalError("CUDA runtime is unavailable for this worker container.")
    return str(torch.cuda.get_device_name(0))


def _ensure_scratch_ready(settings: WorkerSettings) -> None:
    settings.scratch_root.mkdir(parents=True, exist_ok=True)
    jobs_root = settings.scratch_root / "jobs"
    jobs_root.mkdir(parents=True, exist_ok=True)

    probe_path = settings.scratch_root / ".write_probe"
    probe_path.write_text("ok", encoding="utf-8")
    probe_path.unlink(missing_ok=True)

    free_bytes = shutil.disk_usage(settings.scratch_root).free
    if free_bytes < settings.scratch_min_free_bytes:
        raise WorkerFatalError(
            "Scratch free space is below the minimum threshold. "
            f"path={settings.scratch_root} free_bytes={free_bytes} "
            f"required_bytes={settings.scratch_min_free_bytes}"
        )


def _glob_exists(root: Path, pattern: str) -> bool:
    return any(root.glob(pattern))


def _ensure_model_assets(settings: WorkerSettings) -> None:
    if settings.runner_backend == "mock":
        return

    root = settings.model_root
    if not root.exists():
        raise WorkerFatalError(f"Model root does not exist: {root}")

    required_files = (
        "gvhmr/gvhmr_siga24_release.ckpt",
        "hmr2/epoch=10-step=25000.ckpt",
        "vitpose/vitpose-h-multi-coco.pth",
        "yolo/yolov8x.pt",
        "dpvo/dpvo.pth",
    )
    missing = [relative for relative in required_files if not (root / relative).exists()]
    if not _glob_exists(root, "body_models/smpl/*.pkl"):
        missing.append("body_models/smpl/*.pkl")
    if not _glob_exists(root, "body_models/smplx/*.npz"):
        missing.append("body_models/smplx/*.npz")

    if missing:
        raise WorkerFatalError(
            "Worker model assets are incomplete. Missing: " + ", ".join(sorted(missing))
        )


def _run_startup_preflight(
    *,
    settings: WorkerSettings,
    store: ControlPlaneStore,
    queue: RedisDispatchQueue,
) -> None:
    if settings.runner_backend == "real" and not settings.gvhmr_root.exists():
        raise WorkerFatalError(f"GVHMR root does not exist: {settings.gvhmr_root}")

    _ensure_runner_entry_exists(settings.runner_entry_module)
    gpu_name = _ensure_cuda_available(settings)
    _ensure_model_assets(settings)
    _ensure_scratch_ready(settings)

    if not store.ping_database():
        raise WorkerFatalError("Postgres preflight ping failed.")
    if not queue.ping():
        raise WorkerFatalError("Redis preflight ping failed.")
    if not store.ping_storage():
        raise WorkerFatalError("MinIO preflight ping failed.")

    logger.info(
        "Worker preflight passed: worker_id=%s gpu_name=%s scratch_root=%s model_root=%s",
        settings.worker_id,
        gpu_name,
        settings.scratch_root,
        settings.model_root,
    )


def _run_idle_preflight(settings: WorkerSettings) -> None:
    _ensure_cuda_available(settings)
    _ensure_scratch_ready(settings)


def _persist_failure_artifacts(
    *,
    store: ControlPlaneStore,
    job_id: str,
    scratch_dir: Path,
    attempt_number: int,
) -> list[UploadedArtifact]:
    artifacts: list[UploadedArtifact] = []
    log_path = scratch_dir / "runner.log"
    if not log_path.exists():
        return artifacts

    artifacts.append(
        store.upload_file_artifact(
            job_id=job_id,
            file_path=log_path,
            artifact_kind=ArtifactKind.LOG,
            subdir="logs",
            content_type="text/plain",
            filename_override=f"runner.attempt-{attempt_number}.log",
        )
    )
    return artifacts


def _classify_failure(
    *,
    settings: WorkerSettings,
    exc: Exception,
) -> tuple[FailureCategory, int | None]:
    if isinstance(exc, RunnerCancelled):
        return FailureCategory.CANCELED, None
    if isinstance(exc, TimeoutError):
        return FailureCategory.TIMEOUT, None
    if isinstance(exc, RunnerInfrastructureError):
        message = str(exc)
        if "CUDA runtime is unavailable." in message or "CUDA initialization failed." in message:
            return FailureCategory.INFRA_TRANSIENT, settings.infra_retry_delay_seconds
        if "Required runtime asset is missing." in message or "Scratch disk is full." in message:
            return FailureCategory.INFRA_PERMANENT, None
        return FailureCategory.INFRA_PERMANENT, None
    if isinstance(exc, FileNotFoundError):
        return FailureCategory.INPUT_INVALID, None
    if isinstance(exc, WorkerFatalError):
        return FailureCategory.INFRA_PERMANENT, None
    return FailureCategory.ALGORITHM_FAILURE, None


def _cleanup_scratch_once(
    *,
    settings: WorkerSettings,
    store: ControlPlaneStore,
    state: WorkerRuntimeState,
) -> int:
    jobs_root = settings.scratch_root / "jobs"
    if not jobs_root.exists():
        return 0

    now = utcnow()
    active_job_id = state.get_running_job_id()
    removed = 0

    for path in jobs_root.iterdir():
        if not path.is_dir():
            continue
        if path.name == active_job_id:
            continue

        mtime = path.stat().st_mtime
        age_seconds = (now - datetime.fromtimestamp(mtime, tz=timezone.utc)).total_seconds()
        job = store.get_job(path.name)

        if job is None:
            ttl_seconds = settings.scratch_orphan_ttl_seconds
        elif job.status in {JobStatus.QUEUED, JobStatus.SCHEDULED, JobStatus.RUNNING}:
            continue
        elif job.status in {JobStatus.SUCCEEDED, JobStatus.CANCELED}:
            ttl_seconds = settings.scratch_success_ttl_seconds
        else:
            ttl_seconds = settings.scratch_failed_ttl_seconds

        if age_seconds < ttl_seconds:
            continue

        shutil.rmtree(path, ignore_errors=False)
        removed += 1

    return removed


def execute_assigned_job(
    *,
    settings: WorkerSettings,
    store: ControlPlaneStore,
    queue: RedisDispatchQueue,
    runner: GVHMRRunner,
    payload: JobExecutionPayload,
    state: WorkerRuntimeState,
) -> None:
    job = payload.job
    upload = payload.upload
    scratch_dir = settings.scratch_root / "jobs" / job.id
    scratch_dir.mkdir(parents=True, exist_ok=True)
    attempt_number = job.retry_count + 1

    input_path = scratch_dir / upload.filename
    uploaded_failure_artifacts: list[UploadedArtifact] = []

    try:
        try:
            store.download_upload(upload=upload, destination=input_path)
        except Exception as exc:
            raise WorkerFatalError(f"Failed to download input upload for job={job.id}.") from exc

        spec = RunnerJobSpec(
            upload_id=upload.id,
            video_sha256=upload.sha256,
            static_camera=job.static_camera,
            use_dpvo=job.use_dpvo,
            video_render=job.video_render,
            video_type=job.video_type,
            f_mm=job.f_mm,
            upstream_version=settings.upstream_gvhmr_ref,
        )

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

        uploaded_artifacts = []
        try:
            uploaded_artifacts = [
                store.upload_file_artifact(
                    job_id=job.id,
                    file_path=artifact.file_path,
                    artifact_kind=ArtifactKind(artifact.kind),
                    subdir=artifact.subdir,
                    content_type=artifact.content_type,
                    filename_override=upload.filename if artifact.kind == ArtifactKind.INPUT_VIDEO.value else None,
                )
                for artifact in result.artifacts
            ]
        except Exception as exc:
            raise WorkerFatalError(f"Failed to upload job artifacts for job={job.id}.") from exc

        try:
            store.complete_job_success(
                job_id=job.id,
                worker_id=settings.worker_id,
                artifacts=uploaded_artifacts,
            )
        except Exception as exc:
            raise WorkerFatalError(f"Failed to persist success state for job={job.id}.") from exc
        logger.info("Completed job=%s successfully.", job.id)
    except RunnerCancelled as exc:
        try:
            uploaded_failure_artifacts = _persist_failure_artifacts(
                store=store,
                job_id=job.id,
                scratch_dir=scratch_dir,
                attempt_number=attempt_number,
            )
        except Exception:
            logger.exception("Failed to upload cancellation diagnostics for job=%s.", job.id)

        store.complete_job_failure(
            job_id=job.id,
            worker_id=settings.worker_id,
            error_message=str(exc),
            failure_category=FailureCategory.CANCELED,
            canceled=True,
            artifacts=uploaded_failure_artifacts,
        )
        logger.info("Canceled job=%s during execution.", job.id)
    except Exception as exc:
        failure_category, retry_delay_seconds = _classify_failure(settings=settings, exc=exc)
        try:
            uploaded_failure_artifacts = _persist_failure_artifacts(
                store=store,
                job_id=job.id,
                scratch_dir=scratch_dir,
                attempt_number=attempt_number,
            )
        except Exception as upload_exc:
            logger.exception("Failed to upload failure diagnostics for job=%s.", job.id)
            if isinstance(exc, WorkerFatalError):
                raise WorkerFatalError(str(exc)) from upload_exc

        try:
            updated_job = store.complete_job_failure(
                job_id=job.id,
                worker_id=settings.worker_id,
                error_message=str(exc),
                failure_category=failure_category,
                retry_delay_seconds=retry_delay_seconds,
                canceled=False,
                artifacts=uploaded_failure_artifacts,
            )
        except Exception as persist_exc:
            raise WorkerFatalError(f"Failed to persist failure state for job={job.id}.") from persist_exc

        logger.exception("Job=%s failed.", job.id)
        if updated_job.status is JobStatus.QUEUED:
            queue.signal_scheduler("job_retry")
            logger.warning(
                "Scheduled automatic retry for job=%s retry_count=%s/%s next_retry_at=%s category=%s",
                updated_job.id,
                updated_job.retry_count,
                updated_job.max_retries,
                updated_job.next_retry_at.isoformat() if updated_job.next_retry_at else None,
                updated_job.failure_category.value if updated_job.failure_category else None,
            )
        if isinstance(exc, (WorkerFatalError, RunnerInfrastructureError)):
            raise WorkerFatalError(str(exc)) from exc
    finally:
        state.set_running_job_id(None)


async def heartbeat_loop(
    *,
    settings: WorkerSettings,
    store: ControlPlaneStore,
    state: WorkerRuntimeState,
) -> None:
    while True:
        running_job_id = state.get_running_job_id()
        status = WorkerStatus.BUSY if running_job_id else WorkerStatus.IDLE
        try:
            store.upsert_worker_heartbeat(
                worker_id=settings.worker_id,
                node_name=settings.node_name,
                gpu_slot=settings.gpu_slot,
                status=status,
                running_job_id=running_job_id,
            )
            _write_healthcheck_state(
                settings=settings,
                status=status.value,
                running_job_id=running_job_id,
            )
        except Exception as exc:
            logger.exception("Failed to write worker heartbeat.")
            raise WorkerFatalError("Worker heartbeat failed.") from exc
        await asyncio.sleep(settings.heartbeat_interval_seconds)


async def scratch_cleanup_loop(
    *,
    settings: WorkerSettings,
    store: ControlPlaneStore,
    state: WorkerRuntimeState,
) -> None:
    while True:
        try:
            removed = await asyncio.to_thread(
                _cleanup_scratch_once,
                settings=settings,
                store=store,
                state=state,
            )
            if removed:
                logger.info("Removed %s stale scratch job directorie(s).", removed)
        except Exception:
            logger.exception("Scratch cleanup failed.")
        await asyncio.sleep(settings.scratch_cleanup_interval_seconds)


async def work_loop(
    *,
    settings: WorkerSettings,
    store: ControlPlaneStore,
    queue: RedisDispatchQueue,
    state: WorkerRuntimeState,
) -> None:
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

        if not idle_announced:
            await asyncio.to_thread(_run_idle_preflight, settings)
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
        idle_announced = False

        try:
            store.mark_job_running(job_id=payload.job.id, worker_id=settings.worker_id)
        except (KeyError, ValueError):
            logger.warning(
                "Skipped stale assignment while claiming job=%s for worker=%s.",
                payload.job.id,
                settings.worker_id,
            )
            state.set_running_job_id(None)
            continue

        logger.info("Worker claimed job=%s.", payload.job.id)
        await asyncio.to_thread(
            execute_assigned_job,
            settings=settings,
            store=store,
            queue=queue,
            runner=runner,
            payload=payload,
            state=state,
        )


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
    queue = RedisDispatchQueue(settings.redis_url, namespace=settings.redis_namespace)
    state = WorkerRuntimeState()

    _run_startup_preflight(settings=settings, store=store, queue=queue)
    store.ensure_worker_identity_available(
        worker_id=settings.worker_id,
        node_name=settings.node_name,
        gpu_slot=settings.gpu_slot,
        stale_after_seconds=settings.identity_stale_after_seconds,
    )
    database_now = store.get_database_utcnow()
    worker_now = utcnow()
    clock_skew_seconds = abs((worker_now - database_now).total_seconds())
    if clock_skew_seconds >= settings.clock_skew_fail_seconds:
        raise RuntimeError(
            "Worker clock skew is too large. "
            f"worker_now={worker_now.isoformat()} db_now={database_now.isoformat()} "
            f"skew_seconds={clock_skew_seconds:.3f} "
            f"threshold={settings.clock_skew_fail_seconds}"
        )
    if clock_skew_seconds >= settings.clock_skew_warn_seconds:
        logger.warning(
            "Worker clock skew is above warning threshold: worker_now=%s db_now=%s skew_seconds=%.3f threshold=%s",
            worker_now.isoformat(),
            database_now.isoformat(),
            clock_skew_seconds,
            settings.clock_skew_warn_seconds,
        )

    store.upsert_worker_heartbeat(
        worker_id=settings.worker_id,
        node_name=settings.node_name,
        gpu_slot=settings.gpu_slot,
        status=WorkerStatus.IDLE,
        running_job_id=None,
    )
    _write_healthcheck_state(
        settings=settings,
        status=WorkerStatus.IDLE.value,
        running_job_id=None,
        detail="startup-complete",
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
        scratch_cleanup_loop(settings=settings, store=store, state=state),
        work_loop(settings=settings, store=store, queue=queue, state=state),
    )


def main() -> None:
    settings = WorkerSettings()
    try:
        asyncio.run(run_worker(settings))
    except WorkerFatalError as exc:
        logger.critical("Worker exiting due to fatal runtime error: %s", exc)
        try:
            _write_healthcheck_state(
                settings=settings,
                status="fatal",
                running_job_id=None,
                detail=str(exc),
            )
        except Exception:
            logger.exception("Failed to write fatal healthcheck state.")
        raise SystemExit(1) from exc
    except Exception as exc:
        logger.critical("Worker exiting due to unhandled error: %s", exc, exc_info=True)
        try:
            _write_healthcheck_state(
                settings=settings,
                status="fatal",
                running_job_id=None,
                detail=str(exc),
            )
        except Exception:
            logger.exception("Failed to write fatal healthcheck state.")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
