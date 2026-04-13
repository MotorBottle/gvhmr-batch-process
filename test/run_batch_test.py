from __future__ import annotations

import argparse
import csv
import json
import mimetypes
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
DEFAULT_UPLOAD_DIR = ROOT / "uploads"
DEFAULT_RESULTS_DIR = ROOT / "results"
VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
TERMINAL_BATCH_STATUSES = {"succeeded", "failed", "partial_failed", "canceled"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upload videos from test/uploads, create a batch, and download results.")
    parser.add_argument("--base-url", default="http://127.0.0.1:18000", help="GVHMR Batch Process API base URL.")
    parser.add_argument("--upload-dir", type=Path, default=DEFAULT_UPLOAD_DIR, help="Directory containing test videos.")
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR, help="Directory for downloaded results.")
    parser.add_argument("--batch-name", default=None, help="Optional batch name override.")
    parser.add_argument("--static-camera", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--use-dpvo", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--video-render", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--video-type", default="none")
    parser.add_argument("--f-mm", type=int, default=None)
    parser.add_argument("--priority", choices=["low", "normal", "high"], default="normal")
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--no-wait", action="store_true", help="Create the batch but do not wait for completion.")
    parser.add_argument(
        "--download-artifacts",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Download artifacts into test/results after the batch finishes.",
    )
    return parser.parse_args()


def discover_videos(upload_dir: Path) -> list[Path]:
    if not upload_dir.exists():
        raise SystemExit(f"Upload directory does not exist: {upload_dir}")

    videos = [path for path in sorted(upload_dir.iterdir()) if path.is_file() and path.suffix.lower() in VIDEO_SUFFIXES]
    if not videos:
        raise SystemExit(f"No test videos found in {upload_dir}. Supported suffixes: {', '.join(sorted(VIDEO_SUFFIXES))}")
    return videos


def request_json(method: str, url: str, payload: dict | None = None, headers: dict[str, str] | None = None) -> dict:
    body = None
    request_headers = dict(headers or {})
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")

    request = Request(url=url, data=body, method=method, headers=request_headers)
    try:
        with urlopen(request, timeout=300) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed: {exc.code} {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"{method} {url} failed: {exc}") from exc


def upload_file(base_url: str, file_path: Path) -> dict:
    boundary = f"gvhmr-batch-{uuid.uuid4().hex}"
    content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    header = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="video"; filename="{file_path.name}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode("utf-8")
    footer = f"\r\n--{boundary}--\r\n".encode("utf-8")
    body = header + file_path.read_bytes() + footer

    request = Request(
        url=f"{base_url.rstrip('/')}/uploads",
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urlopen(request, timeout=300) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Upload failed for {file_path.name}: {exc.code} {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Upload failed for {file_path.name}: {exc}") from exc


def download_file(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = Request(url=url, method="GET")
    try:
        with urlopen(request, timeout=300) as response:
            destination.write_bytes(response.read())
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Download failed for {url}: {exc.code} {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Download failed for {url}: {exc}") from exc


def infer_video_fps(video_path: Path) -> float | None:
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None or not video_path.exists():
        return None

    request = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=avg_frame_rate,r_frame_rate",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ]
    try:
        output = subprocess.check_output(request, text=True, stderr=subprocess.DEVNULL).strip().splitlines()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

    for value in output:
        fps = parse_ffprobe_rate(value)
        if fps is not None:
            return fps
    return None


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

    return fps if fps > 0 else None


def save_json(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def save_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return

    fieldnames = [
        "job_id",
        "result_group",
        "result_dir_name",
        "result_dir",
        "upload_id",
        "upload_filename",
        "source_path",
        "source_fps",
        "status",
    ]
    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def safe_label(value: str | None) -> str:
    if not value:
        return "unknown"
    cleaned = value.replace("/", "_").replace("\\", "_").replace(" ", "_")
    return "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in cleaned).strip("._") or "unknown"


def format_batch_timestamp(batch: dict) -> str:
    created_at = batch.get("created_at")
    if not created_at:
        return datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")

    try:
        parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        return parsed.astimezone().strftime("%Y%m%d-%H%M%S")
    except ValueError:
        return datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")


def batch_result_dir_name(batch: dict) -> str:
    timestamp = format_batch_timestamp(batch)
    return f"{timestamp}__{batch['id']}"


def job_result_dir_name(job: dict, upload_meta: dict | None = None) -> str:
    upload_filename = job.get("upload_filename")
    if not upload_filename and upload_meta:
        upload_filename = upload_meta.get("upload", {}).get("filename")
    if not upload_filename:
        return job["id"]
    return f"{job['id']}__{safe_label(Path(upload_filename).stem)}"


def job_result_group(job: dict) -> str:
    return "succeeded" if job.get("status") == "succeeded" else "failed"


def poll_batch(base_url: str, batch_id: str, results_dir: Path, poll_seconds: float) -> dict:
    last_snapshot = None
    while True:
        batch = request_json("GET", f"{base_url.rstrip('/')}/batches/{batch_id}")
        save_json(results_dir / "batch_status.json", batch)

        status = batch["status"]
        counts = batch["counts"]
        snapshot = (
            status,
            counts["total_jobs"],
            counts["queued"],
            counts["scheduled"],
            counts["running"],
            counts["succeeded"],
            counts["failed"],
            counts["canceled"],
        )
        if snapshot != last_snapshot:
            print(
                f"[batch] {batch_id} status={status} "
                f"total={counts['total_jobs']} queued={counts['queued']} scheduled={counts['scheduled']} "
                f"running={counts['running']} succeeded={counts['succeeded']} failed={counts['failed']} canceled={counts['canceled']}"
            )
            last_snapshot = snapshot

        if status in TERMINAL_BATCH_STATUSES:
            return batch

        time.sleep(poll_seconds)


def download_batch_artifacts(base_url: str, batch: dict, batch_dir: Path, uploads: list[dict]) -> None:
    uploads_by_id = {item["upload"]["id"]: item for item in uploads}
    job_index = []
    for job_id in batch["job_ids"]:
        job = request_json("GET", f"{base_url.rstrip('/')}/jobs/{job_id}")
        artifacts = request_json("GET", f"{base_url.rstrip('/')}/jobs/{job_id}/artifacts")
        upload_meta = uploads_by_id.get(job["upload_id"], {})
        source_path = upload_meta.get("source_path")
        source_fps = upload_meta.get("source_fps")
        if source_fps is None:
            source_fps = upload_meta.get("upload", {}).get("source_fps")
        upload_filename = job.get("upload_filename") or upload_meta.get("upload", {}).get("filename")
        result_dir_name = job_result_dir_name(job, upload_meta)
        result_group = job_result_group(job)
        job_dir = batch_dir / result_group / result_dir_name

        save_json(job_dir / "job.json", job)
        save_json(job_dir / "artifacts.json", artifacts)
        job_index.append(
            {
                "job_id": job["id"],
                "result_group": result_group,
                "result_dir_name": result_dir_name,
                "upload_id": job["upload_id"],
                "upload_filename": upload_filename,
                "source_path": source_path,
                "source_fps": source_fps,
                "status": job["status"],
                "result_dir": str(job_dir),
            }
        )

        for artifact in artifacts:
            artifact_filename = artifact["filename"]
            if artifact["kind"] == "input_video" and upload_filename:
                artifact_filename = upload_filename
            artifact_path = job_dir / artifact["kind"] / artifact_filename
            download_file(f"{base_url.rstrip('/')}/artifacts/{artifact['id']}/download", artifact_path)
            print(f"[artifact] job={job_id} saved={artifact_path}")

        if result_group == "failed" and source_path and upload_filename:
            source_video = Path(source_path)
            debug_video_path = job_dir / "input_video" / upload_filename
            if source_video.exists() and not debug_video_path.exists():
                debug_video_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_video, debug_video_path)
                print(f"[artifact] job={job_id} copied-debug-input={debug_video_path}")

    save_json(batch_dir / "job_index.json", job_index)
    save_csv(batch_dir / "job_index.csv", job_index)


def main() -> int:
    args = parse_args()
    base_url = args.base_url.rstrip("/")
    upload_dir = args.upload_dir.resolve()
    results_root = args.results_dir.resolve()

    videos = discover_videos(upload_dir)
    print(f"[discover] found {len(videos)} videos in {upload_dir}")

    uploads = []
    for video_path in videos:
        upload = upload_file(base_url, video_path)
        uploads.append(
            {
                "source_path": str(video_path),
                "source_fps": upload.get("source_fps") if upload.get("source_fps") is not None else infer_video_fps(video_path),
                "upload": upload,
            }
        )
        print(f"[upload] {video_path.name} -> {upload['id']}")

    batch_name = args.batch_name or f"test-batch-{time.strftime('%Y%m%d-%H%M%S')}"
    batch_request = {
        "name": batch_name,
        "items": [
            {
                "upload_id": item["upload"]["id"],
                "static_camera": args.static_camera,
                "use_dpvo": args.use_dpvo,
                "video_render": args.video_render,
                "video_type": args.video_type,
                "f_mm": args.f_mm,
                "priority": args.priority,
            }
            for item in uploads
        ],
    }

    batch = request_json("POST", f"{base_url}/batches", payload=batch_request)
    batch_dir = results_root / batch_result_dir_name(batch)
    batch_dir.mkdir(parents=True, exist_ok=True)

    save_json(batch_dir / "uploads.json", uploads)
    save_json(batch_dir / "batch_request.json", batch_request)
    save_json(batch_dir / "batch_created.json", batch)
    print(f"[batch] created {batch['id']} with {len(batch['job_ids'])} jobs")

    if args.no_wait:
        return 0

    batch = poll_batch(base_url, batch["id"], batch_dir, args.poll_seconds)
    if args.download_artifacts:
        download_batch_artifacts(base_url, batch, batch_dir, uploads)

    print(f"[done] batch={batch['id']} status={batch['status']} results_dir={batch_dir}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        raise SystemExit(130)
