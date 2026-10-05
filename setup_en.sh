#!/usr/bin/env bash
set -Eeuo pipefail

# AI Professor Lite installer
#
# Flow:
#   1) Check Docker / NVIDIA GPU
#   2) Download official Ditto checkpoints to core/ditto-talkinghead/checkpoints
#   3) Create/update .env
#   4) Build Docker image from Dockerfile
#   5) Run container with fixed internal port 8002 and user-selected external port
#
# Host prerequisites:
#   - Linux
#   - Docker Engine
#   - NVIDIA driver (`nvidia-smi` works on host)
#   - NVIDIA Container Toolkit (`docker run --gpus ...` works)
#   - git + git-lfs (for official Ditto checkpoint download)

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

IMAGE_NAME="${IMAGE_NAME:-ai-prof-lite:latest}"
CONTAINER_NAME="${CONTAINER_NAME:-ai-prof-lite}"
INTERNAL_PORT=8002
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env}"
DEFAULT_DATA_DIR="$ROOT_DIR/data"
DATA_DIR="${DATA_DIR:-}"
DITTO_ROOT="$ROOT_DIR/core/ditto-talkinghead"
CHECKPOINT_DIR="$DITTO_ROOT/checkpoints"
DITTO_REPO="https://huggingface.co/digital-avatar/ditto-talkinghead"
DEFAULT_EXTERNAL_PORT=8002
DEFAULT_GPU_CAP=4

# Dockerfile non-root runtime identity. Keep these aligned with APP_UID/APP_GID there.
APP_UID="${APP_UID:-10001}"
APP_GID="${APP_GID:-10001}"

# Optional non-interactive overrides:
#   DATA_DIR=/u2a/ai-prof-lite-data ./setup_en.sh
#   EXTERNAL_PORT=18002 ./setup_en.sh
#   SETUP_OPENAI_KEY_MODE=user ./setup_en.sh
#   SETUP_JOB_CONCURRENCY=4 ./setup_en.sh
EXTERNAL_PORT="${EXTERNAL_PORT:-}"
SETUP_OPENAI_KEY_MODE="${SETUP_OPENAI_KEY_MODE:-}"
SETUP_JOB_CONCURRENCY="${SETUP_JOB_CONCURRENCY:-}"

BLUE='\033[1;34m'
GREEN='\033[1;32m'
YELLOW='\033[1;33m'
RED='\033[1;31m'
RESET='\033[0m'

log()  { printf "%b[setup]%b %s\n" "$BLUE" "$RESET" "$*"; }
ok()   { printf "%b[ OK ]%b %s\n" "$GREEN" "$RESET" "$*"; }
warn() { printf "%b[WARN]%b %s\n" "$YELLOW" "$RESET" "$*" >&2; }
die()  { printf "%b[FAIL]%b %s\n" "$RED" "$RESET" "$*" >&2; exit 1; }

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"
}

# Safe single-line KEY=VALUE updater.
set_env() {
  local key="$1"
  local value="$2"
  local file="$3"
  local tmp
  tmp="$(mktemp)"

  if [[ -f "$file" ]] && grep -qE "^${key}=" "$file"; then
    while IFS= read -r line || [[ -n "$line" ]]; do
      case "$line" in
        "${key}="*) printf '%s=%s\n' "$key" "$value" ;;
        *)           printf '%s\n' "$line" ;;
      esac
    done < "$file" > "$tmp"
  else
    [[ -f "$file" ]] && cat "$file" > "$tmp"
    printf '%s=%s\n' "$key" "$value" >> "$tmp"
  fi

  cat "$tmp" > "$file"
  rm -f "$tmp"
}

get_env() {
  local key="$1"
  local file="$2"
  [[ -f "$file" ]] || return 0
  grep -E "^${key}=" "$file" | tail -n1 | cut -d= -f2- || true
}

is_placeholder() {
  local value="$1"
  [[ -z "$value" || "$value" == replace-with-* ]]
}

prompt_value() {
  local prompt="$1"
  local default="$2"
  local result=""

  if [[ -t 0 ]]; then
    read -r -p "$prompt [$default]: " result
  fi

  printf '%s' "${result:-$default}"
}

validate_port() {
  local port="$1"
  [[ "$port" =~ ^[0-9]+$ ]] || die "Port must be numeric: $port"
  (( port >= 1 && port <= 65535 )) || die "Port is out of range: $port"
}

validate_positive_int() {
  local value="$1"
  [[ "$value" =~ ^[0-9]+$ ]] || return 1
  (( value >= 1 ))
}

cleanup_tmp=""
cleanup() {
  if [[ -n "$cleanup_tmp" && -d "$cleanup_tmp" ]]; then
    rm -rf "$cleanup_tmp"
  fi
}
trap cleanup EXIT

printf '\n'
printf '========================================\n'
printf ' AI Professor Lite Setup\n'
printf '========================================\n\n'

# -----------------------------------------------------------------------------
# 0. Project checks
# -----------------------------------------------------------------------------
[[ "$(uname -s)" == "Linux" ]] || die "This setup script currently targets Linux servers."
[[ -f "$ROOT_DIR/Dockerfile" ]] || die "Dockerfile not found: $ROOT_DIR/Dockerfile"
[[ -f "$ROOT_DIR/app.py" ]] || die "app.py not found: $ROOT_DIR/app.py"
[[ -f "$ROOT_DIR/.env.example" ]] || die ".env.example not found: $ROOT_DIR/.env.example"
[[ -f "$DITTO_ROOT/inference.py" ]] || die "Ditto source not found: $DITTO_ROOT/inference.py"

need_cmd docker
need_cmd nvidia-smi
need_cmd git
need_cmd openssl

docker info >/dev/null 2>&1 || die "Cannot access the Docker daemon. Make sure Docker is running."
nvidia-smi >/dev/null 2>&1 || die "nvidia-smi failed on the host. Check the NVIDIA driver first."

GPU_COUNT="$(nvidia-smi -L 2>/dev/null | grep -c '^GPU ' || true)"
[[ "$GPU_COUNT" =~ ^[0-9]+$ ]] || GPU_COUNT=0
(( GPU_COUNT > 0 )) || die "No NVIDIA GPU detected."
ok "Detected ${GPU_COUNT} NVIDIA GPU(s)"

# -----------------------------------------------------------------------------
# 1. External port
# -----------------------------------------------------------------------------
if [[ -z "$EXTERNAL_PORT" ]]; then
  SAVED_PORT="$(get_env AI_PROF_EXTERNAL_PORT "$ENV_FILE")"
  PORT_DEFAULT="${SAVED_PORT:-$DEFAULT_EXTERNAL_PORT}"
  EXTERNAL_PORT="$(prompt_value 'Enter the external port' "$PORT_DEFAULT")"
fi
validate_port "$EXTERNAL_PORT"
log "Port mapping: 0.0.0.0:${EXTERNAL_PORT} -> container:${INTERNAL_PORT}"

# -----------------------------------------------------------------------------
# 2. Download official Ditto checkpoints
# -----------------------------------------------------------------------------
if ! git lfs version >/dev/null 2>&1; then
  die "git-lfs is required. Ubuntu/Debian example: apt-get update && apt-get install -y git-lfs"
fi

DITTO_CFG_FILE="$CHECKPOINT_DIR/ditto_cfg/v0.4_hubert_cfg_trt.pkl"
DITTO_ENGINE_DIR="$CHECKPOINT_DIR/ditto_trt_Ampere_Plus"
DITTO_ENGINE_SENTINEL="$DITTO_ENGINE_DIR/lmdm_v0.4_hubert_fp32.engine"

if [[ -f "$DITTO_CFG_FILE" && -f "$DITTO_ENGINE_SENTINEL" ]]; then
  ok "Official Ditto checkpoints already exist. Skipping download."
else
  log "Downloading official Ditto checkpoints..."
  log "source: $DITTO_REPO"

  cleanup_tmp="$(mktemp -d)"
  GIT_LFS_SKIP_SMUDGE=1 git clone --depth 1 "$DITTO_REPO" "$cleanup_tmp/ditto-checkpoints"

  (
    cd "$cleanup_tmp/ditto-checkpoints"
    git lfs install --local >/dev/null
    git lfs pull --include="ditto_cfg/v0.4_hubert_cfg_trt.pkl,ditto_trt_Ampere_Plus/**"
  )

  mkdir -p "$CHECKPOINT_DIR/ditto_cfg" "$DITTO_ENGINE_DIR"
  cp -f "$cleanup_tmp/ditto-checkpoints/ditto_cfg/v0.4_hubert_cfg_trt.pkl" \
        "$CHECKPOINT_DIR/ditto_cfg/v0.4_hubert_cfg_trt.pkl"
  cp -a "$cleanup_tmp/ditto-checkpoints/ditto_trt_Ampere_Plus/." \
        "$DITTO_ENGINE_DIR/"

  [[ -f "$DITTO_CFG_FILE" ]] || die "Failed to download the Ditto cfg file."
  [[ -f "$DITTO_ENGINE_SENTINEL" ]] || die "Failed to download the Ditto TensorRT checkpoint."

  rm -rf "$cleanup_tmp"
  cleanup_tmp=""
  ok "Ditto checkpoint download complete: $CHECKPOINT_DIR"
fi

# Check for an LFS pointer accidentally left instead of the real binary.
if head -n1 "$DITTO_CFG_FILE" 2>/dev/null | grep -q 'git-lfs.github.com/spec'; then
  die "Ditto checkpoint is still a Git LFS pointer. The actual model file was not downloaded."
fi

# Checkpoint is mounted at runtime; do not send multi-GB model files into docker build context.
DOCKERIGNORE="$ROOT_DIR/.dockerignore"
touch "$DOCKERIGNORE"
if ! grep -qxF 'core/ditto-talkinghead/checkpoints/' "$DOCKERIGNORE"; then
  printf '\n# Ditto model files are mounted at runtime by setup.sh\ncore/ditto-talkinghead/checkpoints/\n' >> "$DOCKERIGNORE"
  ok "Added Ditto checkpoint exclusion rule to .dockerignore"
fi

# -----------------------------------------------------------------------------
# 3. .env setup
# -----------------------------------------------------------------------------
if [[ ! -f "$ENV_FILE" ]]; then
  cp "$ROOT_DIR/.env.example" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  ok "Created .env"
else
  ok "Using existing .env: $ENV_FILE"
fi

SESSION_SECRET="$(get_env SESSION_SECRET "$ENV_FILE")"
if is_placeholder "$SESSION_SECRET" || (( ${#SESSION_SECRET} < 32 )); then
  SESSION_SECRET="$(openssl rand -hex 48)"
  set_env SESSION_SECRET "$SESSION_SECRET" "$ENV_FILE"
  ok "Generated SESSION_SECRET automatically"
fi

CREDENTIAL_MASTER_KEY="$(get_env CREDENTIAL_MASTER_KEY "$ENV_FILE")"
if is_placeholder "$CREDENTIAL_MASTER_KEY"; then
  # Fernet-compatible urlsafe base64 encoding of 32 random bytes.
  CREDENTIAL_MASTER_KEY="$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '\n')"
  set_env CREDENTIAL_MASTER_KEY "$CREDENTIAL_MASTER_KEY" "$ENV_FILE"
  ok "Generated CREDENTIAL_MASTER_KEY automatically"
fi

# Save installer-only host port for convenient re-runs. The application itself ignores this key.
set_env AI_PROF_EXTERNAL_PORT "$EXTERNAL_PORT" "$ENV_FILE"

# OpenAI key policy.
CURRENT_OPENAI_MODE="$(get_env OPENAI_KEY_MODE "$ENV_FILE")"
if [[ -z "$SETUP_OPENAI_KEY_MODE" ]]; then
  SETUP_OPENAI_KEY_MODE="${CURRENT_OPENAI_MODE:-user}"
  if [[ -t 0 ]]; then
    if [[ "$SETUP_OPENAI_KEY_MODE" == "server" ]]; then
      OPENAI_DEFAULT_CHOICE=2
    else
      OPENAI_DEFAULT_CHOICE=1
    fi
    printf '\nSelect the OpenAI API key mode.\n'
    printf '  1) user   : Per-user BYOK (recommended default)\n'
    printf '  2) server : Shared server-side OpenAI API key\n'
    read -r -p "Select [$OPENAI_DEFAULT_CHOICE]: " OPENAI_CHOICE
    case "${OPENAI_CHOICE:-$OPENAI_DEFAULT_CHOICE}" in
      1|user)   SETUP_OPENAI_KEY_MODE="user" ;;
      2|server) SETUP_OPENAI_KEY_MODE="server" ;;
      *) die "Invalid OpenAI key mode selection." ;;
    esac
  fi
fi

case "$SETUP_OPENAI_KEY_MODE" in
  user)
    set_env OPENAI_KEY_MODE "user" "$ENV_FILE"
    set_env SERVER_OPENAI_API_KEY "" "$ENV_FILE"
    ok "OpenAI: per-user BYOK mode"
    ;;
  server)
    set_env OPENAI_KEY_MODE "server" "$ENV_FILE"
    SERVER_KEY="$(get_env SERVER_OPENAI_API_KEY "$ENV_FILE")"
    if [[ -t 0 ]]; then
      if [[ -n "$SERVER_KEY" ]]; then
        read -r -p "Keep the existing SERVER_OPENAI_API_KEY? [Y/n]: " KEEP_KEY
      else
        KEEP_KEY="n"
      fi

      case "${KEEP_KEY:-Y}" in
        n|N|no|NO)
          read -r -s -p "Enter SERVER_OPENAI_API_KEY: " SERVER_KEY
          printf '\n'
          ;;
      esac
    fi
    [[ -n "$SERVER_KEY" ]] || die "SERVER_OPENAI_API_KEY is required in server mode."
    set_env SERVER_OPENAI_API_KEY "$SERVER_KEY" "$ENV_FILE"
    ok "OpenAI: shared server key mode"
    ;;
  *)
    die "SETUP_OPENAI_KEY_MODE must be either user or server."
    ;;
esac

# GPU worker configuration. Default: min(number of GPUs, 4).
DEFAULT_JOB_CONCURRENCY="$GPU_COUNT"
if (( DEFAULT_JOB_CONCURRENCY > DEFAULT_GPU_CAP )); then
  DEFAULT_JOB_CONCURRENCY="$DEFAULT_GPU_CAP"
fi

if [[ -z "$SETUP_JOB_CONCURRENCY" ]]; then
  CURRENT_JOBS="$(get_env JOB_CONCURRENCY "$ENV_FILE")"
  JOB_DEFAULT="${CURRENT_JOBS:-$DEFAULT_JOB_CONCURRENCY}"
  SETUP_JOB_CONCURRENCY="$(prompt_value 'Number of concurrent GPU lecture jobs' "$JOB_DEFAULT")"
fi

validate_positive_int "$SETUP_JOB_CONCURRENCY" || die "JOB_CONCURRENCY must be an integer greater than or equal to 1."
(( SETUP_JOB_CONCURRENCY <= GPU_COUNT )) || die "JOB_CONCURRENCY(${SETUP_JOB_CONCURRENCY}) exceeds GPU_COUNT(${GPU_COUNT})."

GPU_IDS="$(seq -s, 0 $((SETUP_JOB_CONCURRENCY - 1)))"
set_env JOB_CONCURRENCY "$SETUP_JOB_CONCURRENCY" "$ENV_FILE"
set_env JOB_GPU_IDS "$GPU_IDS" "$ENV_FILE"
set_env DITTO_ROOT "core/ditto-talkinghead" "$ENV_FILE"
set_env DITTO_DATA_ROOT "core/ditto-talkinghead/checkpoints/ditto_trt_Ampere_Plus" "$ENV_FILE"
set_env DITTO_CFG_PKL "core/ditto-talkinghead/checkpoints/ditto_cfg/v0.4_hubert_cfg_trt.pkl" "$ENV_FILE"

ok "GPU workers: JOB_CONCURRENCY=$SETUP_JOB_CONCURRENCY / JOB_GPU_IDS=$GPU_IDS"

# -----------------------------------------------------------------------------
# 4. Persistent data directory
# -----------------------------------------------------------------------------
if [[ -z "$DATA_DIR" ]]; then
  DATA_DIR="$(prompt_value 'Host directory for persistent application data' "$DEFAULT_DATA_DIR")"
fi

mkdir -p "$DATA_DIR"
DATA_DIR="$(cd "$DATA_DIR" && pwd -P)"

ok "Persistent data directory: $DATA_DIR"

# -----------------------------------------------------------------------------
# 5. Docker build
# -----------------------------------------------------------------------------
log "Building Docker image: $IMAGE_NAME"
docker build -t "$IMAGE_NAME" "$ROOT_DIR"
ok "Docker build complete"

# Prepare bind-mounted data directory for the non-root application user.
#
# Preferred path:
#   - use a short-lived root container from the just-built image
#   - chown existing data to APP_UID:APP_GID
#   - keep permissions at 0775 instead of making the directory world-writable
#
# Fallback:
#   - if the filesystem/daemon does not allow chown (for example some
#     rootless/NFS setups), use chmod 0777 so the application can still start.
log "Preparing data directory permissions for container UID:GID ${APP_UID}:${APP_GID}..."
if docker run --rm \
    --user 0:0 \
    --entrypoint /bin/sh \
    -v "$DATA_DIR:/app/data" \
    "$IMAGE_NAME" \
    -c "chown -R ${APP_UID}:${APP_GID} /app/data && chmod 0775 /app/data"; then
  ok "Data directory ownership set to ${APP_UID}:${APP_GID} (mode 0775)"
else
  warn "Could not chown the data directory. Falling back to chmod 0777: $DATA_DIR"
  chmod 0777 "$DATA_DIR" || die "Failed to make the data directory writable: $DATA_DIR"
fi

# Verify NVIDIA Container Toolkit using the image we just built.
log "Checking Docker GPU passthrough..."
docker run --rm --gpus all --entrypoint nvidia-smi "$IMAGE_NAME" >/dev/null \
  || die "NVIDIA GPU is not available inside Docker. Check the NVIDIA Container Toolkit."
ok "Docker GPU passthrough OK"

# -----------------------------------------------------------------------------
# 6. Docker run - external port -> internal 8002
# -----------------------------------------------------------------------------
if docker container inspect "$CONTAINER_NAME" >/dev/null 2>&1; then
  die "Container already exists: $CONTAINER_NAME
Stop/remove it manually if you want to recreate it, then run setup_en.sh again."
fi

log "Starting container"
docker run -d \
  --name "$CONTAINER_NAME" \
  --restart unless-stopped \
  --gpus all \
  --env-file "$ENV_FILE" \
  -e APP_HOST=0.0.0.0 \
  -e APP_PORT="$INTERNAL_PORT" \
  -e DATA_DIR=/app/data \
  -p "${EXTERNAL_PORT}:${INTERNAL_PORT}" \
  -v "$DATA_DIR:/app/data" \
  -v "$CHECKPOINT_DIR:/app/core/ditto-talkinghead/checkpoints:ro" \
  "$IMAGE_NAME" >/dev/null

sleep 3

# A stale NVML state can occasionally be fixed by a container restart.
if ! docker exec "$CONTAINER_NAME" nvidia-smi >/dev/null 2>&1; then
  warn "NVML initialization failed inside the container. Restarting once."
  docker restart "$CONTAINER_NAME" >/dev/null
  sleep 3
fi

docker exec "$CONTAINER_NAME" nvidia-smi >/dev/null 2>&1 \
  || { docker logs --tail 100 "$CONTAINER_NAME" >&2 || true; die "nvidia-smi failed inside the container"; }
ok "Container NVIDIA GPU OK"

docker exec "$CONTAINER_NAME" /opt/conda/envs/runtime/bin/python -c \
  'import torch; assert torch.cuda.is_available(); print("CUDA devices:", torch.cuda.device_count())' \
  || { docker logs --tail 100 "$CONTAINER_NAME" >&2 || true; die "Ditto Python CUDA initialization failed"; }
ok "Ditto/PyTorch CUDA OK"

# -----------------------------------------------------------------------------
# 7. Simple readiness check
# -----------------------------------------------------------------------------
READY=0
if command -v curl >/dev/null 2>&1; then
  for _ in $(seq 1 30); do
    if curl -fsS -o /dev/null "http://127.0.0.1:${EXTERNAL_PORT}/"; then
      READY=1
      break
    fi

    if ! docker inspect -f '{{.State.Running}}' "$CONTAINER_NAME" 2>/dev/null | grep -q '^true$'; then
      break
    fi
    sleep 2
  done
fi

printf '\n========================================\n'
printf ' AI Professor Lite Setup Complete\n'
printf '========================================\n'
printf 'Container      : %s\n' "$CONTAINER_NAME"
printf 'Image          : %s\n' "$IMAGE_NAME"
printf 'Internal port  : %s\n' "$INTERNAL_PORT"
printf 'External port  : %s\n' "$EXTERNAL_PORT"
printf 'Local URL      : http://127.0.0.1:%s/\n' "$EXTERNAL_PORT"
printf 'Data           : %s\n' "$DATA_DIR"
printf 'Checkpoints    : %s\n' "$CHECKPOINT_DIR"
printf '\n'

if [[ "$READY" == "1" ]]; then
  ok "HTTP readiness check passed"
else
  warn "Could not verify HTTP readiness. Check the logs below."
fi

printf '\nUseful commands:\n'
printf '  docker logs -f %s\n' "$CONTAINER_NAME"
printf '  docker exec %s nvidia-smi\n' "$CONTAINER_NAME"
printf '  docker restart %s\n' "$CONTAINER_NAME"
printf '\n'
printf 'Note: This only configures Docker port mapping. UFW/cloud firewall rules may also need to allow external port %s.\n' "$EXTERNAL_PORT"
