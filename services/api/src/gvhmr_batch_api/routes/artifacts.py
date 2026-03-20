from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from gvhmr_batch_api.container import get_store

router = APIRouter(tags=["artifacts"])


@router.get("/artifacts/{artifact_id}/download")
def download_artifact(artifact_id: str) -> Response:
    artifact = get_store().get_artifact(artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact 不存在。")

    payload = get_store().get_artifact_bytes(artifact_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Artifact 文件尚未准备好。")

    return Response(
        content=payload,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{artifact.filename}"'},
    )
