from __future__ import annotations

from fastapi import APIRouter

from gvhmr_batch_api.container import get_queue, get_settings, get_store
from gvhmr_batch_common.schemas import HealthResponse

router = APIRouter(tags=["health"])


def build_health_response() -> HealthResponse:
    settings = get_settings()
    store = get_store()

    db_status = "up"
    redis_status = "up"
    storage_status = "up"

    try:
        store.ping_database()
    except Exception:
        db_status = "down"

    try:
        get_queue().ping()
    except Exception:
        redis_status = "down"

    try:
        store.ping_storage()
    except Exception:
        storage_status = "down"

    app_status = "healthy" if db_status == "up" and redis_status == "up" and storage_status == "up" else "degraded"
    return HealthResponse(
        status=app_status,
        app_name=settings.app_name,
        mode=settings.control_plane_backend,
        services={
            "api": "up",
            "scheduler": "managed-by-compose",
            "worker": "managed-by-compose",
            "postgres": db_status,
            "redis": redis_status,
            "minio": storage_status,
        },
    )


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return build_health_response()
