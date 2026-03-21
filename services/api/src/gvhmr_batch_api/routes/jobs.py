from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from gvhmr_batch_api.container import get_queue, get_store
from gvhmr_batch_common.schemas import ArtifactRecord, JobCreateRequest, JobRecord

router = APIRouter(tags=["jobs"])


@router.post("/jobs", response_model=JobRecord, status_code=status.HTTP_201_CREATED)
def create_job(request: JobCreateRequest) -> JobRecord:
    try:
        job = get_store().create_job(request)
        get_queue().enqueue_job(job_id=job.id, priority=job.priority)
        return job
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/jobs/{job_id}", response_model=JobRecord)
def get_job(job_id: str) -> JobRecord:
    record = get_store().get_job(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Job 不存在。")
    return record


@router.post("/jobs/{job_id}/cancel", response_model=JobRecord)
def cancel_job(job_id: str) -> JobRecord:
    try:
        return get_store().cancel_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/jobs/{job_id}/artifacts", response_model=list[ArtifactRecord])
def list_job_artifacts(job_id: str) -> list[ArtifactRecord]:
    if get_store().get_job(job_id) is None:
        raise HTTPException(status_code=404, detail="Job 不存在。")
    return get_store().list_job_artifacts(job_id)
