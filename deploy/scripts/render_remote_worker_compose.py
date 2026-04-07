#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(
        description="Render a generalized remote worker compose file for one-worker-per-GPU deployment."
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=root / "deploy" / "env" / "worker.remote.env",
        help="Path to the remote worker env file.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=root / "deploy" / ".generated" / "compose.worker.remote.generated.yml",
        help="Path to the generated compose file.",
    )
    return parser.parse_args()


def load_env_file(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        env[key] = value
    return env


def parse_gpu_ids(env: dict[str, str]) -> list[int]:
    raw = env.get("WORKER_GPU_IDS", "").strip()
    if raw:
        gpu_ids = [int(part.strip()) for part in raw.split(",") if part.strip()]
        if not gpu_ids:
            raise SystemExit("WORKER_GPU_IDS is set but empty.")
        return sorted(dict.fromkeys(gpu_ids))

    if env.get("WORKER_GPU_SLOT"):
        return [int(env["WORKER_GPU_SLOT"])]

    gpu_ids: set[int] = set()
    pattern = re.compile(r"^GPU(\d+)_(VISIBLE_DEVICE|SCRATCH_HOST_PATH)$")
    for key in env:
        match = pattern.match(key)
        if match:
            gpu_ids.add(int(match.group(1)))
    if gpu_ids:
        return sorted(gpu_ids)
    return [0]


def resolve_scratch_path(env: dict[str, str], gpu_id: int, *, single_gpu: bool) -> str:
    explicit_key = f"GPU{gpu_id}_SCRATCH_HOST_PATH"
    if env.get(explicit_key):
        return env[explicit_key]

    scratch_root = env.get("WORKER_SCRATCH_ROOT", "").strip()
    if scratch_root:
        return f"{scratch_root.rstrip('/')}/gpu{gpu_id}"

    if single_gpu and env.get("WORKER_SCRATCH_HOST_PATH"):
        return env["WORKER_SCRATCH_HOST_PATH"]

    raise SystemExit(
        f"Missing scratch path for GPU {gpu_id}. Set {explicit_key} or WORKER_SCRATCH_ROOT in the env file."
    )


def resolve_visible_device(env: dict[str, str], gpu_id: int, *, single_gpu: bool) -> str:
    explicit_key = f"GPU{gpu_id}_VISIBLE_DEVICE"
    if env.get(explicit_key):
        return env[explicit_key]

    if single_gpu and env.get("WORKER_VISIBLE_DEVICE"):
        return env["WORKER_VISIBLE_DEVICE"]

    return str(gpu_id)


def yaml_quote(value: object) -> str:
    return json.dumps(str(value))


def render_service(
    *,
    repo_root: Path,
    env_file: Path,
    env: dict[str, str],
    gpu_id: int,
    single_gpu: bool,
) -> list[str]:
    node_name = env["WORKER_NODE_NAME"]
    worker_id = f"{node_name}-gpu{gpu_id}"
    scratch_path = resolve_scratch_path(env, gpu_id, single_gpu=single_gpu)
    visible_device = resolve_visible_device(env, gpu_id, single_gpu=single_gpu)
    model_root = env["MODEL_ROOT"]
    arch_list = env.get("WORKER_TORCH_CUDA_ARCH_LIST", "7.5;8.0;8.6;8.9")

    lines = [
        f"  worker-gpu{gpu_id}:",
        f"    image: {yaml_quote(env.get('WORKER_IMAGE', 'gvhmr-batch-process-worker:latest'))}",
        "    build:",
        f"      context: {yaml_quote(str(repo_root))}",
        f"      dockerfile: {yaml_quote(str(repo_root / 'deploy' / 'docker' / 'worker.Dockerfile'))}",
        "      args:",
        f"        TORCH_CUDA_ARCH_LIST: {yaml_quote(arch_list)}",
        "    restart: unless-stopped",
        "    env_file:",
        f"      - {yaml_quote(str(env_file))}",
        "    environment:",
        f"      GVHMR_BATCH_WORKER_WORKER_ID: {yaml_quote(worker_id)}",
        f"      GVHMR_BATCH_WORKER_NODE_NAME: {yaml_quote(node_name)}",
        f"      GVHMR_BATCH_WORKER_GPU_SLOT: {gpu_id}",
        f"      NVIDIA_VISIBLE_DEVICES: {yaml_quote(visible_device)}",
        '      NVIDIA_DRIVER_CAPABILITIES: "compute,utility"',
        "    volumes:",
        "      - type: bind",
        f"        source: {yaml_quote(scratch_path)}",
        '        target: "/var/lib/gvhmr-batch-process"',
        "      - type: bind",
        f"        source: {yaml_quote(model_root)}",
        '        target: "/app/gvhmr/inputs/checkpoints"',
        "        read_only: true",
        "    gpus: all",
        "    healthcheck:",
        '      test: ["CMD", "python", "-m", "gvhmr_batch_worker.healthcheck"]',
        "      interval: 30s",
        "      timeout: 10s",
        "      retries: 3",
        "      start_period: 30s",
    ]
    return lines


def render_compose(*, repo_root: Path, env_file: Path, env: dict[str, str]) -> str:
    if not env.get("WORKER_NODE_NAME"):
        raise SystemExit("WORKER_NODE_NAME is required in the env file.")
    if not env.get("MODEL_ROOT"):
        raise SystemExit("MODEL_ROOT is required in the env file.")

    gpu_ids = parse_gpu_ids(env)
    single_gpu = len(gpu_ids) == 1

    lines = [
        "name: gvhmr-batch-worker-remote",
        "",
        "services:",
    ]
    for index, gpu_id in enumerate(gpu_ids):
        if index:
            lines.append("")
        lines.extend(
            render_service(
                repo_root=repo_root,
                env_file=env_file,
                env=env,
                gpu_id=gpu_id,
                single_gpu=single_gpu,
            )
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[2]
    env_file = args.env_file.resolve()
    output_path = args.output.resolve()

    if not env_file.exists():
        raise SystemExit(f"Env file does not exist: {env_file}")

    env = load_env_file(env_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        render_compose(repo_root=repo_root, env_file=env_file, env=env),
        encoding="utf-8",
    )
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
