from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from gvhmr_batch_common.enums import (
    ArtifactKind,
    BatchStatus,
    FailureCategory,
    JobPriority,
    JobStatus,
    WorkerStatus,
)


class UploadRecord(BaseModel):
    id: str
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    storage_key: str
    created_at: datetime


class JobCreateRequest(BaseModel):
    upload_id: str
    static_camera: bool = True
    use_dpvo: bool = False
    video_render: bool = False
    video_type: str = "none"
    f_mm: int | None = None
    priority: JobPriority = JobPriority.NORMAL


class BatchItemCreateRequest(BaseModel):
    upload_id: str
    static_camera: bool = True
    use_dpvo: bool = False
    video_render: bool = False
    video_type: str = "none"
    f_mm: int | None = None
    priority: JobPriority = JobPriority.NORMAL


class ArtifactRecord(BaseModel):
    id: str
    job_id: str
    kind: ArtifactKind
    filename: str
    storage_key: str
    created_at: datetime


class JobRecord(JobCreateRequest):
    id: str
    batch_id: str | None = None
    upload_filename: str | None = None
    status: JobStatus = JobStatus.QUEUED
    assigned_worker_id: str | None = None
    assigned_gpu_slot: int | None = None
    artifact_count: int = 0
    retry_count: int = 0
    max_retries: int = 1
    failure_category: FailureCategory | None = None
    next_retry_at: datetime | None = None
    error_message: str | None = None
    cancel_requested_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class BatchCounts(BaseModel):
    total_jobs: int = 0
    queued: int = 0
    scheduled: int = 0
    running: int = 0
    succeeded: int = 0
    failed: int = 0
    canceled: int = 0


class BatchCreateRequest(BaseModel):
    name: str
    items: list[BatchItemCreateRequest] = Field(min_length=1)


class BatchRecord(BaseModel):
    id: str
    name: str
    status: BatchStatus
    job_ids: list[str]
    counts: BatchCounts
    created_at: datetime
    updated_at: datetime


class WorkerHeartbeatRecord(BaseModel):
    id: str
    node_name: str
    gpu_slot: int
    status: WorkerStatus
    last_heartbeat_at: datetime
    running_job_id: str | None = None


class JobAssignment(BaseModel):
    id: str
    job_id: str
    worker_id: str
    assigned_at: datetime
    claimed_at: datetime | None = None
    completed_at: datetime | None = None


class HealthResponse(BaseModel):
    status: str
    app_name: str
    mode: str
    services: dict[str, str]
