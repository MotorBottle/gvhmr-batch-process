from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import mimetypes
import os
import subprocess
import sys
import time
from typing import Callable

from gvhmr_runner.cache import build_core_cache_key, build_render_cache_key, normalize_video_type


@dataclass(slots=True)
class RunnerJobSpec:
    upload_id: str
    video_sha256: str
    static_camera: bool = True
    use_dpvo: bool = False
    video_render: bool = False
    video_type: str = "none"
    f_mm: int | None = None
    upstream_version: str = "unbound"


@dataclass(slots=True)
class RunnerPlan:
    core_cache_key: str
    render_cache_key: str
    expected_artifacts: list[str]


@dataclass(slots=True)
class RunnerArtifact:
    kind: str
    file_path: Path
    subdir: str
    content_type: str


@dataclass(slots=True)
class RunnerExecutionResult:
    artifacts: list[RunnerArtifact]
    log_file: Path
    output_root: Path


class RunnerCancelled(RuntimeError):
    pass


class GVHMRRunner:
    def __init__(
        self,
        upstream_version: str = "unbound",
        *,
        gvhmr_root: Path | None = None,
        runner_entry_module: str = "gvhmr_runner.bridge.demo_with_skeleton",
        python_executable: str | None = None,
    ) -> None:
        self.upstream_version = upstream_version
        self.gvhmr_root = Path(gvhmr_root or "/app/gvhmr")
        self.runner_entry_module = runner_entry_module
        self.python_executable = python_executable or sys.executable

    def plan(self, spec: RunnerJobSpec) -> RunnerPlan:
        core_key = build_core_cache_key(
            video_sha256=spec.video_sha256,
            static_camera=spec.static_camera,
            use_dpvo=spec.use_dpvo,
            f_mm=spec.f_mm,
            upstream_version=spec.upstream_version or self.upstream_version,
        )
        render_key = build_render_cache_key(
            core_cache_key=core_key,
            video_render=spec.video_render,
            video_type=spec.video_type,
        )

        artifacts = ["hmr4d_results.pt", "runner.log"]
        normalized_type = normalize_video_type(spec.video_type)
        if spec.video_render and normalized_type not in {"none", ""}:
            artifacts.append("render_outputs")

        return RunnerPlan(
            core_cache_key=core_key,
            render_cache_key=render_key,
            expected_artifacts=artifacts,
        )

    def run(
        self,
        spec: RunnerJobSpec,
        *,
        input_video_path: Path,
        workdir: Path,
        timeout_seconds: int = 3600,
        is_cancel_requested: Callable[[], bool] | None = None,
    ) -> RunnerExecutionResult:
        return self.run_real(
            spec,
            input_video_path=input_video_path,
            workdir=workdir,
            timeout_seconds=timeout_seconds,
            is_cancel_requested=is_cancel_requested,
        )

    def run_real(
        self,
        spec: RunnerJobSpec,
        *,
        input_video_path: Path,
        workdir: Path,
        timeout_seconds: int = 3600,
        is_cancel_requested: Callable[[], bool] | None = None,
    ) -> RunnerExecutionResult:
        workdir.mkdir(parents=True, exist_ok=True)
        output_root = workdir / "gvhmr_output"
        output_root.mkdir(parents=True, exist_ok=True)
        log_path = workdir / "runner.log"

        if not self.gvhmr_root.exists():
            raise FileNotFoundError(f"GVHMR root not found: {self.gvhmr_root}")
        if not input_video_path.exists():
            raise FileNotFoundError(f"Input video not found: {input_video_path}")

        command = [
            self.python_executable,
            "-m",
            self.runner_entry_module,
            f"--video={input_video_path}",
            f"--output_root={output_root}",
            f"--video_render={'true' if spec.video_render else 'false'}",
        ]
        if spec.static_camera:
            command.append("-s")
        elif spec.use_dpvo:
            command.append("--use_dpvo")
        if spec.f_mm is not None:
            command.append(f"--f_mm={spec.f_mm}")

        normalized_type = normalize_video_type(spec.video_type)
        if spec.video_render and normalized_type not in {"", "none"}:
            command.append(f"--video_type={normalized_type}")

        with log_path.open("w", encoding="utf-8") as log_fp:
            log_fp.write(f"[Runner] mode=real\n")
            log_fp.write(f"[Runner] gvhmr_root={self.gvhmr_root}\n")
            log_fp.write(f"[Runner] runner_entry_module={self.runner_entry_module}\n")
            log_fp.write(f"[Runner] command={' '.join(command)}\n")
            log_fp.flush()

            started_at = time.monotonic()
            process_env = os.environ.copy()
            process_env["GVHMR_ROOT"] = str(self.gvhmr_root)
            process = subprocess.Popen(
                command,
                cwd=str(self.gvhmr_root),
                env=process_env,
                stdout=log_fp,
                stderr=subprocess.STDOUT,
                text=True,
            )

            while True:
                return_code = process.poll()
                if return_code is not None:
                    break

                if is_cancel_requested and is_cancel_requested():
                    log_fp.write("[Runner] cancel requested, terminating GVHMR subprocess.\n")
                    log_fp.flush()
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                    raise RunnerCancelled("Job canceled during GVHMR execution.")

                if time.monotonic() - started_at > timeout_seconds:
                    log_fp.write("[Runner] timeout exceeded, terminating GVHMR subprocess.\n")
                    log_fp.flush()
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                    raise TimeoutError(f"GVHMR runner timed out after {timeout_seconds} seconds.")

                time.sleep(1)

        if return_code != 0:
            raise RuntimeError(f"GVHMR runner exited with code {return_code}. See runner.log for details.")

        artifacts = self._discover_real_artifacts(output_root)
        artifacts.append(
            RunnerArtifact(
                kind="log",
                file_path=log_path,
                subdir="logs",
                content_type="text/plain",
            )
        )

        if not any(artifact.kind == "hmr4d_results" for artifact in artifacts):
            raise RuntimeError("GVHMR runner finished but did not produce hmr4d_results.pt.")

        return RunnerExecutionResult(
            artifacts=artifacts,
            log_file=log_path,
            output_root=output_root,
        )

    def run_mock(
        self,
        spec: RunnerJobSpec,
        *,
        workdir: Path,
        duration_seconds: int = 5,
        should_fail: bool = False,
        is_cancel_requested: Callable[[], bool] | None = None,
    ) -> RunnerExecutionResult:
        workdir.mkdir(parents=True, exist_ok=True)
        result_path = workdir / "hmr4d_results.mock.json"
        log_path = workdir / "runner.log"
        plan = self.plan(spec)

        with log_path.open("w", encoding="utf-8") as log_fp:
            log_fp.write(f"[MockRunner] upload_id={spec.upload_id}\n")
            log_fp.write(f"[MockRunner] core_cache_key={plan.core_cache_key}\n")
            log_fp.write(f"[MockRunner] render_cache_key={plan.render_cache_key}\n")
            log_fp.flush()

            for step in range(duration_seconds):
                if is_cancel_requested and is_cancel_requested():
                    log_fp.write("[MockRunner] cancel requested, stopping execution.\n")
                    log_fp.flush()
                    raise RunnerCancelled("Job canceled during mock execution.")
                log_fp.write(f"[MockRunner] processing step={step + 1}/{duration_seconds}\n")
                log_fp.flush()
                time.sleep(1)

            if should_fail:
                log_fp.write("[MockRunner] fail flag enabled, raising error.\n")
                log_fp.flush()
                raise RuntimeError("Mock runner failure requested by configuration.")

        result_payload = {
            "upload_id": spec.upload_id,
            "video_sha256": spec.video_sha256,
            "static_camera": spec.static_camera,
            "video_render": spec.video_render,
            "video_type": normalize_video_type(spec.video_type),
            "f_mm": spec.f_mm,
            "upstream_version": spec.upstream_version,
            "core_cache_key": plan.core_cache_key,
            "render_cache_key": plan.render_cache_key,
            "expected_artifacts": plan.expected_artifacts,
            "mode": "mock",
        }
        result_path.write_text(json.dumps(result_payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return RunnerExecutionResult(
            artifacts=[
                RunnerArtifact(
                    kind="hmr4d_results",
                    file_path=result_path,
                    subdir="results",
                    content_type="application/json",
                ),
                RunnerArtifact(
                    kind="log",
                    file_path=log_path,
                    subdir="logs",
                    content_type="text/plain",
                ),
            ],
            log_file=log_path,
            output_root=workdir,
        )

    def _discover_real_artifacts(self, output_root: Path) -> list[RunnerArtifact]:
        artifacts: list[RunnerArtifact] = []
        for file_path in sorted(path for path in output_root.rglob("*") if path.is_file()):
            artifact = self._classify_artifact(file_path)
            if artifact is not None:
                artifacts.append(artifact)
        return artifacts

    def _classify_artifact(self, file_path: Path) -> RunnerArtifact | None:
        filename = file_path.name
        suffix = file_path.suffix.lower()
        content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"

        if filename == "hmr4d_results.pt":
            return RunnerArtifact("hmr4d_results", file_path, "results", "application/octet-stream")
        if suffix == ".pt":
            return RunnerArtifact("preprocess", file_path, "preprocess", "application/octet-stream")
        if filename == "joints.json":
            return RunnerArtifact("joints_json", file_path, "results", "application/json")
        if suffix == ".mp4":
            if filename == "input.mp4":
                return RunnerArtifact("input_video", file_path, "videos", "video/mp4")
            return RunnerArtifact("render_video", file_path, "videos", "video/mp4")
        if suffix == ".zip":
            return RunnerArtifact("archive", file_path, "archives", "application/zip")
        if suffix in {".json", ".txt", ".log"}:
            return RunnerArtifact("log", file_path, "logs", content_type)
        return None
