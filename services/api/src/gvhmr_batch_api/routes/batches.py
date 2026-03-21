from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from gvhmr_batch_api.container import get_queue, get_store
from gvhmr_batch_common.schemas import BatchCreateRequest, BatchRecord

router = APIRouter(tags=["batches"])


@router.post("/batches", response_model=BatchRecord, status_code=status.HTTP_201_CREATED)
def create_batch(request: BatchCreateRequest) -> BatchRecord:
    try:
        batch = get_store().create_batch(request)
        jobs = [get_store().get_job(job_id) for job_id in batch.job_ids]
        get_queue().enqueue_jobs(
            [
                (job.id, job.priority)
                for job in jobs
                if job is not None
            ]
        )
        return batch
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/batches/{batch_id}", response_model=BatchRecord)
def get_batch(batch_id: str) -> BatchRecord:
    record = get_store().get_batch(batch_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Batch 不存在。")
    return record
