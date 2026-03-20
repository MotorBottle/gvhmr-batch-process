from __future__ import annotations

from fastapi import APIRouter

from gvhmr_batch_api.container import get_settings, get_store
from gvhmr_batch_common.schemas import WorkerHeartbeatRecord

router = APIRouter(tags=["workers"])


@router.get("/workers", response_model=list[WorkerHeartbeatRecord])
def list_workers() -> list[WorkerHeartbeatRecord]:
    settings = get_settings()
    return get_store().list_workers(offline_after_seconds=settings.worker_offline_after_seconds)
