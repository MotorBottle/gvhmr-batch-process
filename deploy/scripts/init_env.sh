#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_DIR="${ROOT_DIR}/deploy/env"
FORCE="${FORCE:-0}"

copy_example() {
  local example_path="$1"
  local target_path="${example_path%.example.env}.env"
  if [[ -f "${target_path}" && "${FORCE}" != "1" ]]; then
    echo "[skip] ${target_path} already exists"
    return
  fi
  cp "${example_path}" "${target_path}"
  echo "[init] ${target_path}"
}

shopt -s nullglob
for example_path in "${ENV_DIR}"/*.example.env; do
  copy_example "${example_path}"
done
