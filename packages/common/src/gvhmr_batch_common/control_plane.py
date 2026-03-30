from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from pathlib import Path
from typing import Iterable

from sqlalchemy import case, or_, select, text
from sqlalchemy.orm import Session, sessionmaker

from gvhmr_batch_common.enums import ArtifactKind, BatchStatus, FailureCategory, JobPriority, JobStatus, WorkerStatus
from gvhmr_batch_common.models import ArtifactORM, BatchORM, JobAssignmentORM, JobORM, UploadORM, WorkerHeartbeatORM
from gvhmr_batch_common.schemas import (
    ArtifactRecord,
    BatchCounts,
    BatchCreateRequest,
    BatchRecord,
    JobAssignment,
    JobCreateRequest,
    JobRecord,
    UploadRecord,
    WorkerHeartbeatRecord,
)
from gvhmr_batch_common.storage import MinIOStorage
from gvhmr_batch_common.utils import new_id, safe_filename, utcnow


@dataclass(slots=True)
class JobExecutionPayload:
    job: JobRecord
    upload: UploadRecord


@dataclass(slots=True)
class UploadedArtifact:
    kind: ArtifactKind
    filename: str
    storage_key: str


@dataclass(slots=True)
class DispatchDecision:
    scheduled: bool
    requeue_job: bool
    requeue_worker: bool
    reason: str
    job: JobRecord | None = None
    worker: WorkerHeartbeatRecord | None = None


@dataclass(slots=True)
class StaleWorkerRecoveryResult:
    failed_job_ids: list[str]
    retried_jobs: list[tuple[str, JobPriority]]


def _priority_order() -> case:
    return case(
        (JobORM.priority == JobPriority.HIGH.value, 3),
        (JobORM.priority == JobPriority.NORMAL.value, 2),
        (JobORM.priority == JobPriority.LOW.value, 1),
        else_=0,
    )


def _to_upload_record(model: UploadORM) -> UploadRecord:
    return UploadRecord(
        id=model.id,
        filename=model.filename,
        content_type=model.content_type,
        size_bytes=model.size_bytes,
        sha256=model.sha256,
        storage_key=model.storage_key,
        created_at=model.created_at,
    )


def _to_job_record(model: JobORM) -> JobRecord:
    upload = model.upload
    return JobRecord(
        id=model.id,
        batch_id=model.batch_id,
        upload_id=model.upload_id,
        upload_filename=upload.filename if upload is not None else None,
        status=JobStatus(model.status),
        priority=JobPriority(model.priority),
        static_camera=model.static_camera,
        use_dpvo=model.use_dpvo,
        video_render=model.video_render,
        video_type=model.video_type,
        f_mm=model.f_mm,
        assigned_worker_id=model.assigned_worker_id,
        assigned_gpu_slot=model.assigned_gpu_slot,
        artifact_count=model.artifact_count,
        retry_count=model.retry_count,
        max_retries=model.max_retries,
        failure_category=FailureCategory(model.failure_category) if model.failure_category else None,
        next_retry_at=model.next_retry_at,
        error_message=model.error_message,
        cancel_requested_at=model.cancel_requested_at,
        started_at=model.started_at,
        finished_at=model.finished_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _to_artifact_record(model: ArtifactORM) -> ArtifactRecord:
    return ArtifactRecord(
        id=model.id,
        job_id=model.job_id,
        kind=ArtifactKind(model.kind),
        filename=model.filename,
        storage_key=model.storage_key,
        created_at=model.created_at,
    )


def _to_worker_record(model: WorkerHeartbeatORM, *, stale_after_seconds: int | None = None) -> WorkerHeartbeatRecord:
    status = WorkerStatus(model.status)
    if stale_after_seconds is not None and model.last_heartbeat_at < utcnow() - timedelta(seconds=stale_after_seconds):
        status = WorkerStatus.OFFLINE
    return WorkerHeartbeatRecord(
        id=model.id,
        node_name=model.node_name,
        gpu_slot=model.gpu_slot,
        status=status,
        last_heartbeat_at=model.last_heartbeat_at,
        running_job_id=model.running_job_id,
    )


def _to_assignment_record(model: JobAssignmentORM) -> JobAssignment:
    return JobAssignment(
        id=model.id,
        job_id=model.job_id,
        worker_id=model.worker_id,
        assigned_at=model.assigned_at,
        claimed_at=model.claimed_at,
        completed_at=model.completed_at,
    )


class ControlPlaneStore:
    def __init__(self, session_factory: sessionmaker[Session], storage: MinIOStorage | None = None) -> None:
        self._session_factory = session_factory
        self._storage = storage

    def ping_database(self) -> bool:
        with self._session_factory() as session:
            session.execute(text("SELECT 1"))
        return True

    def get_database_utcnow(self) -> datetime:
        with self._session_factory() as session:
            return session.execute(text("SELECT CURRENT_TIMESTAMP")).scalar_one()

    def ensure_worker_identity_available(
        self,
        *,
        worker_id: str,
        node_name: str,
        gpu_slot: int,
        stale_after_seconds: int,
    ) -> None:
        cutoff = utcnow() - timedelta(seconds=stale_after_seconds)
        with self._session_factory() as session:
            existing_worker = session.get(WorkerHeartbeatORM, worker_id)
            if (
                existing_worker is not None
                and existing_worker.last_heartbeat_at >= cutoff
                and existing_worker.status != WorkerStatus.OFFLINE.value
                and (existing_worker.node_name != node_name or existing_worker.gpu_slot != gpu_slot)
            ):
                raise RuntimeError(
                    f'worker_id "{worker_id}" is already registered by '
                    f'{existing_worker.node_name}/gpu{existing_worker.gpu_slot}.'
                )

            conflicting_slot = session.scalars(
                select(WorkerHeartbeatORM).where(
                    WorkerHeartbeatORM.node_name == node_name,
                    WorkerHeartbeatORM.gpu_slot == gpu_slot,
                    WorkerHeartbeatORM.id != worker_id,
                    WorkerHeartbeatORM.last_heartbeat_at >= cutoff,
                    WorkerHeartbeatORM.status != WorkerStatus.OFFLINE.value,
                )
            ).first()
            if conflicting_slot is not None:
                raise RuntimeError(
                    f'node_name "{node_name}" gpu_slot "{gpu_slot}" is already occupied by '
                    f'worker_id "{conflicting_slot.id}".'
                )

    def ping_storage(self) -> bool:
        if self._storage is None:
            return False
        self._storage.ensure_bucket()
        return True

    def create_upload(self, *, filename: str, content_type: str, payload: bytes) -> UploadRecord:
        if self._storage is None:
            raise RuntimeError("Storage backend is not configured.")

        upload_id = new_id("upl")
        safe_name = safe_filename(filename)
        from hashlib import sha256

        digest = sha256(payload).hexdigest()
        storage_key = f"uploads/{upload_id}/{safe_name}"
        self._storage.put_bytes(storage_key, payload, content_type=content_type or "application/octet-stream")

        record = UploadORM(
            id=upload_id,
            filename=safe_name,
            content_type=content_type or "application/octet-stream",
            size_bytes=len(payload),
            sha256=digest,
            storage_key=storage_key,
            created_at=utcnow(),
        )
        with self._session_factory() as session:
            session.add(record)
            session.commit()
            session.refresh(record)
            return _to_upload_record(record)

    def get_upload(self, upload_id: str) -> UploadRecord | None:
        with self._session_factory() as session:
            record = session.get(UploadORM, upload_id)
            return _to_upload_record(record) if record else None

    def create_job(self, request: JobCreateRequest, *, batch_id: str | None = None) -> JobRecord:
        with self._session_factory() as session:
            upload = session.get(UploadORM, request.upload_id)
            if upload is None:
                raise KeyError(f"Unknown upload_id: {request.upload_id}")

            now = utcnow()
            record = JobORM(
                id=new_id("job"),
                batch_id=batch_id,
                upload_id=request.upload_id,
                status=JobStatus.QUEUED.value,
                priority=request.priority.value,
                static_camera=request.static_camera,
                use_dpvo=request.use_dpvo,
                video_render=request.video_render,
                video_type=request.video_type,
                f_mm=request.f_mm,
                artifact_count=0,
                retry_count=0,
                max_retries=1,
                failure_category=None,
                next_retry_at=None,
                created_at=now,
                updated_at=now,
            )
            session.add(record)
            session.flush()
            if batch_id:
                self._refresh_batch_state(session, batch_id)
            session.commit()
            session.refresh(record)
            return _to_job_record(record)

    def get_job(self, job_id: str) -> JobRecord | None:
        with self._session_factory() as session:
            record = session.get(JobORM, job_id)
            return _to_job_record(record) if record else None

    def cancel_job(self, job_id: str) -> JobRecord:
        with self._session_factory() as session:
            record = session.get(JobORM, job_id)
            if record is None:
                raise KeyError(f"Unknown job_id: {job_id}")

            now = utcnow()
            status = JobStatus(record.status)
            if status in {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELED}:
                return _to_job_record(record)

            if status is JobStatus.RUNNING:
                record.cancel_requested_at = now
                record.updated_at = now
            elif status is JobStatus.SCHEDULED:
                record.status = JobStatus.CANCELED.value
                record.finished_at = now
                record.updated_at = now
                self._release_worker_for_job(session, record.id, record.assigned_worker_id)
            else:
                record.status = JobStatus.CANCELED.value
                record.finished_at = now
                record.updated_at = now

            if record.batch_id:
                self._refresh_batch_state(session, record.batch_id)
            session.commit()
            session.refresh(record)
            return _to_job_record(record)

    def list_job_artifacts(self, job_id: str) -> list[ArtifactRecord]:
        with self._session_factory() as session:
            query = (
                select(ArtifactORM)
                .where(ArtifactORM.job_id == job_id)
                .order_by(ArtifactORM.created_at.asc())
            )
            return [_to_artifact_record(item) for item in session.scalars(query).all()]

    def get_artifact(self, artifact_id: str) -> ArtifactRecord | None:
        with self._session_factory() as session:
            record = session.get(ArtifactORM, artifact_id)
            return _to_artifact_record(record) if record else None

    def get_artifact_bytes(self, artifact_id: str) -> bytes | None:
        if self._storage is None:
            return None
        artifact = self.get_artifact(artifact_id)
        if artifact is None:
            return None
        return self._storage.get_bytes(artifact.storage_key)

    def create_batch(self, request: BatchCreateRequest) -> BatchRecord:
        with self._session_factory() as session:
            missing = [
                item.upload_id
                for item in request.items
                if session.get(UploadORM, item.upload_id) is None
            ]
            if missing:
                raise KeyError(f"Unknown upload_id(s): {', '.join(missing)}")

            now = utcnow()
            batch = BatchORM(
                id=new_id("bat"),
                name=request.name,
                status=BatchStatus.QUEUED.value,
                created_at=now,
                updated_at=now,
            )
            session.add(batch)
            session.flush()

            for item in request.items:
                session.add(
                    JobORM(
                        id=new_id("job"),
                        batch_id=batch.id,
                        upload_id=item.upload_id,
                        status=JobStatus.QUEUED.value,
                        priority=item.priority.value,
                        static_camera=item.static_camera,
                        use_dpvo=item.use_dpvo,
                        video_render=item.video_render,
                        video_type=item.video_type,
                        f_mm=item.f_mm,
                        artifact_count=0,
                        retry_count=0,
                        max_retries=1,
                        failure_category=None,
                        next_retry_at=None,
                        created_at=now,
                        updated_at=now,
                    )
                )

            session.flush()
            self._refresh_batch_state(session, batch.id)
            session.commit()
            return self._build_batch_record(session, batch.id)

    def get_batch(self, batch_id: str) -> BatchRecord | None:
        with self._session_factory() as session:
            if session.get(BatchORM, batch_id) is None:
                return None
            self._refresh_batch_state(session, batch_id)
            session.commit()
            return self._build_batch_record(session, batch_id)

    def list_workers(self, *, offline_after_seconds: int) -> list[WorkerHeartbeatRecord]:
        with self._session_factory() as session:
            query = select(WorkerHeartbeatORM).order_by(WorkerHeartbeatORM.node_name, WorkerHeartbeatORM.gpu_slot)
            return [
                _to_worker_record(item, stale_after_seconds=offline_after_seconds)
                for item in session.scalars(query).all()
            ]

    def list_active_jobs(self, *, limit: int = 20) -> list[JobRecord]:
        status_order = case(
            (JobORM.status == JobStatus.RUNNING.value, 3),
            (JobORM.status == JobStatus.SCHEDULED.value, 2),
            (JobORM.status == JobStatus.QUEUED.value, 1),
            else_=0,
        )
        with self._session_factory() as session:
            query = (
                select(JobORM)
                .where(
                    JobORM.status.in_(
                        [
                            JobStatus.QUEUED.value,
                            JobStatus.SCHEDULED.value,
                            JobStatus.RUNNING.value,
                        ]
                    )
                )
                .order_by(status_order.desc(), _priority_order().desc(), JobORM.updated_at.desc(), JobORM.created_at.desc())
                .limit(limit)
            )
            return [_to_job_record(item) for item in session.scalars(query).all()]

    def list_active_batches(self, *, limit: int = 20) -> list[BatchRecord]:
        with self._session_factory() as session:
            batch_ids = session.scalars(
                select(BatchORM.id)
                .where(BatchORM.status.in_([BatchStatus.QUEUED.value, BatchStatus.RUNNING.value]))
                .order_by(BatchORM.updated_at.desc(), BatchORM.created_at.desc())
                .limit(limit)
            ).all()
            return [self._build_batch_record(session, batch_id) for batch_id in batch_ids]

    def list_queued_jobs(self) -> list[JobRecord]:
        now = utcnow()
        with self._session_factory() as session:
            query = (
                select(JobORM)
                .where(
                    JobORM.status == JobStatus.QUEUED.value,
                    or_(JobORM.next_retry_at.is_(None), JobORM.next_retry_at <= now),
                )
                .order_by(_priority_order().desc(), JobORM.created_at.asc())
            )
            return [_to_job_record(item) for item in session.scalars(query).all()]

    def list_scheduled_jobs(self) -> list[JobRecord]:
        with self._session_factory() as session:
            query = (
                select(JobORM)
                .where(JobORM.status == JobStatus.SCHEDULED.value)
                .order_by(JobORM.updated_at.asc(), JobORM.created_at.asc())
            )
            return [_to_job_record(item) for item in session.scalars(query).all()]

    def upsert_worker_heartbeat(
        self,
        *,
        worker_id: str,
        node_name: str,
        gpu_slot: int,
        status: WorkerStatus,
        running_job_id: str | None,
    ) -> WorkerHeartbeatRecord:
        with self._session_factory() as session:
            record = session.get(WorkerHeartbeatORM, worker_id)
            now = utcnow()
            preserved_running_job_id = running_job_id
            preserved_status = status

            if record is not None and running_job_id is None:
                active_job = session.scalars(
                    select(JobORM)
                    .where(
                        JobORM.assigned_worker_id == worker_id,
                        JobORM.status.in_([JobStatus.SCHEDULED.value, JobStatus.RUNNING.value]),
                    )
                    .order_by(JobORM.updated_at.asc())
                ).first()
                if active_job is not None:
                    preserved_running_job_id = active_job.id
                    preserved_status = WorkerStatus.BUSY

            if record is None:
                record = WorkerHeartbeatORM(
                    id=worker_id,
                    node_name=node_name,
                    gpu_slot=gpu_slot,
                    status=preserved_status.value,
                    last_heartbeat_at=now,
                    running_job_id=preserved_running_job_id,
                )
                session.add(record)
            else:
                record.node_name = node_name
                record.gpu_slot = gpu_slot
                record.status = preserved_status.value
                record.last_heartbeat_at = now
                record.running_job_id = preserved_running_job_id

            session.commit()
            session.refresh(record)
            return _to_worker_record(record)

    def mark_stale_workers_offline(
        self,
        *,
        offline_after_seconds: int,
        retry_delay_seconds: int | None = None,
    ) -> StaleWorkerRecoveryResult:
        cutoff = utcnow() - timedelta(seconds=offline_after_seconds)
        failed_job_ids: list[str] = []
        retried_jobs: list[tuple[str, JobPriority]] = []

        with self._session_factory() as session:
            stale_workers = session.scalars(
                select(WorkerHeartbeatORM).where(
                    WorkerHeartbeatORM.last_heartbeat_at < cutoff,
                    WorkerHeartbeatORM.status != WorkerStatus.OFFLINE.value,
                )
            ).all()

            for worker in stale_workers:
                if worker.running_job_id:
                    job = session.get(JobORM, worker.running_job_id)
                    if job and job.status in {JobStatus.SCHEDULED.value, JobStatus.RUNNING.value}:
                        error_message = f"Worker {worker.id} heartbeat timed out."
                        retried = self._transition_job_after_failure(
                            session,
                            job=job,
                            worker_id=worker.id,
                            error_message=error_message,
                            failure_category=FailureCategory.INFRA_TRANSIENT,
                            retry_delay_seconds=retry_delay_seconds,
                            canceled=False,
                        )
                        if retried:
                            retried_jobs.append((job.id, JobPriority(job.priority)))
                        else:
                            failed_job_ids.append(job.id)
                        if job.batch_id:
                            self._refresh_batch_state(session, job.batch_id)

                worker.status = WorkerStatus.OFFLINE.value
                worker.running_job_id = None

            session.commit()
        return StaleWorkerRecoveryResult(
            failed_job_ids=failed_job_ids,
            retried_jobs=retried_jobs,
        )

    def assign_job_to_worker(
        self,
        *,
        job_id: str,
        worker_id: str,
        offline_after_seconds: int,
    ) -> DispatchDecision:
        cutoff = utcnow() - timedelta(seconds=offline_after_seconds)

        with self._session_factory() as session:
            worker = session.get(WorkerHeartbeatORM, worker_id)
            if worker is None:
                return DispatchDecision(
                    scheduled=False,
                    requeue_job=True,
                    requeue_worker=False,
                    reason=f"Worker {worker_id} does not exist.",
                )

            has_active_assignment = session.scalars(
                select(JobORM)
                .where(
                    JobORM.assigned_worker_id == worker_id,
                    JobORM.status.in_([JobStatus.SCHEDULED.value, JobStatus.RUNNING.value]),
                )
                .order_by(JobORM.updated_at.asc())
            ).first()
            if (
                worker.status != WorkerStatus.IDLE.value
                or worker.last_heartbeat_at < cutoff
                or has_active_assignment is not None
            ):
                return DispatchDecision(
                    scheduled=False,
                    requeue_job=True,
                    requeue_worker=False,
                    reason=f"Worker {worker_id} is not dispatchable.",
                )

            job = session.get(JobORM, job_id)
            if job is None:
                return DispatchDecision(
                    scheduled=False,
                    requeue_job=False,
                    requeue_worker=True,
                    reason=f"Job {job_id} does not exist.",
                )
            if job.status != JobStatus.QUEUED.value:
                return DispatchDecision(
                    scheduled=False,
                    requeue_job=False,
                    requeue_worker=True,
                    reason=f"Job {job_id} is not queued.",
                    job=_to_job_record(job),
                    worker=_to_worker_record(worker),
                )
            if job.next_retry_at is not None and job.next_retry_at > utcnow():
                return DispatchDecision(
                    scheduled=False,
                    requeue_job=False,
                    requeue_worker=True,
                    reason=f"Job {job_id} is not ready for retry yet.",
                    job=_to_job_record(job),
                    worker=_to_worker_record(worker),
                )

            now = utcnow()
            job.status = JobStatus.SCHEDULED.value
            job.assigned_worker_id = worker.id
            job.assigned_gpu_slot = worker.gpu_slot
            job.error_message = None
            job.failure_category = None
            job.next_retry_at = None
            job.updated_at = now

            worker.status = WorkerStatus.BUSY.value
            worker.running_job_id = job.id

            assignment = JobAssignmentORM(
                id=new_id("asg"),
                job_id=job.id,
                worker_id=worker.id,
                assigned_at=now,
            )
            session.add(assignment)

            if job.batch_id:
                self._refresh_batch_state(session, job.batch_id)
            session.commit()
            session.refresh(job)
            session.refresh(worker)
            return DispatchDecision(
                scheduled=True,
                requeue_job=False,
                requeue_worker=False,
                reason="scheduled",
                job=_to_job_record(job),
                worker=_to_worker_record(worker),
            )

    def requeue_stale_scheduled_jobs(
        self,
        *,
        claim_timeout_seconds: int,
        offline_after_seconds: int,
    ) -> tuple[list[tuple[str, JobPriority]], list[str]]:
        now = utcnow()
        claim_cutoff = now - timedelta(seconds=claim_timeout_seconds)
        offline_cutoff = now - timedelta(seconds=offline_after_seconds)
        requeued_jobs: list[tuple[str, JobPriority]] = []
        reusable_workers: list[str] = []

        with self._session_factory() as session:
            assignments = session.scalars(
                select(JobAssignmentORM)
                .join(JobORM, JobORM.id == JobAssignmentORM.job_id)
                .where(
                    JobORM.status == JobStatus.SCHEDULED.value,
                    JobAssignmentORM.claimed_at.is_(None),
                    JobAssignmentORM.assigned_at < claim_cutoff,
                )
                .order_by(JobAssignmentORM.assigned_at.asc())
            ).all()

            for assignment in assignments:
                job = session.get(JobORM, assignment.job_id)
                if job is None or job.status != JobStatus.SCHEDULED.value:
                    continue

                worker = session.get(WorkerHeartbeatORM, assignment.worker_id)
                worker_is_stale = worker is None or worker.last_heartbeat_at < offline_cutoff

                job.status = JobStatus.QUEUED.value
                job.assigned_worker_id = None
                job.assigned_gpu_slot = None
                job.next_retry_at = None
                job.updated_at = now

                if worker is not None:
                    if worker_is_stale:
                        worker.status = WorkerStatus.OFFLINE.value
                    else:
                        worker.status = WorkerStatus.IDLE.value
                        reusable_workers.append(worker.id)
                    if worker.running_job_id == job.id:
                        worker.running_job_id = None

                session.delete(assignment)
                requeued_jobs.append((job.id, JobPriority(job.priority)))
                if job.batch_id:
                    self._refresh_batch_state(session, job.batch_id)

            session.commit()
        return requeued_jobs, reusable_workers

    def schedule_next_job(self, *, offline_after_seconds: int) -> tuple[JobRecord, WorkerHeartbeatRecord] | None:
        now = utcnow()
        cutoff = now - timedelta(seconds=offline_after_seconds)

        with self._session_factory() as session:
            worker = session.scalars(
                select(WorkerHeartbeatORM)
                .where(
                    WorkerHeartbeatORM.status == WorkerStatus.IDLE.value,
                    WorkerHeartbeatORM.last_heartbeat_at >= cutoff,
                )
                .order_by(WorkerHeartbeatORM.node_name.asc(), WorkerHeartbeatORM.gpu_slot.asc())
            ).first()
            if worker is None:
                return None

            job = session.scalars(
                select(JobORM)
                .where(
                    JobORM.status == JobStatus.QUEUED.value,
                    or_(JobORM.next_retry_at.is_(None), JobORM.next_retry_at <= now),
                )
                .order_by(_priority_order().desc(), JobORM.created_at.asc())
            ).first()
            if job is None:
                return None

            job.status = JobStatus.SCHEDULED.value
            job.assigned_worker_id = worker.id
            job.assigned_gpu_slot = worker.gpu_slot
            job.error_message = None
            job.failure_category = None
            job.next_retry_at = None
            job.updated_at = now

            worker.status = WorkerStatus.BUSY.value
            worker.running_job_id = job.id

            assignment = JobAssignmentORM(
                id=new_id("asg"),
                job_id=job.id,
                worker_id=worker.id,
                assigned_at=now,
            )
            session.add(assignment)

            if job.batch_id:
                self._refresh_batch_state(session, job.batch_id)
            session.commit()
            session.refresh(job)
            session.refresh(worker)
            return _to_job_record(job), _to_worker_record(worker)

    def revert_scheduled_job(self, *, job_id: str, worker_id: str) -> JobRecord | None:
        with self._session_factory() as session:
            job = session.get(JobORM, job_id)
            if job is None:
                return None
            if job.assigned_worker_id != worker_id or job.status != JobStatus.SCHEDULED.value:
                return _to_job_record(job)

            now = utcnow()
            job.status = JobStatus.QUEUED.value
            job.assigned_worker_id = None
            job.assigned_gpu_slot = None
            job.updated_at = now

            worker = session.get(WorkerHeartbeatORM, worker_id)
            if worker is not None and worker.status != WorkerStatus.OFFLINE.value:
                worker.status = WorkerStatus.IDLE.value
                if worker.running_job_id == job_id:
                    worker.running_job_id = None

            assignment = session.scalars(
                select(JobAssignmentORM).where(JobAssignmentORM.job_id == job_id)
            ).first()
            if assignment is not None:
                session.delete(assignment)

            if job.batch_id:
                self._refresh_batch_state(session, job.batch_id)
            session.commit()
            session.refresh(job)
            return _to_job_record(job)

    def get_scheduled_job_for_worker(self, worker_id: str) -> JobExecutionPayload | None:
        with self._session_factory() as session:
            job = session.scalars(
                select(JobORM)
                .where(
                    JobORM.assigned_worker_id == worker_id,
                    JobORM.status == JobStatus.SCHEDULED.value,
                )
                .order_by(JobORM.updated_at.asc())
            ).first()
            if job is None:
                return None

            upload = session.get(UploadORM, job.upload_id)
            if upload is None:
                raise RuntimeError(f"Upload {job.upload_id} not found for job {job.id}")

            return JobExecutionPayload(job=_to_job_record(job), upload=_to_upload_record(upload))

    def get_scheduled_job_by_id_for_worker(self, *, worker_id: str, job_id: str) -> JobExecutionPayload | None:
        with self._session_factory() as session:
            job = session.scalars(
                select(JobORM).where(
                    JobORM.id == job_id,
                    JobORM.assigned_worker_id == worker_id,
                    JobORM.status == JobStatus.SCHEDULED.value,
                )
            ).first()
            if job is None:
                return None

            upload = session.get(UploadORM, job.upload_id)
            if upload is None:
                raise RuntimeError(f"Upload {job.upload_id} not found for job {job.id}")

            return JobExecutionPayload(job=_to_job_record(job), upload=_to_upload_record(upload))

    def mark_job_running(self, *, job_id: str, worker_id: str) -> JobRecord:
        with self._session_factory() as session:
            job = session.get(JobORM, job_id)
            if job is None:
                raise KeyError(f"Unknown job_id: {job_id}")
            if job.assigned_worker_id != worker_id:
                raise ValueError(f"Job {job_id} is not assigned to worker {worker_id}")

            now = utcnow()
            job.status = JobStatus.RUNNING.value
            job.started_at = job.started_at or now
            job.error_message = None
            job.failure_category = None
            job.next_retry_at = None
            job.updated_at = now

            assignment = session.scalars(
                select(JobAssignmentORM).where(JobAssignmentORM.job_id == job.id)
            ).first()
            if assignment:
                assignment.claimed_at = now

            if job.batch_id:
                self._refresh_batch_state(session, job.batch_id)
            session.commit()
            session.refresh(job)
            return _to_job_record(job)

    def is_cancel_requested(self, job_id: str) -> bool:
        with self._session_factory() as session:
            job = session.get(JobORM, job_id)
            if job is None:
                return False
            return job.cancel_requested_at is not None

    def complete_job_success(
        self,
        *,
        job_id: str,
        worker_id: str,
        artifacts: Iterable[UploadedArtifact],
    ) -> JobRecord:
        with self._session_factory() as session:
            job = session.get(JobORM, job_id)
            if job is None:
                raise KeyError(f"Unknown job_id: {job_id}")

            now = utcnow()
            self._persist_artifacts(session, job=job, artifacts=artifacts, created_at=now)
            job.status = JobStatus.SUCCEEDED.value
            job.error_message = None
            job.failure_category = None
            job.next_retry_at = None
            job.finished_at = now
            job.updated_at = now
            self._release_worker_for_job(session, job_id, worker_id)
            if job.batch_id:
                self._refresh_batch_state(session, job.batch_id)
            session.commit()
            session.refresh(job)
            return _to_job_record(job)

    def complete_job_failure(
        self,
        *,
        job_id: str,
        worker_id: str,
        error_message: str,
        failure_category: FailureCategory | None = None,
        retry_delay_seconds: int | None = None,
        canceled: bool = False,
        artifacts: Iterable[UploadedArtifact] = (),
    ) -> JobRecord:
        with self._session_factory() as session:
            job = session.get(JobORM, job_id)
            if job is None:
                raise KeyError(f"Unknown job_id: {job_id}")

            now = utcnow()
            self._persist_artifacts(session, job=job, artifacts=artifacts, created_at=now)
            self._transition_job_after_failure(
                session,
                job=job,
                worker_id=worker_id,
                error_message=error_message,
                failure_category=failure_category,
                retry_delay_seconds=retry_delay_seconds,
                canceled=canceled,
            )
            if job.batch_id:
                self._refresh_batch_state(session, job.batch_id)
            session.commit()
            session.refresh(job)
            return _to_job_record(job)

    def download_upload(self, *, upload: UploadRecord, destination: Path) -> Path:
        if self._storage is None:
            raise RuntimeError("Storage backend is not configured.")
        return self._storage.download_file(upload.storage_key, destination)

    def upload_file_artifact(
        self,
        *,
        job_id: str,
        file_path: Path,
        artifact_kind: ArtifactKind,
        subdir: str,
        content_type: str = "application/octet-stream",
        filename_override: str | None = None,
    ) -> UploadedArtifact:
        if self._storage is None:
            raise RuntimeError("Storage backend is not configured.")
        filename = safe_filename(filename_override or file_path.name)
        storage_key = f"jobs/{job_id}/{subdir}/{filename}"
        self._storage.fput_file(storage_key, file_path, content_type=content_type)
        return UploadedArtifact(
            kind=artifact_kind,
            filename=filename,
            storage_key=storage_key,
        )

    def _persist_artifacts(
        self,
        session: Session,
        *,
        job: JobORM,
        artifacts: Iterable[UploadedArtifact],
        created_at: datetime,
    ) -> None:
        artifact_count = job.artifact_count
        for item in artifacts:
            session.add(
                ArtifactORM(
                    id=new_id("art"),
                    job_id=job.id,
                    kind=item.kind.value,
                    filename=item.filename,
                    storage_key=item.storage_key,
                    created_at=created_at,
                )
            )
            artifact_count += 1
        job.artifact_count = artifact_count

    def _transition_job_after_failure(
        self,
        session: Session,
        *,
        job: JobORM,
        worker_id: str | None,
        error_message: str,
        failure_category: FailureCategory | None,
        retry_delay_seconds: int | None,
        canceled: bool,
    ) -> bool:
        now = utcnow()
        should_retry = (
            not canceled
            and retry_delay_seconds is not None
            and job.retry_count < job.max_retries
        )

        if should_retry:
            job.status = JobStatus.QUEUED.value
            job.retry_count += 1
            job.error_message = error_message
            job.failure_category = failure_category.value if failure_category else None
            job.next_retry_at = now + timedelta(seconds=max(retry_delay_seconds, 0))
            job.finished_at = None
            job.updated_at = now
            job.cancel_requested_at = None
        else:
            job.status = JobStatus.CANCELED.value if canceled else JobStatus.FAILED.value
            job.error_message = error_message
            job.failure_category = failure_category.value if failure_category else None
            job.next_retry_at = None
            job.finished_at = now
            job.updated_at = now

        self._release_worker_for_job(session, job.id, worker_id)
        return should_retry

    def _release_worker_for_job(self, session: Session, job_id: str, worker_id: str | None) -> None:
        now = utcnow()
        if worker_id:
            worker = session.get(WorkerHeartbeatORM, worker_id)
            if worker:
                if worker.status != WorkerStatus.OFFLINE.value:
                    worker.status = WorkerStatus.IDLE.value
                if worker.running_job_id == job_id:
                    worker.running_job_id = None

        assignment = session.scalars(
            select(JobAssignmentORM).where(JobAssignmentORM.job_id == job_id)
        ).first()
        if assignment:
            assignment.completed_at = assignment.completed_at or now

    def _build_batch_record(self, session: Session, batch_id: str) -> BatchRecord:
        batch = session.get(BatchORM, batch_id)
        if batch is None:
            raise KeyError(f"Unknown batch_id: {batch_id}")

        jobs = session.scalars(
            select(JobORM).where(JobORM.batch_id == batch_id).order_by(JobORM.created_at.asc())
        ).all()
        counts = self._build_batch_counts(jobs)
        return BatchRecord(
            id=batch.id,
            name=batch.name,
            status=BatchStatus(batch.status),
            job_ids=[job.id for job in jobs],
            counts=counts,
            created_at=batch.created_at,
            updated_at=batch.updated_at,
        )

    def _build_batch_counts(self, jobs: Iterable[JobORM]) -> BatchCounts:
        counts = BatchCounts()
        jobs_list = list(jobs)
        counts.total_jobs = len(jobs_list)
        for job in jobs_list:
            status = JobStatus(job.status)
            if status is JobStatus.QUEUED:
                counts.queued += 1
            elif status is JobStatus.SCHEDULED:
                counts.scheduled += 1
            elif status is JobStatus.RUNNING:
                counts.running += 1
            elif status is JobStatus.SUCCEEDED:
                counts.succeeded += 1
            elif status is JobStatus.FAILED:
                counts.failed += 1
            elif status is JobStatus.CANCELED:
                counts.canceled += 1
        return counts

    def _refresh_batch_state(self, session: Session, batch_id: str) -> None:
        batch = session.get(BatchORM, batch_id)
        if batch is None:
            return

        jobs = session.scalars(select(JobORM).where(JobORM.batch_id == batch_id)).all()
        statuses = [JobStatus(job.status) for job in jobs]
        counts = self._build_batch_counts(jobs)

        if statuses and all(status is JobStatus.CANCELED for status in statuses):
            status = BatchStatus.CANCELED
        elif any(status is JobStatus.RUNNING for status in statuses):
            status = BatchStatus.RUNNING
        elif any(status is JobStatus.SCHEDULED for status in statuses):
            status = BatchStatus.QUEUED
        elif statuses and all(status is JobStatus.SUCCEEDED for status in statuses):
            status = BatchStatus.SUCCEEDED
        elif statuses and all(status in {JobStatus.FAILED, JobStatus.CANCELED} for status in statuses):
            status = BatchStatus.FAILED
        elif counts.succeeded > 0 and (counts.failed > 0 or counts.canceled > 0):
            status = BatchStatus.PARTIAL_FAILED
        else:
            status = BatchStatus.QUEUED

        batch.status = status.value
        batch.updated_at = utcnow()
