[한국어](./README.MD) | **English** | [日本語](./README_JA.MD) | [中文](./README_ZH.MD)

# AI Professor Lite

> Version `1.0.0`

AI Professor Lite is a self-hosted lecture production application that handles lecture planning, slides, speech, professor-avatar video, final MP4 composition, and Moodle publishing in one workflow.

The web application is built with FastAPI and uses a SQLite-backed job queue. Media jobs run in isolated GPU runners. OpenAI is used for lecture planning, images, TTS, and reference-material RAG; Ditto TalkingHead is used for professor-avatar video generation.


## Screenshots and generation example

The dashboard provides a single view of connection status, active lecture generation, the Ditto engine, and recent jobs.

<p align="center">
  <img src="docs/images/dashboard.png" alt="AI Professor Lite dashboard" width="100%">
</p>

The lecture detail page shows the current generation stage and progress. After completion, users can download artifacts such as the PPTX, final lecture MP4, narration WAV, and Quiz JSON. Both desktop and mobile layouts are supported.

<table>
  <tr>
    <td width="72%"><img src="docs/images/lecture-progress-desktop.png" alt="Lecture generation progress - desktop"></td>
    <td width="28%"><img src="docs/images/lecture-progress-mobile.png" alt="Lecture generation progress - mobile"></td>
  </tr>
  <tr>
    <td align="center"><sub>Desktop lecture detail / generation progress</sub></td>
    <td align="center"><sub>Mobile lecture detail</sub></td>
  </tr>
</table>

### Actual lecture-video generation flow

AI Professor Lite combines the generated PPT/slides, TTS audio (`narration.wav`), and a Ditto TalkingHead created from the professor image with FFmpeg to produce the final lecture video, `final_lecture.mp4`.

<table>
  <tr>
    <td width="52%"><img src="docs/images/generated-slide.png" alt="Generated lecture slide example"></td>
    <td width="14%" align="center"><img src="docs/images/narration-wav.png" alt="narration.wav audio" width="120"></td>
    <td width="34%"><img src="docs/images/professor-avatar-source.png" alt="Professor image used for TalkingHead generation"></td>
  </tr>
  <tr>
    <td align="center"><sub>PPT / generated lecture slide</sub></td>
    <td align="center"><sub><code>narration.wav</code></sub></td>
    <td align="center"><sub>Professor image for Ditto TalkingHead</sub></td>
  </tr>
</table>

<p align="center"><strong>PPT / slides + audio + TalkingHead → <code>final_lecture.mp4</code></strong></p>

<p align="center">
  <img src="docs/images/final-lecture-preview.png" alt="Final lecture frame composed from a slide and TalkingHead" width="100%">
</p>

<p align="center"><sub>Example frame from the final lecture video — the slide and TalkingHead are composed into a single video.</sub></p>

> The repository contains only lightweight static examples for the README. Large generated artifacts such as MP4 and WAV files are managed from the application's lecture detail page.

---

## Features

- Account registration/login with per-user data isolation
- Korean / English / Japanese / Chinese UI
- Browser-language detection with per-user language override
- Per-user OpenAI BYOK or a shared server API key
- PDF / TXT / Markdown / DOCX / PPTX reference files
- Full-reference input or embedding-based RAG
- Lecture plan, slide structure, narration, and quiz generation
- GPT Image based slide image generation
- PowerPoint (`.pptx`) and 1920×1080 slide PNG output
- OpenAI TTS lecture audio
- Automatic narration expansion to meet target duration
- Ditto TalkingHead professor-avatar video
- Background removal / chroma-key preprocessing
- FFmpeg final MP4 composition
- PPT review, approval, editing, and resume flow
- Moodle course / section / VideoTracker integration
- Semester-based automated lecture generation and scheduled publishing with AI Instructor
- SQLite lease queue, retry, heartbeat, and checkpoint recovery
- Multi-GPU workers
- Per-user OpenAI usage view

---

## Requirements

### Docker installation

- Linux
- Docker Engine
- NVIDIA Driver
- NVIDIA Container Toolkit
- Git
- Git LFS
- OpenSSL
- NVIDIA GPU

Host verification commands:

```bash
nvidia-smi
docker run --rm --gpus all nvidia/cuda:12.1.1-base-ubuntu22.04 nvidia-smi
```

### Manual installation

- Linux / POSIX environment
- Python 3.10
- FFmpeg / FFprobe
- NVIDIA GPU + CUDA / TensorRT environment
- SQLite

The application and Ditto run in the same Python 3.10 environment.

---

# Quick start

## Docker

Docker installation is provided through `setup.sh` and `setup_en.sh`.

```bash
git clone <REPOSITORY_URL>
cd ai_prof_lite

chmod +x setup.sh
./setup.sh
```

For English installer messages:

```bash
chmod +x setup_en.sh
./setup_en.sh
```

The setup script handles:

- Docker / GPU / command checks
- Ditto checkpoint preparation
- `.env` creation and required secrets
- OpenAI key policy selection
- GPU worker configuration
- Docker image build
- GPU passthrough verification
- Existing container presence check
- Persistent host data directory selection and bind mount to `/app/data`
- HTTP readiness check

Default Docker values:

```text
Container    : ai-prof-lite
Image        : ai-prof-lite:latest
Internal     : 8002
Runtime      : Python 3.10
Runtime path : /opt/conda/envs/runtime/bin/python
Data default : <project>/data
```

The external port and persistent data directory are selected during setup. Press Enter at the data-directory prompt to use the project's `data/` directory.

Non-interactive example:

```bash
EXTERNAL_PORT=18002 \
DATA_DIR=/srv/ai-prof-lite-data \
SETUP_OPENAI_KEY_MODE=user \
SETUP_JOB_CONCURRENCY=1 \
./setup.sh
```

Supported overrides:

```text
EXTERNAL_PORT
SETUP_OPENAI_KEY_MODE
SETUP_JOB_CONCURRENCY
IMAGE_NAME
CONTAINER_NAME
ENV_FILE
DATA_DIR
```

Common operations:

```bash
docker logs -f ai-prof-lite
docker exec ai-prof-lite nvidia-smi
docker restart ai-prof-lite
```

### Reverse proxy / original client IP

When AI Professor Lite runs behind Nginx, Traefik, or another reverse proxy, set `FORWARDED_ALLOW_IPS` to **only the trusted proxy IP or Docker network range**. Uvicorn uses `X-Forwarded-For` from a trusted proxy to restore the original client address in `request.client.host`.

This also affects IP-based rate limiting for sign-in and registration. If the proxy is not trusted correctly, every request may appear to come from the proxy's single IP address, causing multiple users to share one rate-limit quota.

For the default setup where the Docker port is exposed directly, keep the default value:

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

> **Warning:** Do not use `FORWARDED_ALLOW_IPS=*` when port `8002` is directly reachable by untrusted clients. Otherwise a client can spoof `X-Forwarded-For` and potentially bypass IP-based rate limits.

---

# Manual installation

## 1. Python 3.10 environment

The application and Ditto run together in a single Python 3.10 environment.

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

A separate application Python environment and a separate `DITTO_PYTHON` setting are not required. `app.py` and Ditto inference use the active Python environment.

## 2. Ditto checkpoints

Default layout:

```text
core/ditto-talkinghead/
└── checkpoints/
    ├── ditto_trt_Ampere_Plus/
    └── ditto_cfg/
        └── v0.4_hubert_cfg_trt.pkl
```

Environment variables:

```env
DITTO_ROOT=core/ditto-talkinghead
DITTO_DATA_ROOT=core/ditto-talkinghead/checkpoints/ditto_trt_Ampere_Plus
DITTO_CFG_PKL=core/ditto-talkinghead/checkpoints/ditto_cfg/v0.4_hubert_cfg_trt.pkl
```

## 3. Environment file

```bash
cp .env.example .env
```

Generate the required secrets:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

`.env`:

```env
SESSION_SECRET=<random-secret>
CREDENTIAL_MASTER_KEY=<fernet-key>
```

Changing `CREDENTIAL_MASTER_KEY` after credentials have been stored makes those existing credentials unreadable.

## 4. Preflight

```bash
python scripts/preflight.py
```

## 5. Run

```bash
python app.py
```

Default URL:

```text
http://localhost:8001
```

Override when needed:

```env
APP_HOST=0.0.0.0
APP_PORT=8001
```

Development reload:

```env
APP_RELOAD=1
```

`app.py` starts the lecture worker supervisor internally. A separate `python worker.py` process using the same `DATA_DIR` conflicts with the worker lock.

---

# First-time setup

1. Create an account.
2. Select the preferred UI language in the profile.
3. Add OpenAI credentials under `API / Connections`.
4. Add Moodle Web Service credentials if Moodle publishing is required.
5. Create a lecture and attach reference files if needed.
6. Review and approve the generated PPT.
7. Download the PPTX, video, audio, quiz JSON, and other outputs after completion.
8. Publish to Moodle VideoTracker when Moodle is configured.

---

# Lecture pipeline

```text
Topic / requirements / references / professor image
                    │
                    ▼
              Lecture Plan
                    │
                    ▼
          Slides / Image Assets
                    │
                    ▼
                 PPTX
                    │
                    ▼
             PPT Review
                    │
                    ▼
             OpenAI TTS
                    │
                    ▼
          Ditto TalkingHead
                    │
                    ▼
             FFmpeg Compose
                    │
                    ▼
          final_lecture.mp4
                    │
                    └── Moodle VideoTracker (optional)
```

Stages:

| Stage | Purpose |
|---|---|
| `plan` | Lecture structure, narration, quiz |
| `images` | Slide visual assets |
| `slides` | PPTX and slide PNGs |
| `narration` | TTS and actual-duration validation |
| `timeline` | Slide video aligned to narration |
| `avatar` | Ditto professor-avatar video |
| `compose` | Slides, avatar, and audio composition |
| `deploy` | Moodle publishing |

Completed stages are checkpointed. A retry reuses valid outputs from completed stages.

---

# OpenAI configuration

## Per-user BYOK

Default mode:

```env
OPENAI_KEY_MODE=user
```

Each account stores its own OpenAI API key.

## Shared server key

```env
OPENAI_KEY_MODE=server
SERVER_OPENAI_API_KEY=sk-...
```

Optional per-account budget:

```env
SERVER_OPENAI_ACCOUNT_BUDGET_USD=
```

Moodle credentials remain per-user regardless of the OpenAI key mode.

---

# Reference files

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

`REFERENCE_RAG_MAX_CHUNKS=0` means no chunk-count limit.

---

# GPU / worker

Default:

```env
JOB_CONCURRENCY=4
JOB_GPU_IDS=0,1,2,3
MAX_RUNNING_JOBS_PER_USER=1
```

Single GPU:

```env
JOB_CONCURRENCY=1
JOB_GPU_IDS=0
MAX_RUNNING_JOBS_PER_USER=1
```

`JOB_GPU_IDS` accepts CUDA indices, GPU UUIDs, and MIG UUIDs.

Queue settings:

```env
JOB_POLL_SECONDS=2
JOB_HEARTBEAT_SECONDS=10
JOB_LEASE_SECONDS=60
JOB_TIMEOUT_SECONDS=7200
JOB_MAX_ATTEMPTS=3
JOB_RETRY_SECONDS=10
```

The normal deployment uses the embedded worker started by `app.py`.

---

# Target lecture duration

Defaults:

```env
LECTURE_TARGET_DURATION_MINUTES=40
LECTURE_TARGET_SLIDE_COUNT=10
LECTURE_DURATION_GENERATION_RATIO=1.05
LECTURE_DURATION_MAX_RETRIES=3
```

The application measures the generated TTS duration and expands narration when it is shorter than the target.

---

# Moodle

Moodle integration uses per-user Web Service credentials.

Supported flows:

- Course lookup
- Section lookup
- VideoTracker lookup
- Attach video to an existing activity
- Create a new VideoTracker activity
- Publish completed lectures
- Scheduled publishing from AI Instructor

Moodle is optional; lecture generation works without it.

---

# AI Instructor

AI Instructor schedules lecture generation around a semester plan.

It supports:

- Moodle course selection
- Lecture schedule calculation
- Professor-avatar management
- Automatic lecture generation
- Run/failure tracking
- Scheduled Moodle publishing
- Catch-up after application downtime

Recovery window:

```env
AI_INSTRUCTOR_CATCHUP_GRACE_MINUTES=120
```

---

# Internationalization

Supported UI languages:

| Code | Language |
|---|---|
| `ko` | 한국어 |
| `en` | English |
| `ja` | 日本語 |
| `zh` | 中文 |

Language resolution:

```text
User preference
    │
    ├── ko / en / ja / zh
    │
    └── auto
          │
          ▼
Browser Accept-Language
          │
          ▼
Normalize to a supported language
          │
          ▼
Fallback to ko
```

New accounts default to `auto`.

## Files

```text
core/
└── lang/
    ├── __init__.py
    ├── config.py
    ├── resolver.py
    ├── loader.py
    └── xml/
        ├── ko.xml
        ├── en.xml
        ├── ja.xml
        └── zh.xml
```

Shared Jinja setup:

```text
core/templates.py
```

Header language selector:

```text
templates/base.html
static/language-selector.js
```

## Adding UI text

User-facing template text is managed through translation keys.

```jinja2
<h1>{{ t("dashboard.title") }}</h1>
<button>{{ t("common.save") }}</button>
```

Add the same key to every language file.

```xml
<!-- ko.xml -->
<string name="lecture.retry">다시 시도</string>

<!-- en.xml -->
<string name="lecture.retry">Retry</string>

<!-- ja.xml -->
<string name="lecture.retry">再試行</string>

<!-- zh.xml -->
<string name="lecture.retry">重试</string>
```

Named placeholders are supported:

```xml
<string name="lecture.hello_user">Hello, {name}.</string>
```

```jinja2
{{ t("lecture.hello_user", name=user.name) }}
```

If the selected language is missing a key, `ko` is used as the fallback. If `ko` is also missing it, the key itself is returned.

## Adding a language

For example, to add French (`fr`):

1. Add `core/lang/xml/fr.xml`.
2. Keep the same key set as the existing language files.
3. Add `fr` to `SUPPORTED_LANGUAGES` in `core/lang/config.py`.
4. Add locale aliases to `LANGUAGE_ALIASES` as needed.
5. Render the templates and check for missing keys.

The XML loader is cached. Restart the application after editing language files if changes are not picked up immediately.

## CSP

Inline JavaScript event handlers are blocked.

Inline event handlers blocked by the CSP:

```html
<select onchange="this.form.submit()">
```

Event handlers are registered from a static JavaScript file:

```javascript
select.addEventListener("change", () => {
    select.form?.submit();
});
```

The CSP remains enabled, and UI events are bound from static JavaScript.

---

# Data

Default database:

```text
data/ai_prof_lite.db
```

Lecture artifacts:

```text
data/lectures/<lecture_id>/
```

Uploads and AI Instructor data also live under `DATA_DIR`.

The Docker setup script asks for the persistent data directory. The default is the project's `data/` directory, and the selected host directory is bind-mounted to `/app/data` in the container. For non-interactive setup, set the `DATA_DIR` environment variable.

The application creates the required files and subdirectories under `DATA_DIR`. Back up the data directory you selected as well as `.env`.

---

# Security

- Argon2 password hashing
- Session cookies
- CSRF validation
- Fernet credential encryption
- Trusted Host filtering
- Content Security Policy
- Upload-size limits
- Per-user access checks

Production:

```env
APP_ENV=production
TRUSTED_HOSTS=example.com,www.example.com

# Set only when using a reverse proxy.
# Keep 127.0.0.1 when exposing the Docker port directly.
FORWARDED_ALLOW_IPS=127.0.0.1
```

When deploying behind a reverse proxy, restrict `FORWARDED_ALLOW_IPS` to the actual proxy IP or internal network range. This setting affects both original client-IP restoration and the accuracy of IP-based rate limiting.

`SESSION_SECRET` and `CREDENTIAL_MASTER_KEY` are runtime secrets managed through `.env`.

---

# Tests

```bash
python -m pytest
```

Examples:

```bash
python -m pytest tests/test_pipeline.py
python -m pytest tests/test_worker.py
python -m pytest tests/test_security.py
```

Minimum checks before deployment:

```bash
python scripts/preflight.py
python -m pytest
```

---

# Troubleshooting

## `Another lecture worker supervisor is already running`

Another worker is using the same `DATA_DIR`.

Lock owner:

```bash
cat data/lecture-worker.lock
ps -fp "$(cat data/lecture-worker.lock)"
```

or:

```bash
fuser -v data/lecture-worker.lock
```

After the existing process exits cleanly, `app.py` can be started again.

`lecture-worker.lock` is managed through `flock`. Removing the file while the owning process is alive does not release the active lock.

## Missing Ditto files

Ditto checkpoint paths and `.env` settings:

```env
DITTO_ROOT=core/ditto-talkinghead
DITTO_DATA_ROOT=core/ditto-talkinghead/checkpoints/ditto_trt_Ampere_Plus
DITTO_CFG_PKL=core/ditto-talkinghead/checkpoints/ditto_cfg/v0.4_hubert_cfg_trt.pkl
```

## Worker configuration does not match the GPU count

For one GPU:

```env
JOB_CONCURRENCY=1
JOB_GPU_IDS=0
```

## Stored credentials cannot be decrypted

Credentials encrypted with a different `CREDENTIAL_MASTER_KEY` cannot be decrypted with the current key.

---

# Project layout

```text
.
├── app.py
├── worker.py
├── setup.sh
├── setup_en.sh
├── Dockerfile
├── .env.example
│
├── core/
│   ├── database/
│   ├── jobs/
│   ├── lang/
│   ├── moodle/
│   ├── openai/
│   ├── ditto-talkinghead/
│   ├── config.py
│   ├── security_headers.py
│   └── templates.py
│
├── modules/
│   ├── auth/
│   ├── credentials/
│   ├── dashboard/
│   ├── image/
│   ├── instructor/
│   ├── lecture/
│   ├── moodle/
│   └── users/
│
├── templates/
├── static/
├── scripts/
├── tests/
└── data/
```


---

# Project and Contributors

AI Professor Lite is a **student-led open-source project**. Its development has been supported through technical guidance and project support.

## Current Contributors

| Name | GitHub | Role |
|---|---|---|
| **Iamjunseok** | [@Iamjunseok](https://github.com/Iamjunseok) | Developer / Collaborator |
| **Wonyoung Choi** | [@waitinghm-creator](https://github.com/waitinghm-creator) | Developer / Collaborator |
| **ChunCheon Man** | [@hero707](https://github.com/hero707) | Technical Advisor / Project Support |
| **hallymgitoslab** | @hallymgitoslab | Project Support / Contributor |

---

# Acknowledgement

This research was supported by the ANCHOR program(Glocal University30) through the Gangwon ANCHOR Center, funded by the Ministry of Education(MOE) and the Gangwon State(G.S.),Republic of Korea.(2026-ANCHOR-10-009)

**Korean acknowledgement**

본 과제(결과물)는 2026년도 교육부 및 강원특별자치도의 재원으로 강원앵커센터의 지원을 받아 수행된 지역성장 인재양성체계(앵커) 글로컬대학 30의 결과입니다.(2026-ANCHOR-10-009)

---

# License

Apache License 2.0. See [`LICENSE`](./LICENSE).
