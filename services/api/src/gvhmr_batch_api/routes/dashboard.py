from __future__ import annotations

from fastapi import APIRouter

from gvhmr_batch_api.container import get_settings, get_store
from gvhmr_batch_api.routes.health import build_health_response
from gvhmr_batch_common.schemas import DashboardOverview
from gvhmr_batch_common.utils import utcnow

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard/overview", response_model=DashboardOverview)
def dashboard_overview() -> DashboardOverview:
    settings = get_settings()
    store = get_store()
    return DashboardOverview(
        refreshed_at=utcnow(),
        health=build_health_response(),
        workers=store.list_workers(offline_after_seconds=settings.worker_offline_after_seconds),
        active_jobs=store.list_active_jobs(limit=30),
        active_batches=store.list_active_batches(limit=20),
    )
