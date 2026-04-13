from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
from pathlib import Path

import numpy as np
import torch


DEFAULT_RESULTS_DIR = Path(__file__).resolve().parent / "results"
DEFAULT_OUTPUT_DIR_NAME = "ouput"
TERMINAL_SUCCESS_STATUS = "succeeded"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Convert all succeeded GVHMR batch outputs (hmr4d_results.pt) into "
            "SMPL-X body-only NPZ files with 10D betas."
        )
    )
    parser.add_argument(
        "batch_dir",
        type=Path,
        help="Path to a downloaded batch result directory, e.g. test/results/<timestamp>__<batch_id>/",
    )
    parser.add_argument(
        "--output-dir-name",
        default=DEFAULT_OUTPUT_DIR_NAME,
        help=f"Output directory name created under the batch directory. Default: {DEFAULT_OUTPUT_DIR_NAME}",
    )
    parser.add_argument(
        "--betas-agg",
        choices=["median", "mean"],
        default="median",
        help="How to aggregate frame-wise 10D betas into a sequence-level 10D vector.",
    )
    parser.add_argument(
        "--default-fps",
        type=float,
        default=30.0,
        help="Fallback mocap_frame_rate when video FPS cannot be inferred locally.",
    )
    return parser.parse_args()


def load_json(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def safe_label(value: str | None) -> str:
    if not value:
        return "unknown"
    cleaned = value.replace("/", "_").replace("\\", "_").replace(" ", "_")
    return "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in cleaned).strip("._") or "unknown"


def resolve_result_dir(batch_dir: Path, item: dict) -> Path:
    raw_result_dir = item.get("result_dir")
    if raw_result_dir:
        result_dir = Path(raw_result_dir)
        if result_dir.exists():
            return result_dir

    result_group = item.get("result_group")
    result_dir_name = item.get("result_dir_name")
    if result_group and result_dir_name:
        candidate = batch_dir / result_group / result_dir_name
        if candidate.exists():
            return candidate

    if result_dir_name:
        legacy_candidate = batch_dir / result_dir_name
        if legacy_candidate.exists():
            return legacy_candidate

    if raw_result_dir:
        return Path(raw_result_dir)
    if result_group and result_dir_name:
        return batch_dir / result_group / result_dir_name
    if result_dir_name:
        return batch_dir / result_dir_name
    return batch_dir


def parse_source_fps(value) -> float | None:
    if value in {None, ""}:
        return None
    try:
        fps = float(value)
    except (TypeError, ValueError):
        return None
    if math.isfinite(fps) and fps > 0:
        return fps
    return None


def infer_video_fps(video_path: Path, default_fps: float) -> float:
    ffprobe = shutil_which("ffprobe")
    if ffprobe is None or not video_path.exists():
        return float(default_fps)

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
        str(video_path),
    ]
    try:
        output = subprocess.check_output(command, text=True, stderr=subprocess.DEVNULL).strip().splitlines()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return float(default_fps)

    for value in output:
        fps = parse_ffprobe_rate(value)
        if fps and fps > 0:
            return fps
    return float(default_fps)


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


def shutil_which(command: str) -> str | None:
    try:
        from shutil import which

        return which(command)
    except Exception:
        return None


def aggregate_betas(frame_betas: np.ndarray, method: str) -> np.ndarray:
    if frame_betas.ndim != 2 or frame_betas.shape[1] != 10:
        raise ValueError(f"Expected frame-wise betas with shape (F, 10), got {frame_betas.shape}")
    if method == "median":
        return np.median(frame_betas, axis=0).astype(np.float32)
    return np.mean(frame_betas, axis=0).astype(np.float32)


def convert_pt_to_npz_payload(pt_path: Path, fps: float, betas_agg: str) -> dict[str, np.ndarray]:
    data = torch.load(pt_path, map_location="cpu", weights_only=False)
    global_params = data["smpl_params_global"]

    root_orient = np.asarray(global_params["global_orient"], dtype=np.float32)
    pose_body = np.asarray(global_params["body_pose"], dtype=np.float32)
    trans = np.asarray(global_params["transl"], dtype=np.float32)
    frame_betas = np.asarray(global_params["betas"], dtype=np.float32)

    if root_orient.ndim != 2 or root_orient.shape[1] != 3:
        raise ValueError(f"Unexpected global_orient shape: {root_orient.shape}")
    if pose_body.ndim != 2 or pose_body.shape[1] != 63:
        raise ValueError(f"Unexpected body_pose shape: {pose_body.shape}")
    if trans.ndim != 2 or trans.shape[1] != 3:
        raise ValueError(f"Unexpected transl shape: {trans.shape}")

    num_frames = root_orient.shape[0]
    poses = np.zeros((num_frames, 22, 3), dtype=np.float32)
    poses[:, 0, :] = root_orient
    poses[:, 1:, :] = pose_body.reshape(num_frames, 21, 3)

    betas = aggregate_betas(frame_betas, betas_agg)

    return {
        "model_type": np.array("smplx", dtype=np.str_),
        "pose_rep": np.array("body_only", dtype=np.str_),
        "coordinate_system": np.array("world_y_up", dtype=np.str_),
        "betas_source": np.array(f"gvhmr_sequence_{betas_agg}_10d", dtype=np.str_),
        "gender": np.array("neutral", dtype=np.str_),
        "num_betas": np.array(10, dtype=np.int32),
        "num_pose_joints": np.array(22, dtype=np.int32),
        "mocap_frame_rate": np.array(float(fps), dtype=np.float32),
        "betas": betas,
        "root_orient": root_orient,
        "pose_body": pose_body,
        "poses": poses,
        "trans": trans,
    }


def build_readme_text(batch_dir: Path, output_dir_name: str, rows: list[dict[str, str]], betas_agg: str, default_fps: float) -> str:
    succeeded = sum(1 for row in rows if row["status"] == TERMINAL_SUCCESS_STATUS)
    lines = [
        "# NPZ Export",
        "",
        f"- Source batch: `{batch_dir.name}`",
        f"- Output directory: `{output_dir_name}/`",
        f"- Converted jobs: `{succeeded}`",
        "- Export schema: `SMPL-X body-only`",
        "- Coordinate system: `world_y_up`",
        "- Betas: sequence-level `10D`, aggregated from frame-wise GVHMR betas",
        f"- Beta aggregation: `{betas_agg}`",
        "- Pose packing: `poses` has shape `(F, 22, 3)`",
        "- `poses[:, 0, :] == root_orient`",
        "- `poses[:, 1:, :] == pose_body.reshape(F, 21, 3)`",
        f"- `mocap_frame_rate` is inferred from the downloaded input video when `ffprobe` is available; otherwise defaults to `{default_fps}`",
        "",
        "## NPZ Fields",
        "",
        "- `model_type`: string, always `smplx`",
        "- `pose_rep`: string, always `body_only`",
        "- `coordinate_system`: string, always `world_y_up`",
        "- `betas_source`: string, records how 10D betas were aggregated",
        "- `gender`: string, currently `neutral`",
        "- `num_betas`: int, always `10`",
        "- `num_pose_joints`: int, always `22`",
        "- `mocap_frame_rate`: float32",
        "- `betas`: `(10,)` float32",
        "- `root_orient`: `(F, 3)` float32",
        "- `pose_body`: `(F, 63)` float32",
        "- `poses`: `(F, 22, 3)` float32",
        "- `trans`: `(F, 3)` float32",
        "",
        "## Files",
        "",
        "- `index.csv`: one row per converted job",
        "- `index.json`: same information in JSON",
        "- `<job_id>__<video_stem>.npz`: converted sequence data",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    batch_dir = args.batch_dir.resolve()
    if not batch_dir.exists():
        raise SystemExit(f"Batch directory does not exist: {batch_dir}")

    job_index_path = batch_dir / "job_index.json"
    if not job_index_path.exists():
        raise SystemExit(f"Missing job index: {job_index_path}")

    job_index = load_json(job_index_path)
    if not isinstance(job_index, list):
        raise SystemExit(f"Expected a list in {job_index_path}")

    output_dir = batch_dir / args.output_dir_name
    output_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, str]] = []
    converted_count = 0

    for item in job_index:
        job_id = item["job_id"]
        result_dir = resolve_result_dir(batch_dir, item)
        job_json_path = result_dir / "job.json"
        pt_path = result_dir / "hmr4d_results" / "hmr4d_results.pt"
        video_filename = item.get("upload_filename") or "unknown.mp4"
        video_stem = safe_label(Path(video_filename).stem)
        npz_name = f"{job_id}__{video_stem}.npz"
        npz_path = output_dir / npz_name

        status = "unknown"
        fps = float(args.default_fps)
        note = ""

        if job_json_path.exists():
            job = load_json(job_json_path)
            if isinstance(job, dict):
                status = job.get("status", status)

        source_fps = parse_source_fps(item.get("source_fps"))
        if source_fps is not None:
            fps = source_fps
        else:
            source_path = item.get("source_path")
            if source_path:
                source_path_obj = Path(source_path)
                if source_path_obj.exists():
                    fps = infer_video_fps(source_path_obj, default_fps=args.default_fps)
                else:
                    input_video_candidates = sorted((result_dir / "input_video").glob("*"))
                    if input_video_candidates:
                        fps = infer_video_fps(input_video_candidates[0], default_fps=args.default_fps)
            else:
                input_video_candidates = sorted((result_dir / "input_video").glob("*"))
                if input_video_candidates:
                    fps = infer_video_fps(input_video_candidates[0], default_fps=args.default_fps)

        if status == TERMINAL_SUCCESS_STATUS and pt_path.exists():
            payload = convert_pt_to_npz_payload(pt_path, fps=fps, betas_agg=args.betas_agg)
            np.savez_compressed(npz_path, **payload)
            converted_count += 1
        else:
            note = "skipped_non_succeeded_or_missing_pt"

        rows.append(
            {
                "job_id": job_id,
                "status": status,
                "upload_filename": video_filename,
                "source_path": item.get("source_path") or "",
                "result_dir_name": item.get("result_dir_name") or result_dir.name,
                "pt_path": str(pt_path.relative_to(batch_dir)) if pt_path.exists() else "",
                "npz_path": str(npz_path.relative_to(batch_dir)) if npz_path.exists() else "",
                "fps": f"{fps:.6f}",
                "betas_agg": args.betas_agg,
                "note": note,
            }
        )

    index_json_path = output_dir / "index.json"
    index_csv_path = output_dir / "index.csv"
    readme_path = output_dir / "README.md"

    index_json_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    with index_csv_path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(
            fp,
            fieldnames=[
                "job_id",
                "status",
                "upload_filename",
                "source_path",
                "result_dir_name",
                "pt_path",
                "npz_path",
                "fps",
                "betas_agg",
                "note",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    readme_path.write_text(
        build_readme_text(
            batch_dir=batch_dir,
            output_dir_name=args.output_dir_name,
            rows=rows,
            betas_agg=args.betas_agg,
            default_fps=args.default_fps,
        ),
        encoding="utf-8",
    )

    print(f"[export] batch={batch_dir.name} converted={converted_count} output_dir={output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
