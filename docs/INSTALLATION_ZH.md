[한국어](./INSTALLATION.md) | [English](./INSTALLATION_EN.md) | [日本語](./INSTALLATION_JA.md) | **中文**

# 安装与运维

[README](../README_ZH.md) | [开发者指南](./DEVELOPMENT_ZH.md) | [参与贡献](../CONTRIBUTING_ZH.md)

## 要求

### Docker 安装

- Linux
- Docker Engine
- NVIDIA Driver
- NVIDIA Container Toolkit
- Git
- Git LFS
- OpenSSL
- NVIDIA GPU（Ampere 或更新架构）

主机上必须能够正常执行以下两个命令。

```bash
nvidia-smi
docker run --rm --gpus all nvidia/cuda:12.1.1-base-ubuntu22.04 nvidia-smi
```

### 手动安装

- Linux / POSIX 环境
- Python 3.10
- FFmpeg / FFprobe
- NVIDIA GPU（Ampere 或更新架构）+ CUDA / TensorRT 环境
- SQLite

应用程序与 Ditto 在同一个 Python 3.10 环境中运行。

---

## 快速开始

### Docker 安装

Docker 安装以 `setup.sh` 或 `setup_en.sh` 为准。

```bash
git clone https://github.com/hallym-aied/AI_Prof_lite.git
cd ai_prof_lite

chmod +x setup.sh
./setup.sh
```

英文安装脚本:

```bash
chmod +x setup_en.sh
./setup_en.sh
```

安装脚本会处理以下工作。

- 检查 Docker / GPU / 必需命令
- 准备 Ditto checkpoint
- 创建 `.env` 并设置必需的 secret
- 选择 OpenAI Key 策略
- 根据 GPU 数量设置 worker
- 构建 Docker image
- 检查 GPU passthrough
- 检查是否存在已有容器
- 选择持久化数据路径并 bind mount 到 `/app/data`
- 检查 HTTP readiness

默认 Docker 设置:

```text
Container    : ai-prof-lite
Image        : ai-prof-lite:latest
Internal     : 8002
Runtime      : Python 3.10
Runtime path : /opt/conda/envs/runtime/bin/python
Data default : <project>/data
```

安装过程中可以选择外部端口和持久化数据路径。在数据路径提示处按 Enter，会使用项目的 `data/` 目录。

非交互式安装示例:

```bash
EXTERNAL_PORT=18002 \
DATA_DIR=/srv/ai-prof-lite-data \
SETUP_OPENAI_KEY_MODE=user \
SETUP_JOB_CONCURRENCY=1 \
./setup.sh
```

主要 override:

```text
EXTERNAL_PORT
SETUP_OPENAI_KEY_MODE
SETUP_JOB_CONCURRENCY
IMAGE_NAME
CONTAINER_NAME
ENV_FILE
DATA_DIR
```

检查状态:

```bash
docker logs -f ai-prof-lite
docker exec ai-prof-lite nvidia-smi
docker restart ai-prof-lite
```

#### Reverse proxy / 原始客户端 IP

如果在 Nginx、Traefik 等 reverse proxy 后运行 AI Professor Lite，请将 `FORWARDED_ALLOW_IPS` **仅设置为可信 proxy 的 IP 或 Docker network 网段**。Uvicorn 使用可信 proxy 传递的 `X-Forwarded-For` 将 `request.client.host` 恢复为原始客户端 IP。

该设置也用于登录、注册等功能的基于 IP 的 rate limit。如果 proxy 不受信任，所有请求可能都会显示为来自同一个 proxy IP，导致多个用户共享同一个 rate-limit quota。

如果直接暴露 Docker 端口，请保持默认值。

```env
FORWARDED_ALLOW_IPS=127.0.0.1
```

例如，如果 Nginx 从 Docker network `172.20.0.0/24` 访问应用程序:

```env
FORWARDED_ALLOW_IPS=172.20.0.0/24
```

Nginx 示例:

```nginx
location / {
    proxy_pass http://ai-prof-lite:8002;

    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

> **注意:** 如果应用程序的 `8002` 端口直接暴露给不可信客户端，请不要使用 `FORWARDED_ALLOW_IPS=*`。客户端可能伪造 `X-Forwarded-For`，从而绕过基于 IP 的 rate limit。

---

## 手动安装

### 1. Python 3.10 环境

应用程序与 Ditto 在同一个 Python 3.10 环境中运行。

```bash
conda env create -f environment.yaml
conda activate ditto

python --version
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

开发 / 测试依赖:

```bash
python -m pip install -r requirements-dev.txt
```

不需要单独的应用程序 Python 环境，也不需要单独设置 `DITTO_PYTHON`。`app.py` 与 Ditto inference 会在当前激活的 Python 环境中一起运行。

### 2. Ditto checkpoint

默认路径:

```text
core/ditto-talkinghead/
└── checkpoints/
    ├── ditto_trt_Ampere_Plus/
    └── ditto_cfg/
        └── v0.4_hubert_cfg_trt.pkl
```

相关环境变量:

```env
DITTO_ROOT=core/ditto-talkinghead
DITTO_DATA_ROOT=core/ditto-talkinghead/checkpoints/ditto_trt_Ampere_Plus
DITTO_CFG_PKL=core/ditto-talkinghead/checkpoints/ditto_cfg/v0.4_hubert_cfg_trt.pkl
```

### 3. 环境变量

```bash
cp .env.example .env
```

必需的 secret:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

`.env`:

```env
SESSION_SECRET=<random-secret>
CREDENTIAL_MASTER_KEY=<fernet-key>
```

如果更改 `CREDENTIAL_MASTER_KEY`，此前使用旧 key 加密保存的 credential 将无法解密。

### 4. Preflight

```bash
python scripts/preflight.py
```

### 5. 运行

```bash
python app.py
```

默认地址:

```text
http://localhost:8001
```

可以在 `.env` 中修改应用程序地址。

```env
APP_HOST=0.0.0.0
APP_PORT=8001
```

开发环境 reload:

```env
APP_RELOAD=1
```

`app.py` 会在内部启动 lecture worker supervisor。在相同 `DATA_DIR` 下另行运行 `worker.py` 会发生 worker lock 冲突。

---

## OpenAI 设置

### 用户级 BYOK

默认模式:

```env
OPENAI_KEY_MODE=user
```

每个账户注册自己的 OpenAI API Key。

### 服务器共享 Key

```env
OPENAI_KEY_MODE=server
SERVER_OPENAI_API_KEY=sk-...
```

可以设置每个用户的预算上限。

```env
SERVER_OPENAI_ACCOUNT_BUDGET_USD=
```

无论 OpenAI Key 策略如何，Moodle credential 都按用户分别保存。

---

## 参考资料

支持格式:

```text
.pdf
.txt
.md
.docx
.pptx
```

默认限制:

```env
MAX_REFERENCE_FILES=5
MAX_REFERENCE_FILE_BYTES=10485760
MAX_REFERENCE_UPLOAD_BYTES=26214400
MAX_REFERENCE_CONTEXT_CHARS=120000
```

RAG 设置:

```env
REFERENCE_RAG_CHUNK_CHARS=2600
REFERENCE_RAG_CHUNK_OVERLAP_CHARS=260
REFERENCE_RAG_TOP_K=16
REFERENCE_RAG_MAX_CHUNKS=0
REFERENCE_EMBEDDING_BATCH_SIZE=64
REFERENCE_EMBEDDING_MODEL=text-embedding-3-small
```

`REFERENCE_RAG_MAX_CHUNKS=0` 表示不限制 chunk 数量。

---

## GPU / Worker

默认设置:

```env
JOB_CONCURRENCY=4
JOB_GPU_IDS=0,1,2,3
MAX_RUNNING_JOBS_PER_USER=1
```

单张 GPU:

```env
JOB_CONCURRENCY=1
JOB_GPU_IDS=0
MAX_RUNNING_JOBS_PER_USER=1
```

`JOB_GPU_IDS` 可使用 CUDA index、GPU UUID、MIG UUID。

任务队列相关设置:

```env
JOB_POLL_SECONDS=2
JOB_HEARTBEAT_SECONDS=10
JOB_LEASE_SECONDS=60
JOB_TIMEOUT_SECONDS=7200
JOB_MAX_ATTEMPTS=3
JOB_RETRY_SECONDS=10
```

由于 `app.py` 会启动 embedded worker，正常运维时无需单独运行 `worker.py`。

---

## 目标课程时长

默认值:

```env
LECTURE_TARGET_DURATION_MINUTES=40
LECTURE_TARGET_SLIDE_COUNT=10
LECTURE_DURATION_GENERATION_RATIO=1.05
LECTURE_DURATION_MAX_RETRIES=3
```

TTS 生成后会测量实际音频时长，如果短于目标值则补充 narration。

---

## 数据

默认 DB:

```text
data/ai_prof_lite.db
```

课程输出文件:

```text
data/lectures/<lecture_id>/
```

上传文件和 AI Instructor 数据也保存在 `DATA_DIR` 下。

Docker 安装脚本会询问持久化数据保存路径。默认使用项目的 `data/` 目录，并将所选主机目录 bind mount 到容器的 `/app/data`。非交互式安装可通过 `DATA_DIR` 环境变量指定路径。

应用程序会在 `DATA_DIR` 下创建所需的数据文件和子目录。实际选择的数据目录和 `.env` 都应纳入备份。

---

## 安全

- 密码: Argon2
- Session cookie
- CSRF 验证
- Credential: Fernet 加密
- Trusted Host 限制
- Content Security Policy
- 上传大小限制
- 用户级数据访问验证

生产环境:

```env
APP_ENV=production
TRUSTED_HOSTS=example.com,www.example.com

# 仅在使用 Reverse proxy 时指定可信 proxy IP/network。
# 直接暴露 Docker 端口的默认配置中保持 127.0.0.1。
FORWARDED_ALLOW_IPS=127.0.0.1
```

在 reverse proxy 后运行时，请将 `FORWARDED_ALLOW_IPS` 限制为实际 proxy IP 或内部 network 网段。该值会影响原始客户端 IP 的恢复以及基于 IP 的 rate limit 准确性。

`SESSION_SECRET` 和 `CREDENTIAL_MASTER_KEY` 是 runtime secret，应在 `.env` 中管理。

---

## 问题排查

### `Another lecture worker supervisor is already running`

已有 worker 正在使用相同的 `DATA_DIR`。

检查持有 lock 的进程:

```bash
cat data/lecture-worker.lock
ps -fp "$(cat data/lecture-worker.lock)"
```

或者:

```bash
fuser -v data/lecture-worker.lock
```

正常结束已有进程后，再次运行 `app.py`。

`lecture-worker.lock` 使用 `flock` 管理。只要持有 lock 的进程仍在运行，仅删除文件并不会释放 active lock。

### 找不到 Ditto 文件

检查 Ditto checkpoint 路径及 `.env` 设置:

```env
DITTO_ROOT=core/ditto-talkinghead
DITTO_DATA_ROOT=core/ditto-talkinghead/checkpoints/ditto_trt_Ampere_Plus
DITTO_CFG_PKL=core/ditto-talkinghead/checkpoints/ditto_cfg/v0.4_hubert_cfg_trt.pkl
```

### GPU 数量与 worker 设置不一致

如果只有一张 GPU，请将设置改为:

```env
JOB_CONCURRENCY=1
JOB_GPU_IDS=0
```

### Credential 解密失败

如果当前 `CREDENTIAL_MASTER_KEY` 与保存 credential 时使用的值不同，则现有 credential 无法解密。
