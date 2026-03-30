from __future__ import annotations

from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from gvhmr_batch_api.container import get_settings
from gvhmr_batch_api.routes.artifacts import router as artifacts_router
from gvhmr_batch_api.routes.batches import router as batches_router
from gvhmr_batch_api.routes.dashboard import router as dashboard_router
from gvhmr_batch_api.routes.health import router as health_router
from gvhmr_batch_api.routes.jobs import router as jobs_router
from gvhmr_batch_api.routes.uploads import router as uploads_router
from gvhmr_batch_api.routes.web import router as web_router
from gvhmr_batch_api.routes.workers import router as workers_router

settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0")

static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")

app.include_router(web_router)
app.include_router(dashboard_router)
app.include_router(health_router)
app.include_router(uploads_router)
app.include_router(jobs_router)
app.include_router(batches_router)
app.include_router(artifacts_router)
app.include_router(workers_router)


def main() -> None:
    uvicorn.run(
        "gvhmr_batch_api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
    )


if __name__ == "__main__":
    main()
