**한국어** | [English](./README_EN.MD) | [日本語](./README_JA.MD) | [中文](./README_ZH.MD)

# AI Professor Lite

> Version `1.0.0`

AI Professor Lite는 강의 기획, 슬라이드, 음성, 교수 아바타 영상, 최종 MP4 제작과 Moodle 배포를 한 흐름으로 처리하는 self-hosted 강의 제작 애플리케이션입니다.

FastAPI 기반 웹 UI와 SQLite 작업 큐를 사용하며, 미디어 생성 작업은 GPU별 독립 runner에서 실행됩니다. OpenAI는 강의 구성, 이미지, TTS, 참고자료 RAG에 사용하고 Ditto TalkingHead는 교수 아바타 영상 생성에 사용합니다.


## 화면 및 생성 예시

대시보드에서 연결 상태, 생성 중인 강의, Ditto 엔진 상태와 최근 작업을 한눈에 확인할 수 있습니다.

<p align="center">
  <img src="docs/images/dashboard.png" alt="AI Professor Lite 대시보드" width="100%">
</p>

강의 상세 화면에서는 현재 생성 stage와 진행률을 확인하고, 완료 후 PPTX, 최종 강의 MP4, narration WAV, Quiz JSON 등의 산출물을 내려받을 수 있습니다. 데스크톱과 모바일 UI를 모두 지원합니다.

<table>
  <tr>
    <td width="72%"><img src="docs/images/lecture-progress-desktop.png" alt="강의 생성 진행 화면 - 데스크톱"></td>
    <td width="28%"><img src="docs/images/lecture-progress-mobile.png" alt="강의 생성 진행 화면 - 모바일"></td>
  </tr>
  <tr>
    <td align="center"><sub>데스크톱 강의 상세 / 생성 진행률</sub></td>
    <td align="center"><sub>모바일 강의 상세</sub></td>
  </tr>
</table>

### 실제 강의 영상 생성 흐름

AI Professor Lite는 생성된 PPT/슬라이드, TTS 음성(`narration.wav`), 교수 이미지를 기반으로 만든 Ditto TalkingHead를 FFmpeg로 합성하여 최종 강의 영상 `final_lecture.mp4`를 생성합니다.

<table>
  <tr>
    <td width="52%"><img src="docs/images/generated-slide.png" alt="생성된 강의 슬라이드 예시"></td>
    <td width="14%" align="center"><img src="docs/images/narration-wav.png" alt="narration.wav 음성" width="120"></td>
    <td width="34%"><img src="docs/images/professor-avatar-source.png" alt="TalkingHead 생성에 사용하는 교수 이미지"></td>
  </tr>
  <tr>
    <td align="center"><sub>PPT / 생성된 강의 슬라이드</sub></td>
    <td align="center"><sub><code>narration.wav</code></sub></td>
    <td align="center"><sub>Ditto TalkingHead용 교수 이미지</sub></td>
  </tr>
</table>

<p align="center"><strong>PPT / 슬라이드 + 음성 + TalkingHead → <code>final_lecture.mp4</code></strong></p>

<p align="center">
  <img src="docs/images/final-lecture-preview.png" alt="PPT와 TalkingHead가 합성된 최종 강의 영상 프레임" width="100%">
</p>

<p align="center"><sub>실제 최종 강의 영상 프레임 예시 — 슬라이드와 TalkingHead가 하나의 영상으로 합성됩니다.</sub></p>

> 저장소에는 README용 정적 이미지 예시만 포함합니다. 실제 생성된 MP4와 WAV 같은 대용량 산출물은 애플리케이션의 강의 상세 화면에서 관리합니다.

---

## 주요 기능

- 회원가입 / 로그인과 사용자별 데이터 분리
- 한국어 / 영어 / 일본어 / 중국어 UI
- 브라우저 언어 자동 감지 및 사용자 언어 고정
- OpenAI 사용자별 BYOK 또는 서버 공용 API Key
- PDF / TXT / Markdown / DOCX / PPTX 참고자료
- 참고자료 전체 입력 또는 embedding 기반 RAG
- 강의안, 슬라이드 구성, narration, Quiz 생성
- GPT Image 기반 슬라이드 이미지 생성
- PowerPoint(`.pptx`) 및 1920×1080 슬라이드 PNG 생성
- OpenAI TTS 기반 강의 음성 생성
- 목표 강의시간에 맞춘 narration 자동 보강
- Ditto TalkingHead 기반 교수 아바타 영상 생성
- 배경 제거 / chroma key 전처리
- FFmpeg 기반 최종 강의 MP4 합성
- PPT 검토 후 승인 / 수정 / 재개
- Moodle course / section / VideoTracker 연동
- AI Instructor 기반 학기 단위 자동 강의 생성 및 예약 게시
- SQLite lease queue, retry, heartbeat, checkpoint 복구
- 다중 GPU worker
- 사용자별 OpenAI 사용량 확인

---

## 요구사항

### Docker 설치

- Linux
- Docker Engine
- NVIDIA Driver
- NVIDIA Container Toolkit
- Git
- Git LFS
- OpenSSL
- NVIDIA GPU

호스트에서 아래 두 명령이 정상 동작해야 합니다.

```bash
nvidia-smi
docker run --rm --gpus all nvidia/cuda:12.1.1-base-ubuntu22.04 nvidia-smi
```

### 수동 설치

- Linux / POSIX 환경
- Python 3.10
- FFmpeg / FFprobe
- NVIDIA GPU + CUDA / TensorRT 환경
- SQLite

애플리케이션과 Ditto는 동일한 Python 3.10 환경에서 실행합니다.

---

# 빠른 시작

## Docker 설치

Docker 설치는 `setup.sh` 또는 `setup_en.sh`를 기준으로 합니다.

```bash
git clone <REPOSITORY_URL>
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

---

# 수동 설치

## 1. Python 3.10 환경

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

## 2. Ditto checkpoint

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

## 3. 환경변수

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

## 4. Preflight

```bash
python scripts/preflight.py
```

## 5. 실행

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

# 최초 설정

1. 계정을 생성합니다.
2. 프로필에서 기본 언어를 선택합니다.
3. `API / 연결 설정`에서 OpenAI credential을 등록합니다.
4. Moodle을 사용할 경우 Moodle Web Service 정보를 등록합니다.
5. 새 강의를 만들고 필요하면 참고자료를 첨부합니다.
6. PPT 검토 단계에서 슬라이드를 확인한 뒤 승인합니다.
7. 생성 완료 후 PPTX, 영상, 음성, Quiz JSON 등의 결과물을 내려받습니다.
8. Moodle 연결이 설정되어 있으면 VideoTracker에 게시할 수 있습니다.

---

# 강의 생성 흐름

```text
강의 주제 / 요청사항 / 참고자료 / 교수 이미지
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
                    └── Moodle VideoTracker (선택)
```

파이프라인 stage:

| Stage | 역할 |
|---|---|
| `plan` | 강의 구성, narration, Quiz 생성 |
| `images` | 슬라이드 시각자료 생성 |
| `slides` | PPTX 및 슬라이드 PNG 생성 |
| `narration` | TTS 생성 및 실제 길이 검증 |
| `timeline` | narration 길이에 맞춘 슬라이드 영상 생성 |
| `avatar` | Ditto 교수 아바타 영상 생성 |
| `compose` | 슬라이드, 아바타, 음성 합성 |
| `deploy` | Moodle 배포 |

완료된 stage는 checkpoint로 기록됩니다. 재시도 시 유효한 결과물이 있으면 해당 stage를 재사용합니다.

---

# OpenAI 설정

## 사용자별 BYOK

기본 모드:

```env
OPENAI_KEY_MODE=user
```

각 계정이 자신의 OpenAI API Key를 등록합니다.

## 서버 공용 Key

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

# 참고자료

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

# GPU / Worker

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

# 목표 강의시간

기본값:

```env
LECTURE_TARGET_DURATION_MINUTES=40
LECTURE_TARGET_SLIDE_COUNT=10
LECTURE_DURATION_GENERATION_RATIO=1.05
LECTURE_DURATION_MAX_RETRIES=3
```

TTS 생성 후 실제 오디오 길이를 측정하고 목표보다 짧으면 narration을 보강합니다.

---

# Moodle

Moodle 연동은 사용자별 Web Service credential을 사용합니다.

지원 흐름:

- course 조회
- section 조회
- VideoTracker 조회
- 기존 activity에 영상 연결
- 새 VideoTracker activity 생성
- 강의 완료 후 즉시 게시
- AI Instructor 예약 게시

Moodle을 사용하지 않아도 강의 생성 기능은 동작합니다.

---

# AI Instructor

AI Instructor는 학기 일정에 맞춰 강의를 자동으로 기획하고 생성 작업을 예약하는 기능입니다.

주요 기능:

- 담당 Moodle course 선택
- 강의 일정 계산
- 교수 아바타 관리
- 예정 강의 자동 생성
- 실패 / 중단 상태 추적
- Moodle 예약 게시
- 서버 재시작 후 catch-up

복구 허용 시간:

```env
AI_INSTRUCTOR_CATCHUP_GRACE_MINUTES=120
```

---

# 다국어

UI 지원 언어:

| Code | 언어 |
|---|---|
| `ko` | 한국어 |
| `en` | English |
| `ja` | 日本語 |
| `zh` | 中文 |

언어 선택 우선순위:

```text
사용자 설정
    │
    ├── ko / en / ja / zh
    │
    └── auto
          │
          ▼
Browser Accept-Language
          │
          ▼
지원 언어로 정규화
          │
          ▼
일치하지 않으면 ko
```

새 계정의 기본값은 `auto`입니다.

## 파일 구조

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

Jinja 공용 설정:

```text
core/templates.py
```

상단 언어 선택기:

```text
templates/base.html
static/language-selector.js
```

## 템플릿에 문자열 추가

템플릿의 사용자 노출 문구는 translation key로 관리합니다.

```jinja2
<h1>{{ t("dashboard.title") }}</h1>
<button>{{ t("common.save") }}</button>
```

XML에는 모든 언어에 같은 key를 추가합니다.

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

동적 값:

```xml
<string name="lecture.hello_user">안녕하세요, {name}님.</string>
```

```jinja2
{{ t("lecture.hello_user", name=user.name) }}
```

선택한 언어에 key가 없으면 `ko`를 사용하고, `ko`에도 없으면 key 문자열 자체를 반환합니다.

## 새 언어 추가

예를 들어 프랑스어 `fr`을 추가할 경우:

1. `core/lang/xml/fr.xml`을 추가합니다.
2. 기존 XML과 같은 key를 채웁니다.
3. `core/lang/config.py`의 `SUPPORTED_LANGUAGES`에 `fr`을 추가합니다.
4. 필요한 locale alias를 `LANGUAGE_ALIASES`에 추가합니다.
5. 전체 템플릿을 렌더링해 누락 key를 확인합니다.

XML loader는 캐시를 사용합니다. 개발 중 XML을 수정한 뒤 즉시 반영되지 않으면 애플리케이션을 재시작합니다.

## CSP

프로젝트는 inline JavaScript event handler를 허용하지 않습니다.

CSP에 의해 차단되는 inline event handler 예시:

```html
<select onchange="this.form.submit()">
```

이벤트 처리는 정적 JS에서 등록합니다.

```javascript
select.addEventListener("change", () => {
    select.form?.submit();
});
```

CSP는 유지하고 이벤트 처리는 정적 JavaScript에서 등록합니다.

---

# 데이터

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

# 보안

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
```

`SESSION_SECRET`과 `CREDENTIAL_MASTER_KEY`는 런타임 secret이며 `.env`에서 관리합니다.

---

# 테스트

```bash
python -m pytest
```

개별 테스트:

```bash
python -m pytest tests/test_pipeline.py
python -m pytest tests/test_worker.py
python -m pytest tests/test_security.py
```

코드 수정 후 최소 확인 항목:

```bash
python scripts/preflight.py
python -m pytest
```

---

# 문제 해결

## `Another lecture worker supervisor is already running`

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

## Ditto 파일을 찾지 못함

Ditto checkpoint 경로 및 `.env` 설정:

```env
DITTO_ROOT=core/ditto-talkinghead
DITTO_DATA_ROOT=core/ditto-talkinghead/checkpoints/ditto_trt_Ampere_Plus
DITTO_CFG_PKL=core/ditto-talkinghead/checkpoints/ditto_cfg/v0.4_hubert_cfg_trt.pkl
```

## GPU 수와 worker 설정이 다름

GPU 한 장이면 다음처럼 줄입니다.

```env
JOB_CONCURRENCY=1
JOB_GPU_IDS=0
```

## Credential 복호화 실패

credential 생성 당시와 현재의 `CREDENTIAL_MASTER_KEY`가 다르면 기존 credential 복호화가 실패합니다.

---

# 프로젝트 구조

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

# 라이선스

Apache License 2.0. 라이선스 전문은 [`LICENSE`](./LICENSE)에 있습니다.
