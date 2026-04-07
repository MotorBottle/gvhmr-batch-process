#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${1:-deploy/env/worker.remote.env}"

info() {
  echo "[info] $*"
}

warn() {
  echo "[warn] $*" >&2
}

die() {
  echo "[error] $*" >&2
  exit 1
}

resolve_gpu_ids() {
  local ids=()
  if [[ -n "${WORKER_GPU_IDS:-}" ]]; then
    IFS=',' read -r -a ids <<<"${WORKER_GPU_IDS}"
  elif [[ -n "${WORKER_GPU_SLOT:-}" ]]; then
    ids=("${WORKER_GPU_SLOT}")
  else
    local name
    while IFS= read -r name; do
      ids+=("${name#GPU}")
      ids[-1]="${ids[-1]%%_*}"
    done < <(compgen -A variable | grep -E '^GPU[0-9]+_(VISIBLE_DEVICE|SCRATCH_HOST_PATH)$' || true)
  fi

  if [[ ${#ids[@]} -eq 0 ]]; then
    ids=("0")
  fi

  printf '%s\n' "${ids[@]}" | sed '/^$/d' | sort -n -u
}

resolve_scratch_path() {
  local gpu_id="$1"
  local explicit_key="GPU${gpu_id}_SCRATCH_HOST_PATH"
  local explicit_value="${!explicit_key:-}"
  if [[ -n "${explicit_value}" ]]; then
    echo "${explicit_value}"
    return
  fi

  if [[ -n "${WORKER_SCRATCH_ROOT:-}" ]]; then
    echo "${WORKER_SCRATCH_ROOT%/}/gpu${gpu_id}"
    return
  fi

  if [[ -n "${WORKER_SCRATCH_HOST_PATH:-}" ]]; then
    echo "${WORKER_SCRATCH_HOST_PATH}"
    return
  fi

  die "Missing scratch path for GPU ${gpu_id}. Set GPU${gpu_id}_SCRATCH_HOST_PATH or WORKER_SCRATCH_ROOT."
}

check_cmd() {
  local cmd="$1"
  command -v "$cmd" >/dev/null 2>&1 || die "Missing required command: $cmd"
}

check_tcp() {
  local host="$1"
  local port="$2"
  if ! timeout 3 bash -lc "</dev/tcp/${host}/${port}" >/dev/null 2>&1; then
    die "Cannot reach ${host}:${port}"
  fi
}

parse_host_port_from_dsn() {
  local dsn="$1"
  local default_port="$2"
  local without_scheme="${dsn#*://}"
  local host_and_rest="${without_scheme#*@}"
  local host_port="${host_and_rest%%/*}"
  local host="${host_port%%:*}"
  local port="${host_port##*:}"
  if [[ "$host_port" == "$host" ]]; then
    port="$default_port"
  fi
  echo "${host} ${port}"
}

parse_host_port_from_url() {
  local url="$1"
  local default_port="$2"
  local without_scheme="${url#*://}"
  local host_port_and_rest="${without_scheme%%/*}"
  local host="${host_port_and_rest%%:*}"
  local port="${host_port_and_rest##*:}"
  if [[ "$host_port_and_rest" == "$host" ]]; then
    port="$default_port"
  fi
  echo "${host} ${port}"
}

parse_host_port_from_endpoint() {
  local endpoint="$1"
  local default_port="$2"
  local host="${endpoint%%:*}"
  local port="${endpoint##*:}"
  if [[ "$endpoint" == "$host" ]]; then
    port="$default_port"
  fi
  echo "${host} ${port}"
}

[[ -f "$ENV_FILE" ]] || die "Env file not found: $ENV_FILE"

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

check_cmd docker
check_cmd nvidia-smi
check_cmd timeout

docker compose version >/dev/null 2>&1 || die "Docker Compose plugin is not available."
nvidia-smi -L >/dev/null 2>&1 || die "nvidia-smi failed. Check driver/runtime installation."

[[ -n "${MODEL_ROOT:-}" ]] || die "MODEL_ROOT is not set."
[[ -n "${GVHMR_BATCH_WORKER_POSTGRES_DSN:-}" ]] || die "GVHMR_BATCH_WORKER_POSTGRES_DSN is not set."
[[ -n "${GVHMR_BATCH_WORKER_REDIS_URL:-}" ]] || die "GVHMR_BATCH_WORKER_REDIS_URL is not set."
[[ -n "${GVHMR_BATCH_WORKER_MINIO_ENDPOINT:-}" ]] || die "GVHMR_BATCH_WORKER_MINIO_ENDPOINT is not set."
[[ -d "${MODEL_ROOT}" ]] || die "MODEL_ROOT does not exist: ${MODEL_ROOT}"
[[ -n "${WORKER_NODE_NAME:-}" ]] || die "WORKER_NODE_NAME is not set."

mapfile -t gpu_ids < <(resolve_gpu_ids)
[[ ${#gpu_ids[@]} -gt 0 ]] || die "No GPU IDs resolved from WORKER_GPU_IDS / WORKER_GPU_SLOT."

available_gpu_ids="$(nvidia-smi --query-gpu=index --format=csv,noheader 2>/dev/null | tr -d ' ' || true)"
for gpu_id in "${gpu_ids[@]}"; do
  grep -qx "${gpu_id}" <<<"${available_gpu_ids}" || die "Requested GPU ${gpu_id} is not available on this host."
  mkdir -p "$(resolve_scratch_path "${gpu_id}")"
done

read -r pg_host pg_port <<<"$(parse_host_port_from_dsn "${GVHMR_BATCH_WORKER_POSTGRES_DSN}" "5432")"
read -r redis_host redis_port <<<"$(parse_host_port_from_url "${GVHMR_BATCH_WORKER_REDIS_URL}" "6379")"
read -r minio_host minio_port <<<"$(parse_host_port_from_endpoint "${GVHMR_BATCH_WORKER_MINIO_ENDPOINT}" "9000")"

check_tcp "${pg_host}" "${pg_port}"
check_tcp "${redis_host}" "${redis_port}"
check_tcp "${minio_host}" "${minio_port}"

if command -v timedatectl >/dev/null 2>&1; then
  ntp_sync="$(timedatectl show -p NTPSynchronized --value 2>/dev/null || true)"
  if [[ "${ntp_sync}" != "yes" ]]; then
    die "Host NTP is not synchronized. Fix time sync before starting remote workers."
  fi
  info "NTP synchronized according to timedatectl."
elif command -v chronyc >/dev/null 2>&1; then
  if ! chronyc tracking 2>/dev/null | grep -q "Leap status[[:space:]]*:[[:space:]]*Normal"; then
    die "chrony is installed but reports unhealthy tracking."
  fi
  info "NTP synchronized according to chrony."
else
  warn "Unable to verify host time sync automatically. Install systemd-timesyncd or chrony."
fi

info "GPU layout: ${gpu_ids[*]}"
info "Docker, GPU runtime, model path, scratch paths, network reachability, and time sync checks passed."
