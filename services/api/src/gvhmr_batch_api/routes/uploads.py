from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from gvhmr_batch_api.container import get_settings, get_store
from gvhmr_batch_common.schemas import UploadRecord

router = APIRouter(tags=["uploads"])


@router.post("/uploads", response_model=UploadRecord, status_code=status.HTTP_201_CREATED)
async def create_upload(video: UploadFile = File(...)) -> UploadRecord:
    payload = await video.read()
    if not payload:
        raise HTTPException(status_code=400, detail="上传文件为空。")

    settings = get_settings()
    max_size = settings.max_upload_size_mb * 1024 * 1024
    if len(payload) > max_size:
        raise HTTPException(status_code=413, detail="上传文件超过当前开发配置限制。")

    return get_store().create_upload(
        filename=video.filename or "upload.bin",
        content_type=video.content_type or "application/octet-stream",
        payload=payload,
    )

