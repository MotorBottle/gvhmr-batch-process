from __future__ import annotations

import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def parse_ffprobe_rate(value: str) -> float | None:
    value = value.strip()
    if not value or value == "0/0":
        return None
    if "/" in value:
        numerator, denominator = value.split("/", 1)
        try:
            numerator_value = float(numerator)
            denominator_value = float(denominator)
        except ValueError:
            return None
        if denominator_value == 0:
            return None
        fps = numerator_value / denominator_value
    else:
        try:
            fps = float(value)
        except ValueError:
            return None

    if math.isfinite(fps) and fps > 0:
        return float(fps)
    return None


def probe_video_fps(path: Path) -> float | None:
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None or not path.exists():
        return None

    command = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=avg_frame_rate,r_frame_rate",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    try:
        output = subprocess.check_output(command, text=True, stderr=subprocess.DEVNULL).strip().splitlines()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

    for value in output:
        fps = parse_ffprobe_rate(value)
        if fps is not None:
            return fps
    return None


def probe_video_fps_from_bytes(payload: bytes, *, suffix: str = ".bin") -> float | None:
    with tempfile.NamedTemporaryFile(prefix="gvhmr-upload-", suffix=suffix, delete=False) as tmp:
        tmp.write(payload)
        tmp_path = Path(tmp.name)

    try:
        return probe_video_fps(tmp_path)
    finally:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
