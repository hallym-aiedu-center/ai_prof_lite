[한국어](./INSTALLATION.md) | **English** | [日本語](./INSTALLATION_JA.md) | [中文](./INSTALLATION_ZH.md)

# Installation & Operations

[README](../README_EN.md) | [Developer Guide](./DEVELOPMENT_EN.md) | [Contributing](../CONTRIBUTING_EN.md)

## Requirements

### Docker Installation

- Linux
- Docker Engine
- NVIDIA Driver
- NVIDIA Container Toolkit
- Git
- Git LFS
- OpenSSL
- NVIDIA GPU (Ampere or newer)

The following two commands must run successfully on the host.

```bash
nvidia-smi
docker run --rm --gpus all nvidia/cuda:12.1.1-base-ubuntu22.04 nvidia-smi
```

### Manual Installation

- Linux / POSIX environment
- Python 3.10
- FFmpeg / FFprobe
- NVIDIA GPU (Ampere or newer) + CUDA / TensorRT environment
- SQLite

The application and Ditto run in the same Python 3.10 environment.

---

## Quick Start

### Docker Installation

Docker installation is based on `setup.sh` or `setup_en.sh`.

```bash
git clone https://github.com/hallym-aied/AI_Prof.git
cd ai_prof_lite

chmod +x setup.sh
./setup.sh
```

English setup script:

```bash
chmod +x setup_en.sh
./setup_en.sh
```

The setup script handles the following tasks.

- Check Docker / GPU / required commands
- Prepare Ditto checkpoints
- Create `.env` and configure required secrets
- Select the OpenAI Key policy
- Configure workers based on the number of GPUs
- Build the Docker image
- Verify GPU passthrough
- Check for an existing container
- Select a persistent data path and bind mount it to `/app/data`
- Verify HTTP readiness

Default Docker settings:

```text
Container    : ai-prof-lite
Image        : ai-prof-lite:latest
Internal     : 8002
Runtime      : Python 3.10
Runtime path : /opt/conda/envs/runtime/bin/python
Data default : <project>/data
```

You can choose the external port and persistent data path during installation. Press Enter at the data path prompt to use the project's `data/` directory.

Non-interactive installation example:

```bash
EXTERNAL_PORT=18002 \
DATA_DIR=/srv/ai-prof-lite-data \
SETUP_OPENAI_KEY_MODE=user \
SETUP_JOB_CONCURRENCY=1 \
./setup.sh
```

Main overrides:

```text
EXTERNAL_PORT
SETUP_OPENAI_KEY_MODE
SETUP_JOB_CONCURRENCY
IMAGE_NAME
CONTAINER_NAME
ENV_FILE
DATA_DIR
```

Check status:

```bash
docker logs -f ai-prof-lite
docker exec ai-prof-lite nvidia-smi
docker restart ai-prof-lite
```

#### Reverse Proxy / Original Client IP

When running AI Professor Lite behind a reverse proxy such as Nginx or Traefik, set `FORWARDED_ALLOW_IPS` to **only the IP address of a trusted proxy or the Docker network range**. Uvicorn uses `X-Forwarded-For` from a trusted proxy to restore the original client IP as `request.client.host`.

This value is also used for IP-based rate limits on login and registration. If the proxy is not trusted, all requests may appear to come from the same proxy IP, causing multiple users to share one rate-limit quota.

If you expose the Docker port directly, keep the default value.

```env
FORWARDED_ALLOW_IPS=127.0.0.1
```

For example, if Nginx reaches the application from Docker network `172.20.0.0/24`:

```env
FORWARDED_ALLOW_IPS=172.20.0.0/24
```

Nginx example:

```nginx
location / {
    proxy_pass http://ai-prof-lite:8002;

    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

> **Warning:** If application port `8002` is directly exposed to untrusted clients, do not use `FORWARDED_ALLOW_IPS=*`. A client could spoof `X-Forwarded-For` and bypass IP-based rate limits.

---

## Manual Installation

### 1. Python 3.10 Environment

The application and Ditto run together in one Python 3.10 environment.

```bash
conda env create -f environment.yaml
conda activate ditto

python --version
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Development / test dependencies:

```bash
python -m pip install -r requirements-dev.txt
```

A separate Python environment for the application or a separate `DITTO_PYTHON` setting is not required. `app.py` and Ditto inference run in the active Python environment.

### 2. Ditto Checkpoint

Default path:

```text
core/ditto-talkinghead/
└── checkpoints/
    ├── ditto_trt_Ampere_Plus/
    └── ditto_cfg/
        └── v0.4_hubert_cfg_trt.pkl
```

Related environment variables:

```env
DITTO_ROOT=core/ditto-talkinghead
DITTO_DATA_ROOT=core/ditto-talkinghead/checkpoints/ditto_trt_Ampere_Plus
DITTO_CFG_PKL=core/ditto-talkinghead/checkpoints/ditto_cfg/v0.4_hubert_cfg_trt.pkl
```

### 3. Environment Variables

```bash
cp .env.example .env
```

Required secrets:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

`.env`:

```env
SESSION_SECRET=<random-secret>
CREDENTIAL_MASTER_KEY=<fernet-key>
```

If you change `CREDENTIAL_MASTER_KEY`, credentials that were encrypted with the previous key can no longer be decrypted.

### 4. Preflight

```bash
python scripts/preflight.py
```

### 5. Run

```bash
python app.py
```

Default address:

```text
http://localhost:8001
```

You can change the application host and port in `.env`.

```env
APP_HOST=0.0.0.0
APP_PORT=8001
```

Development reload:

```env
APP_RELOAD=1
```

`app.py` starts the lecture worker supervisor internally. Running a separate `worker.py` against the same `DATA_DIR` will cause a worker lock conflict.

---

## OpenAI Settings

### Per-user BYOK

Default mode:

```env
OPENAI_KEY_MODE=user
```

Each account registers its own OpenAI API Key.

### Shared Server Key

```env
OPENAI_KEY_MODE=server
SERVER_OPENAI_API_KEY=sk-...
```

You can set a per-user budget limit.

```env
SERVER_OPENAI_ACCOUNT_BUDGET_USD=
```

Moodle credentials are always stored per user regardless of the OpenAI Key policy.

---

## Reference Materials

Supported formats:

```text
.pdf
.txt
.md
.docx
.pptx
```

Default limits:

```env
MAX_REFERENCE_FILES=5
MAX_REFERENCE_FILE_BYTES=10485760
MAX_REFERENCE_UPLOAD_BYTES=26214400
MAX_REFERENCE_CONTEXT_CHARS=120000
```

RAG settings:

```env
REFERENCE_RAG_CHUNK_CHARS=2600
REFERENCE_RAG_CHUNK_OVERLAP_CHARS=260
REFERENCE_RAG_TOP_K=16
REFERENCE_RAG_MAX_CHUNKS=0
REFERENCE_EMBEDDING_BATCH_SIZE=64
REFERENCE_EMBEDDING_MODEL=text-embedding-3-small
```

`REFERENCE_RAG_MAX_CHUNKS=0` means there is no limit on the number of chunks.

---

## GPU / Worker

Default settings:

```env
JOB_CONCURRENCY=4
JOB_GPU_IDS=0,1,2,3
MAX_RUNNING_JOBS_PER_USER=1
```

For one GPU:

```env
JOB_CONCURRENCY=1
JOB_GPU_IDS=0
MAX_RUNNING_JOBS_PER_USER=1
```

`JOB_GPU_IDS` accepts CUDA indexes, GPU UUIDs, and MIG UUIDs.

Job queue settings:

```env
JOB_POLL_SECONDS=2
JOB_HEARTBEAT_SECONDS=10
JOB_LEASE_SECONDS=60
JOB_TIMEOUT_SECONDS=7200
JOB_MAX_ATTEMPTS=3
JOB_RETRY_SECONDS=10
```

Because `app.py` starts an embedded worker, you normally do not need to run `worker.py` separately.

---

## Target Lecture Duration

Default values:

```env
LECTURE_TARGET_DURATION_MINUTES=40
LECTURE_TARGET_SLIDE_COUNT=10
LECTURE_DURATION_GENERATION_RATIO=1.05
LECTURE_DURATION_MAX_RETRIES=3
```

After TTS generation, the application measures the actual audio duration and extends the narration if it is shorter than the target.

---

## Data

Default DB:

```text
data/ai_prof_lite.db
```

Lecture outputs:

```text
data/lectures/<lecture_id>/
```

Uploaded files and AI Instructor data are also stored under `DATA_DIR`.

The Docker setup script asks for a persistent data path. The default is the project's `data/` directory, and the selected host directory is bind-mounted to `/app/data` in the container. For non-interactive installation, use the `DATA_DIR` environment variable.

The application creates the required data files and subdirectories under `DATA_DIR`. Back up the selected data directory and `.env`.

---

## Security

- Passwords: Argon2
- Session cookie
- CSRF validation
- Credentials: Fernet encryption
- Trusted Host restriction
- Content Security Policy
- Upload size limits
- Per-user data access validation

Production environment:

```env
APP_ENV=production
TRUSTED_HOSTS=example.com,www.example.com

# Set a trusted proxy IP/network only when using a reverse proxy.
# Keep 127.0.0.1 when exposing the Docker port directly.
FORWARDED_ALLOW_IPS=127.0.0.1
```

When running behind a reverse proxy, restrict `FORWARDED_ALLOW_IPS` to the actual proxy IP or internal network range. This affects original client IP restoration and the accuracy of IP-based rate limits.

`SESSION_SECRET` and `CREDENTIAL_MASTER_KEY` are runtime secrets and should be managed in `.env`.

---

## Troubleshooting

### `Another lecture worker supervisor is already running`

A worker using the same `DATA_DIR` is already running.

Check the process that owns the lock:

```bash
cat data/lecture-worker.lock
ps -fp "$(cat data/lecture-worker.lock)"
```

Or:

```bash
fuser -v data/lecture-worker.lock
```

Stop the existing process normally, then run `app.py` again.

`lecture-worker.lock` is managed with `flock`. Deleting the file alone does not release an active lock while the process that owns it is still running.

### Ditto Files Not Found

Check the Ditto checkpoint path and `.env` settings:

```env
DITTO_ROOT=core/ditto-talkinghead
DITTO_DATA_ROOT=core/ditto-talkinghead/checkpoints/ditto_trt_Ampere_Plus
DITTO_CFG_PKL=core/ditto-talkinghead/checkpoints/ditto_cfg/v0.4_hubert_cfg_trt.pkl
```

### GPU Count and Worker Settings Do Not Match

For one GPU, reduce the settings as follows.

```env
JOB_CONCURRENCY=1
JOB_GPU_IDS=0
```

### Credential Decryption Fails

If the current `CREDENTIAL_MASTER_KEY` differs from the one used when the credentials were stored, the existing credentials cannot be decrypted.
