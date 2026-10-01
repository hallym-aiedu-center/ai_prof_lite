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
#   DATA_DIR=/u2a/ai-prof-lite-data ./setup.sh
#   EXTERNAL_PORT=18002 ./setup.sh
#   SETUP_OPENAI_KEY_MODE=user ./setup.sh
#   SETUP_JOB_CONCURRENCY=4 ./setup.sh
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
  command -v "$1" >/dev/null 2>&1 || die "필수 명령이 없습니다: $1"
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
  [[ "$port" =~ ^[0-9]+$ ]] || die "포트는 숫자여야 합니다: $port"
  (( port >= 1 && port <= 65535 )) || die "포트 범위가 잘못되었습니다: $port"
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
[[ "$(uname -s)" == "Linux" ]] || die "현재 setup.sh는 Linux 서버를 대상으로 합니다."
[[ -f "$ROOT_DIR/Dockerfile" ]] || die "Dockerfile을 찾을 수 없습니다: $ROOT_DIR/Dockerfile"
[[ -f "$ROOT_DIR/app.py" ]] || die "app.py를 찾을 수 없습니다: $ROOT_DIR/app.py"
[[ -f "$ROOT_DIR/.env.example" ]] || die ".env.example을 찾을 수 없습니다: $ROOT_DIR/.env.example"
[[ -f "$DITTO_ROOT/inference.py" ]] || die "Ditto source를 찾을 수 없습니다: $DITTO_ROOT/inference.py"

need_cmd docker
need_cmd nvidia-smi
need_cmd git
need_cmd openssl

docker info >/dev/null 2>&1 || die "Docker daemon에 접근할 수 없습니다. Docker가 실행 중인지 확인하세요."
nvidia-smi >/dev/null 2>&1 || die "호스트에서 nvidia-smi가 실패합니다. NVIDIA driver를 먼저 확인하세요."

GPU_COUNT="$(nvidia-smi -L 2>/dev/null | grep -c '^GPU ' || true)"
[[ "$GPU_COUNT" =~ ^[0-9]+$ ]] || GPU_COUNT=0
(( GPU_COUNT > 0 )) || die "NVIDIA GPU를 찾지 못했습니다."
ok "NVIDIA GPU ${GPU_COUNT}개 확인"

# -----------------------------------------------------------------------------
# 1. External port
# -----------------------------------------------------------------------------
if [[ -z "$EXTERNAL_PORT" ]]; then
  SAVED_PORT="$(get_env AI_PROF_EXTERNAL_PORT "$ENV_FILE")"
  PORT_DEFAULT="${SAVED_PORT:-$DEFAULT_EXTERNAL_PORT}"
  EXTERNAL_PORT="$(prompt_value '외부에서 접속할 포트를 입력하세요' "$PORT_DEFAULT")"
fi
validate_port "$EXTERNAL_PORT"
log "포트 매핑: 0.0.0.0:${EXTERNAL_PORT} -> container:${INTERNAL_PORT}"

# -----------------------------------------------------------------------------
# 2. Download official Ditto checkpoints
# -----------------------------------------------------------------------------
if ! git lfs version >/dev/null 2>&1; then
  die "git-lfs가 필요합니다. Ubuntu/Debian 예: apt-get update && apt-get install -y git-lfs"
fi

DITTO_CFG_FILE="$CHECKPOINT_DIR/ditto_cfg/v0.4_hubert_cfg_trt.pkl"
DITTO_ENGINE_DIR="$CHECKPOINT_DIR/ditto_trt_Ampere_Plus"
DITTO_ENGINE_SENTINEL="$DITTO_ENGINE_DIR/lmdm_v0.4_hubert_fp32.engine"

if [[ -f "$DITTO_CFG_FILE" && -f "$DITTO_ENGINE_SENTINEL" ]]; then
  ok "Ditto 공식 checkpoint가 이미 존재합니다. 다운로드를 건너뜁니다."
else
  log "Ditto 공식 checkpoint 다운로드 중..."
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

  [[ -f "$DITTO_CFG_FILE" ]] || die "Ditto cfg 다운로드에 실패했습니다."
  [[ -f "$DITTO_ENGINE_SENTINEL" ]] || die "Ditto TensorRT checkpoint 다운로드에 실패했습니다."

  rm -rf "$cleanup_tmp"
  cleanup_tmp=""
  ok "Ditto checkpoint 다운로드 완료: $CHECKPOINT_DIR"
fi

# Check for an LFS pointer accidentally left instead of the real binary.
if head -n1 "$DITTO_CFG_FILE" 2>/dev/null | grep -q 'git-lfs.github.com/spec'; then
  die "Ditto checkpoint가 Git LFS pointer 상태입니다. 실제 모델 파일 다운로드에 실패했습니다."
fi

# Checkpoint is mounted at runtime; do not send multi-GB model files into docker build context.
DOCKERIGNORE="$ROOT_DIR/.dockerignore"
touch "$DOCKERIGNORE"
if ! grep -qxF 'core/ditto-talkinghead/checkpoints/' "$DOCKERIGNORE"; then
  printf '\n# Ditto model files are mounted at runtime by setup.sh\ncore/ditto-talkinghead/checkpoints/\n' >> "$DOCKERIGNORE"
  ok ".dockerignore에 Ditto checkpoint 제외 규칙 추가"
fi

# -----------------------------------------------------------------------------
# 3. .env setup
# -----------------------------------------------------------------------------
if [[ ! -f "$ENV_FILE" ]]; then
  cp "$ROOT_DIR/.env.example" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  ok ".env 생성"
else
  ok "기존 .env 사용: $ENV_FILE"
fi

SESSION_SECRET="$(get_env SESSION_SECRET "$ENV_FILE")"
if is_placeholder "$SESSION_SECRET" || (( ${#SESSION_SECRET} < 32 )); then
  SESSION_SECRET="$(openssl rand -hex 48)"
  set_env SESSION_SECRET "$SESSION_SECRET" "$ENV_FILE"
  ok "SESSION_SECRET 자동 생성"
fi

CREDENTIAL_MASTER_KEY="$(get_env CREDENTIAL_MASTER_KEY "$ENV_FILE")"
if is_placeholder "$CREDENTIAL_MASTER_KEY"; then
  # Fernet-compatible urlsafe base64 encoding of 32 random bytes.
  CREDENTIAL_MASTER_KEY="$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '\n')"
  set_env CREDENTIAL_MASTER_KEY "$CREDENTIAL_MASTER_KEY" "$ENV_FILE"
  ok "CREDENTIAL_MASTER_KEY 자동 생성"
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
    printf '\nOpenAI API key 사용 방식을 선택하세요.\n'
    printf '  1) user   : 사용자별 BYOK (권장 기본값)\n'
    printf '  2) server : 서버 공용 OpenAI API key\n'
    read -r -p "선택 [$OPENAI_DEFAULT_CHOICE]: " OPENAI_CHOICE
    case "${OPENAI_CHOICE:-$OPENAI_DEFAULT_CHOICE}" in
      1|user)   SETUP_OPENAI_KEY_MODE="user" ;;
      2|server) SETUP_OPENAI_KEY_MODE="server" ;;
      *) die "OpenAI key mode 선택이 잘못되었습니다." ;;
    esac
  fi
fi

case "$SETUP_OPENAI_KEY_MODE" in
  user)
    set_env OPENAI_KEY_MODE "user" "$ENV_FILE"
    set_env SERVER_OPENAI_API_KEY "" "$ENV_FILE"
    ok "OpenAI: 사용자별 BYOK 모드"
    ;;
  server)
    set_env OPENAI_KEY_MODE "server" "$ENV_FILE"
    SERVER_KEY="$(get_env SERVER_OPENAI_API_KEY "$ENV_FILE")"
    if [[ -t 0 ]]; then
      if [[ -n "$SERVER_KEY" ]]; then
        read -r -p "기존 SERVER_OPENAI_API_KEY를 유지할까요? [Y/n]: " KEEP_KEY
      else
        KEEP_KEY="n"
      fi

      case "${KEEP_KEY:-Y}" in
        n|N|no|NO)
          read -r -s -p "SERVER_OPENAI_API_KEY 입력: " SERVER_KEY
          printf '\n'
          ;;
      esac
    fi
    [[ -n "$SERVER_KEY" ]] || die "server 모드에서는 SERVER_OPENAI_API_KEY가 필요합니다."
    set_env SERVER_OPENAI_API_KEY "$SERVER_KEY" "$ENV_FILE"
    ok "OpenAI: 서버 공용 key 모드"
    ;;
  *)
    die "SETUP_OPENAI_KEY_MODE는 user 또는 server여야 합니다."
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
  SETUP_JOB_CONCURRENCY="$(prompt_value '동시에 실행할 GPU lecture job 수' "$JOB_DEFAULT")"
fi

validate_positive_int "$SETUP_JOB_CONCURRENCY" || die "JOB_CONCURRENCY는 1 이상의 정수여야 합니다."
(( SETUP_JOB_CONCURRENCY <= GPU_COUNT )) || die "JOB_CONCURRENCY(${SETUP_JOB_CONCURRENCY})가 GPU 개수(${GPU_COUNT})보다 큽니다."

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
  DATA_DIR="$(prompt_value '영구 데이터를 저장할 호스트 디렉터리' "$DEFAULT_DATA_DIR")"
fi

mkdir -p "$DATA_DIR"
DATA_DIR="$(cd "$DATA_DIR" && pwd -P)"

ok "데이터 저장 경로: $DATA_DIR"

# -----------------------------------------------------------------------------
# 5. Docker build
# -----------------------------------------------------------------------------
log "Docker image 빌드 중: $IMAGE_NAME"
docker build -t "$IMAGE_NAME" "$ROOT_DIR"
ok "Docker build 완료"

# bind mount되는 data 디렉터리를 non-root 애플리케이션 사용자용으로 준비합니다.
#
# 기본 방식:
#   - 방금 빌드한 이미지의 root 권한으로 임시 컨테이너를 실행
#   - 기존 데이터까지 APP_UID:APP_GID 소유권으로 정리
#   - 0777 대신 0775 권한을 사용
#
# fallback:
#   - rootless Docker/NFS 등으로 chown이 불가능한 환경에서는
#     애플리케이션 실행을 막지 않도록 data 디렉터리에만 0777을 적용
log "data 디렉터리 권한 설정 중 (container UID:GID ${APP_UID}:${APP_GID})..."
if docker run --rm \
    --user 0:0 \
    --entrypoint /bin/sh \
    -v "$DATA_DIR:/app/data" \
    "$IMAGE_NAME" \
    -c "chown -R ${APP_UID}:${APP_GID} /app/data && chmod 0775 /app/data"; then
  ok "data 디렉터리 소유권 설정 완료: ${APP_UID}:${APP_GID} (mode 0775)"
else
  warn "data 디렉터리 chown에 실패했습니다. chmod 0777 fallback을 적용합니다: $DATA_DIR"
  chmod 0777 "$DATA_DIR" || die "data 디렉터리를 쓰기 가능하게 만들지 못했습니다: $DATA_DIR"
fi

# Verify NVIDIA Container Toolkit using the image we just built.
log "Docker GPU passthrough 확인 중..."
docker run --rm --gpus all --entrypoint nvidia-smi "$IMAGE_NAME" >/dev/null \
  || die "Docker 컨테이너에서 NVIDIA GPU를 사용할 수 없습니다. NVIDIA Container Toolkit을 확인하세요."
ok "Docker GPU passthrough 정상"

# -----------------------------------------------------------------------------
# 6. Docker run - external port -> internal 8002
# -----------------------------------------------------------------------------
if docker container inspect "$CONTAINER_NAME" >/dev/null 2>&1; then
  die "기존 컨테이너가 이미 존재합니다: $CONTAINER_NAME
필요하면 직접 중지/삭제한 뒤 setup.sh를 다시 실행하세요."
fi

log "컨테이너 시작"
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
  warn "컨테이너 내부 NVML 초기화 실패. 한 번 재시작합니다."
  docker restart "$CONTAINER_NAME" >/dev/null
  sleep 3
fi

docker exec "$CONTAINER_NAME" nvidia-smi >/dev/null 2>&1 \
  || { docker logs --tail 100 "$CONTAINER_NAME" >&2 || true; die "컨테이너 내부 nvidia-smi 실패"; }
ok "컨테이너 NVIDIA GPU 정상"

docker exec "$CONTAINER_NAME" /opt/conda/envs/runtime/bin/python -c \
  'import torch; assert torch.cuda.is_available(); print("CUDA devices:", torch.cuda.device_count())' \
  || { docker logs --tail 100 "$CONTAINER_NAME" >&2 || true; die "Ditto Python CUDA 초기화 실패"; }
ok "Ditto/PyTorch CUDA 정상"

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
printf ' AI Professor Lite 설치 완료\n'
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
  ok "HTTP 응답 확인 완료"
else
  warn "HTTP readiness를 확인하지 못했습니다. 아래 로그를 확인하세요."
fi

printf '\nUseful commands:\n'
printf '  docker logs -f %s\n' "$CONTAINER_NAME"
printf '  docker exec %s nvidia-smi\n' "$CONTAINER_NAME"
printf '  docker restart %s\n' "$CONTAINER_NAME"
printf '\n'
printf '주의: Docker 포트 매핑만 설정합니다. UFW/클라우드 방화벽은 별도로 외부 포트 %s를 허용해야 할 수 있습니다.\n' "$EXTERNAL_PORT"
