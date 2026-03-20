from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import time
import uuid
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


def save_json(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


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


def download_batch_artifacts(base_url: str, batch: dict, batch_dir: Path) -> None:
    for job_id in batch["job_ids"]:
        job_dir = batch_dir / job_id
        job = request_json("GET", f"{base_url.rstrip('/')}/jobs/{job_id}")
        artifacts = request_json("GET", f"{base_url.rstrip('/')}/jobs/{job_id}/artifacts")

        save_json(job_dir / "job.json", job)
        save_json(job_dir / "artifacts.json", artifacts)

        for artifact in artifacts:
            artifact_path = job_dir / artifact["kind"] / artifact["filename"]
            download_file(f"{base_url.rstrip('/')}/artifacts/{artifact['id']}/download", artifact_path)
            print(f"[artifact] job={job_id} saved={artifact_path}")


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
        uploads.append({"source_path": str(video_path), "upload": upload})
        print(f"[upload] {video_path.name} -> {upload['id']}")

    batch_name = args.batch_name or f"test-batch-{time.strftime('%Y%m%d-%H%M%S')}"
    batch_request = {
        "name": batch_name,
        "items": [
            {
                "upload_id": item["upload"]["id"],
                "static_camera": args.static_camera,
                "video_render": args.video_render,
                "video_type": args.video_type,
                "f_mm": args.f_mm,
                "priority": args.priority,
            }
            for item in uploads
        ],
    }

    batch = request_json("POST", f"{base_url}/batches", payload=batch_request)
    batch_dir = results_root / batch["id"]
    batch_dir.mkdir(parents=True, exist_ok=True)

    save_json(batch_dir / "uploads.json", uploads)
    save_json(batch_dir / "batch_request.json", batch_request)
    save_json(batch_dir / "batch_created.json", batch)
    print(f"[batch] created {batch['id']} with {len(batch['job_ids'])} jobs")

    if args.no_wait:
        return 0

    batch = poll_batch(base_url, batch["id"], batch_dir, args.poll_seconds)
    if args.download_artifacts:
        download_batch_artifacts(base_url, batch, batch_dir)

    print(f"[done] batch={batch['id']} status={batch['status']} results_dir={batch_dir}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        raise SystemExit(130)
