# 설치 및 운영

[README](../README.md) | [개발자 가이드](./DEVELOPMENT.md) | [기여하기](../CONTRIBUTING.md)

## 요구사항

### Docker 설치

- Linux
- Docker Engine
- NVIDIA Driver
- NVIDIA Container Toolkit
- Git
- Git LFS
- OpenSSL
- NVIDIA GPU (Ampere 이상)

호스트에서 아래 두 명령이 정상 동작해야 합니다.

```bash
nvidia-smi
docker run --rm --gpus all nvidia/cuda:12.1.1-base-ubuntu22.04 nvidia-smi
```

### 수동 설치

- Linux / POSIX 환경
- Python 3.10
- FFmpeg / FFprobe
- NVIDIA GPU (Ampere 이상) + CUDA / TensorRT 환경
- SQLite

애플리케이션과 Ditto는 동일한 Python 3.10 환경에서 실행합니다.

---

## 빠른 시작

### Docker 설치

Docker 설치는 `setup.sh` 또는 `setup_en.sh`를 기준으로 합니다.

```bash
git clone https://github.com/hallym-aied/AI_Prof_lite.git
cd ai_prof_lite

chmod +x setup.sh
./setup.sh
```

영문 설치 스크립트:

```bash
chmod +x setup_en.sh
./setup_en.sh
```

설치 스크립트는 다음 작업을 처리합니다.

- Docker / GPU / 필수 명령 확인
- Ditto checkpoint 준비
- `.env` 생성 및 필수 secret 설정
- OpenAI Key 정책 선택
- GPU 수에 맞춘 worker 설정
- Docker image build
- GPU passthrough 확인
- 기존 컨테이너 존재 여부 확인
- 영구 데이터 저장 경로 선택 및 `/app/data` bind mount
- HTTP readiness 확인

기본 Docker 설정:

```text
Container    : ai-prof-lite
Image        : ai-prof-lite:latest
Internal     : 8002
Runtime      : Python 3.10
Runtime path : /opt/conda/envs/runtime/bin/python
Data default : <project>/data
```

외부 포트와 영구 데이터 저장 경로는 설치 중 선택할 수 있습니다. 데이터 경로에서 Enter를 누르면 프로젝트의 `data/` 디렉터리를 사용합니다.

비대화형 설치 예:

```bash
EXTERNAL_PORT=18002 \
DATA_DIR=/srv/ai-prof-lite-data \
SETUP_OPENAI_KEY_MODE=user \
SETUP_JOB_CONCURRENCY=1 \
./setup.sh
```

주요 override:

```text
EXTERNAL_PORT
SETUP_OPENAI_KEY_MODE
SETUP_JOB_CONCURRENCY
IMAGE_NAME
CONTAINER_NAME
ENV_FILE
DATA_DIR
```

상태 확인:

```bash
docker logs -f ai-prof-lite
docker exec ai-prof-lite nvidia-smi
docker restart ai-prof-lite
```

#### Reverse proxy / 원본 클라이언트 IP

AI Professor Lite를 Nginx, Traefik 등의 reverse proxy 뒤에서 실행할 경우 `FORWARDED_ALLOW_IPS`에 **신뢰할 수 있는 proxy의 IP 또는 Docker network 대역만** 지정해야 합니다. Uvicorn은 신뢰된 proxy가 전달한 `X-Forwarded-For` 정보를 사용해 `request.client.host`를 원본 클라이언트 IP로 복원합니다.

이 설정은 로그인/회원가입 등의 IP 기반 rate limit에도 사용됩니다. Proxy를 신뢰하지 않으면 모든 요청이 proxy의 동일한 IP에서 온 것으로 보일 수 있어 여러 사용자가 하나의 rate-limit quota를 공유하게 됩니다.

Docker 포트를 직접 노출해 사용하는 기본 구성에서는 기본값을 유지하면 됩니다.

```env
FORWARDED_ALLOW_IPS=127.0.0.1
```

예를 들어 Nginx가 Docker network `172.20.0.0/24`에서 애플리케이션에 접근한다면:

```env
FORWARDED_ALLOW_IPS=172.20.0.0/24
```

Nginx 예시:

```nginx
location / {
    proxy_pass http://ai-prof-lite:8002;

    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

> **주의:** 애플리케이션의 `8002` 포트가 신뢰할 수 없는 클라이언트에 직접 노출되어 있다면 `FORWARDED_ALLOW_IPS=*`를 사용하지 마세요. 클라이언트가 `X-Forwarded-For`를 위조해 IP 기반 rate limit을 우회할 수 있습니다.

---

## 수동 설치

### 1. Python 3.10 환경

애플리케이션과 Ditto는 하나의 Python 3.10 환경에서 함께 실행합니다.

```bash
conda env create -f environment.yaml
conda activate ditto

python --version
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

개발 / 테스트 의존성:

```bash
python -m pip install -r requirements-dev.txt
```

별도의 애플리케이션 Python 환경이나 별도의 `DITTO_PYTHON` 설정은 필요하지 않습니다. 활성화한 Python 환경에서 `app.py`와 Ditto inference가 함께 실행됩니다.

### 2. Ditto checkpoint

기본 경로:

```text
core/ditto-talkinghead/
└── checkpoints/
    ├── ditto_trt_Ampere_Plus/
    └── ditto_cfg/
        └── v0.4_hubert_cfg_trt.pkl
```

관련 환경변수:

```env
DITTO_ROOT=core/ditto-talkinghead
DITTO_DATA_ROOT=core/ditto-talkinghead/checkpoints/ditto_trt_Ampere_Plus
DITTO_CFG_PKL=core/ditto-talkinghead/checkpoints/ditto_cfg/v0.4_hubert_cfg_trt.pkl
```

### 3. 환경변수

```bash
cp .env.example .env
```

필수 secret:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

`.env`:

```env
SESSION_SECRET=<random-secret>
CREDENTIAL_MASTER_KEY=<fernet-key>
```

`CREDENTIAL_MASTER_KEY`를 변경하면 기존에 암호화해 저장한 credential을 복호화할 수 없습니다.

### 4. Preflight

```bash
python scripts/preflight.py
```

### 5. 실행

```bash
python app.py
```

기본 주소:

```text
http://localhost:8001
```

애플리케이션 주소 설정은 `.env`에서 변경할 수 있습니다.

```env
APP_HOST=0.0.0.0
APP_PORT=8001
```

개발 환경 reload:

```env
APP_RELOAD=1
```

`app.py`는 lecture worker supervisor를 내부에서 함께 실행합니다. 동일한 `DATA_DIR`에서 별도 `worker.py`를 실행하면 worker lock이 충돌합니다.

---

## OpenAI 설정

### 사용자별 BYOK

기본 모드:

```env
OPENAI_KEY_MODE=user
```

각 계정이 자신의 OpenAI API Key를 등록합니다.

### 서버 공용 Key

```env
OPENAI_KEY_MODE=server
SERVER_OPENAI_API_KEY=sk-...
```

사용자별 예산 한도를 둘 수 있습니다.

```env
SERVER_OPENAI_ACCOUNT_BUDGET_USD=
```

Moodle credential은 OpenAI Key 정책과 관계없이 사용자별로 저장됩니다.

---

## 참고자료

지원 형식:

```text
.pdf
.txt
.md
.docx
.pptx
```

기본 제한:

```env
MAX_REFERENCE_FILES=5
MAX_REFERENCE_FILE_BYTES=10485760
MAX_REFERENCE_UPLOAD_BYTES=26214400
MAX_REFERENCE_CONTEXT_CHARS=120000
```

RAG 설정:

```env
REFERENCE_RAG_CHUNK_CHARS=2600
REFERENCE_RAG_CHUNK_OVERLAP_CHARS=260
REFERENCE_RAG_TOP_K=16
REFERENCE_RAG_MAX_CHUNKS=0
REFERENCE_EMBEDDING_BATCH_SIZE=64
REFERENCE_EMBEDDING_MODEL=text-embedding-3-small
```

`REFERENCE_RAG_MAX_CHUNKS=0`은 chunk 수 제한 없음입니다.

---

## GPU / Worker

기본 설정:

```env
JOB_CONCURRENCY=4
JOB_GPU_IDS=0,1,2,3
MAX_RUNNING_JOBS_PER_USER=1
```

GPU 한 장:

```env
JOB_CONCURRENCY=1
JOB_GPU_IDS=0
MAX_RUNNING_JOBS_PER_USER=1
```

`JOB_GPU_IDS`에는 CUDA index, GPU UUID, MIG UUID를 사용할 수 있습니다.

작업 큐 관련 설정:

```env
JOB_POLL_SECONDS=2
JOB_HEARTBEAT_SECONDS=10
JOB_LEASE_SECONDS=60
JOB_TIMEOUT_SECONDS=7200
JOB_MAX_ATTEMPTS=3
JOB_RETRY_SECONDS=10
```

`app.py`가 embedded worker를 시작하므로 일반 운영에서는 `worker.py`를 따로 실행할 필요가 없습니다.

---

## 목표 강의시간

기본값:

```env
LECTURE_TARGET_DURATION_MINUTES=40
LECTURE_TARGET_SLIDE_COUNT=10
LECTURE_DURATION_GENERATION_RATIO=1.05
LECTURE_DURATION_MAX_RETRIES=3
```

TTS 생성 후 실제 오디오 길이를 측정하고 목표보다 짧으면 narration을 보강합니다.

---

## 데이터

기본 DB:

```text
data/ai_prof_lite.db
```

강의 결과물:

```text
data/lectures/<lecture_id>/
```

업로드 파일과 AI Instructor 데이터도 `DATA_DIR` 아래에 저장됩니다.

Docker 설치 스크립트는 영구 데이터 저장 경로를 사용자에게 묻습니다. 기본값은 프로젝트의 `data/`이며, 선택한 호스트 디렉터리를 컨테이너의 `/app/data`에 bind mount합니다. 비대화형 설치에서는 `DATA_DIR` 환경변수로 경로를 지정할 수 있습니다.

앱은 `DATA_DIR` 아래에 필요한 데이터 파일과 하위 디렉터리를 생성합니다. 실제로 선택한 데이터 디렉터리와 `.env`는 백업 대상입니다.

---

## 보안

- 비밀번호: Argon2
- Session cookie
- CSRF 검증
- Credential: Fernet 암호화
- Trusted Host 제한
- Content Security Policy
- 업로드 크기 제한
- 사용자별 데이터 접근 검증

운영 환경:

```env
APP_ENV=production
TRUSTED_HOSTS=example.com,www.example.com

# Reverse proxy를 사용하는 경우에만 신뢰할 proxy IP/network를 지정합니다.
# Docker 포트를 직접 노출하는 기본 구성에서는 127.0.0.1을 유지합니다.
FORWARDED_ALLOW_IPS=127.0.0.1
```

Reverse proxy 뒤에서 운영할 경우 `FORWARDED_ALLOW_IPS`를 실제 proxy IP 또는 내부 network 대역으로 제한하세요. 이 값은 원본 클라이언트 IP 복원과 IP 기반 rate limit의 정확성에 영향을 줍니다.

`SESSION_SECRET`과 `CREDENTIAL_MASTER_KEY`는 런타임 secret이며 `.env`에서 관리합니다.

---

## 문제 해결

### `Another lecture worker supervisor is already running`

같은 `DATA_DIR`을 사용하는 worker가 이미 실행 중입니다.

lock 소유 프로세스 확인:

```bash
cat data/lecture-worker.lock
ps -fp "$(cat data/lecture-worker.lock)"
```

또는:

```bash
fuser -v data/lecture-worker.lock
```

기존 프로세스를 정상 종료한 뒤 `app.py`를 다시 실행합니다.

`lecture-worker.lock`은 `flock` 기반으로 관리됩니다. lock 소유 프로세스가 살아 있는 동안 파일만 삭제해도 active lock은 해제되지 않습니다.

### Ditto 파일을 찾지 못함

Ditto checkpoint 경로 및 `.env` 설정:

```env
DITTO_ROOT=core/ditto-talkinghead
DITTO_DATA_ROOT=core/ditto-talkinghead/checkpoints/ditto_trt_Ampere_Plus
DITTO_CFG_PKL=core/ditto-talkinghead/checkpoints/ditto_cfg/v0.4_hubert_cfg_trt.pkl
```

### GPU 수와 worker 설정이 다름

GPU 한 장이면 다음처럼 줄입니다.

```env
JOB_CONCURRENCY=1
JOB_GPU_IDS=0
```

### Credential 복호화 실패

credential 생성 당시와 현재의 `CREDENTIAL_MASTER_KEY`가 다르면 기존 credential 복호화가 실패합니다.
