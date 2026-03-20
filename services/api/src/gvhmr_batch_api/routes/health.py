from __future__ import annotations

from fastapi import APIRouter

from gvhmr_batch_api.container import get_settings, get_store
from gvhmr_batch_common.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    store = get_store()

    db_status = "up"
    storage_status = "up"

    try:
        store.ping_database()
    except Exception:
        db_status = "down"

    try:
        store.ping_storage()
    except Exception:
        storage_status = "down"

    app_status = "healthy" if db_status == "up" and storage_status == "up" else "degraded"
    return HealthResponse(
        status=app_status,
        app_name=settings.app_name,
        mode=settings.control_plane_backend,
        services={
            "api": "up",
            "scheduler": "managed-by-compose",
            "worker": "managed-by-compose",
            "postgres": db_status,
            "redis": "deployed-not-on-critical-path",
            "minio": storage_status,
        },
    )
