from __future__ import annotations

import hashlib
import json


def _digest(payload: dict[str, object]) -> str:
    content = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def normalize_video_type(video_type: str) -> str:
    raw = video_type.strip().lower()
    if raw in {"", "none"}:
        return "none"
    if raw == "all":
        return "all"
    items = sorted(part.strip() for part in raw.split(",") if part.strip())
    return ",".join(items) if items else "none"


def build_core_cache_key(
    *,
    video_sha256: str,
    static_camera: bool,
    f_mm: int | None,
    upstream_version: str,
) -> str:
    return _digest(
        {
            "video_sha256": video_sha256,
            "static_camera": static_camera,
            "f_mm": f_mm,
            "upstream_version": upstream_version,
        }
    )


def build_render_cache_key(
    *,
    core_cache_key: str,
    video_render: bool,
    video_type: str,
) -> str:
    return _digest(
        {
            "core_cache_key": core_cache_key,
            "video_render": video_render,
            "video_type": normalize_video_type(video_type),
        }
    )

