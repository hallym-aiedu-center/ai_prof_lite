# AI Professor Lite

> Version `0.5.9`

현재 애플리케이션 버전은 `0.5.9`입니다.

> v0.5.9에서는 OpenAI usage pricing/accounting, 참고자료 파일 처리와 RAG, AI Instructor 선택 로직, Moodle 예약 게시 실행 로직, 기본 DB schema 초기화의 책임을 분리하여 코드 구조와 유지보수성을 개선했습니다.
>
> v0.5.7에서는 RAG 참고자료의 160개 chunk 제한을 기본 해제하고, PPT 승인과 작업 큐 재개를 단일 트랜잭션으로 처리하도록 안정성을 개선했습니다.

AI Professor Lite는 **강의 주제와 교수 아바타 이미지를 입력하면 강의 기획부터 슬라이드, TTS, Talking Head 영상, 최종 MP4, Moodle 배포까지 자동화하는 FastAPI 기반 강의 제작 시스템**입니다.

애플리케이션은 단순한 동기식 요청-응답 구조가 아니라, SQLite 작업 큐와 GPU별 isolated runner를 이용해 오래 걸리는 미디어 생성 작업을 처리합니다. `app.py`를 실행하면 웹 서버뿐 아니라 **강의 worker, AI Instructor scheduler, Moodle publish scheduler가 함께 시작**됩니다.

```text
강의 제목/주제 + 교수 이미지
          │
          ▼
   OpenAI 강의 설계
  (slides + quiz JSON)
          │
          ▼
   슬라이드 이미지/PPTX
          │
          ▼
      OpenAI TTS
          │
          ▼
   Ditto TalkingHead
          │
          ▼
      FFmpeg 합성
          │
          ▼
    final_lecture.mp4
          │
          └──── 선택적으로 Moodle VideoTracker 배포
```

---

## 주요 기능

- 회원가입 / 로그인 기반 사용자 분리
- 사용자별 OpenAI BYOK 또는 서버 공용 OpenAI Key 모드
- 사용자별 Moodle Web Service 연결 정보 암호화 저장
- 강의 제목과 요청사항을 바탕으로 구조화된 강의안 생성
- 슬라이드별 bullet, narration, 이미지 프롬프트 생성
- 4지선다형 Quiz JSON 생성
- GPT Image 기반 전체 슬라이드 이미지 또는 보조 이미지 생성
- PowerPoint(`.pptx`) 및 1920×1080 슬라이드 PNG 생성
- OpenAI TTS 기반 슬라이드별 WAV 및 전체 narration 생성
- 목표 강의시간 보장: 실제 TTS 길이를 측정하고 부족하면 narration을 자동 보강한 뒤 최종 MP4 길이를 재검증
- Ditto TalkingHead 기반 교수 아바타 영상 생성
- 자동 배경 제거 / chroma key 전처리
- FFmpeg 기반 슬라이드 영상 및 최종 강의 MP4 합성
- Moodle 강좌 / 섹션 / VideoTracker 조회
- 기존 VideoTracker에 영상 연결 또는 새 VideoTracker 생성
- AI Instructor를 이용한 학기 단위 자동 강의 기획 / 생성 / 예약 게시
- SQLite lease 기반 작업 큐, retry, heartbeat, checkpoint 복구
- 다중 GPU worker (`JOB_CONCURRENCY`, `JOB_GPU_IDS`)
- 사용자별 동시 실행 제한
- 생성 산출물 다운로드(PPTX / 영상 / 오디오 / 아바타 / Quiz JSON)

---

## 기술 스택

| 영역 | 사용 기술 |
|---|---|
| Web | FastAPI, Uvicorn, Jinja2 |
| Database | SQLite, aiosqlite, WAL mode |
| Auth | Session cookie, Argon2 password hashing, CSRF token |
| Secret storage | Fernet (`cryptography`) |
| LLM | OpenAI Responses API |
| Image | OpenAI Image API, Pillow |
| TTS | OpenAI Audio Speech API |
| Avatar | Ditto TalkingHead, TensorRT/CUDA |
| Background removal | rembg |
| Slides | python-pptx, Pillow |
| Media | FFmpeg, FFprobe |
| LMS | Moodle REST Web Service + VideoTracker custom functions |
| Queue | SQLite-backed lease queue + isolated subprocess runner |

---

## 실행 구조

### `app.py`

메인 엔트리포인트입니다.

애플리케이션 lifespan에서 다음 구성요소를 초기화합니다.

1. SQLite schema/migration
2. AI Instructor schema
3. orphan run cleanup
4. Moodle publish scheduler
5. AI Instructor scheduler
6. embedded lecture worker supervisor

따라서 일반적인 실행에서는 아래 한 명령이면 충분합니다.

```bash
python app.py
```

> **중요:** `app.py`가 worker supervisor를 자동으로 실행합니다. 같은 `DATA_DIR`을 사용하는 상태에서 `python worker.py`를 별도로 동시에 실행하지 마세요. `lecture-worker.lock`으로 중복 supervisor 실행이 차단됩니다.

### `worker.py`

독립 실행이 가능한 lecture worker supervisor입니다. 각 강의 작업을 별도의 `core.jobs.runner` 프로세스로 실행하고, 각 runner에 GPU 하나를 `CUDA_VISIBLE_DEVICES`로 고정합니다.

일반 배포에서는 `app.py`의 embedded worker를 사용하면 됩니다. `worker.py`는 worker만 독립적으로 검증하거나 별도 운영 구조를 구성할 때 사용할 수 있습니다.

---

## 강의 생성 파이프라인

강의 생성은 아래 stage를 순서대로 수행합니다.

| Stage | Progress | 역할 |
|---|---:|---|
| `plan` | 10% | 강의 구성, slide narration, Quiz 생성 |
| `images` | 22% | 슬라이드 시각자료 생성 |
| `slides` | 42% | PPTX 및 1920×1080 슬라이드 PNG 생성 |
| `narration` | 50% | 슬라이드별 TTS WAV + 전체 narration 생성, 실제 재생시간 검증 및 부족분 자동 보강 |
| `timeline` | 65% | narration 길이에 맞춘 슬라이드 MP4 생성 |
| `avatar` | 73% | Ditto TalkingHead 아바타 영상 생성 |
| `compose` | 86% | 슬라이드 + 아바타 + narration 최종 합성 |
| `deploy` | 96% | 선택적으로 Moodle VideoTracker 배포 |

각 stage는 `lecture_stages` 테이블에 checkpoint를 기록합니다. 재시도 시 이미 완료된 stage의 파일이 유효하면 다시 생성하지 않고 이어서 실행합니다.

유료 API 결과 중 일부는 강의별 cache에 저장되어 retry 시 중복 호출을 줄입니다.

---

## 시스템 요구사항

### Application

- Linux / POSIX 환경
- Python 3.12 권장
- FFmpeg
- FFprobe
- SQLite

worker는 다음 Linux 기능을 사용합니다.

- `fcntl`
- process group signal
- `/proc`

따라서 현재 worker 구현은 Linux 환경을 기준으로 합니다.

### GPU / Ditto

- NVIDIA GPU
- NVIDIA Driver
- CUDA / TensorRT가 동작하는 Ditto Python 환경
- 프로젝트의 `environment.yaml`은 Python 3.10 + PyTorch/CUDA/TensorRT 환경을 정의합니다.

Application Python과 Ditto Python은 분리해서 운영하는 것을 권장합니다.

```text
Application : Python 3.12
Ditto       : Python 3.10
```

---

# 설치

## 1. 저장소 준비

```bash
git clone <YOUR_REPOSITORY_URL>
cd AI_Prof-main
```

압축본을 사용하는 경우 프로젝트 루트(`app.py`가 있는 디렉터리)로 이동하면 됩니다.

---

## 2. 시스템 패키지 설치

Ubuntu 계열 예시:

```bash
sudo apt update
sudo apt install -y ffmpeg git
```

정상 설치 확인:

```bash
ffmpeg -version
ffprobe -version
```

---

## 3. Application Python 환경

Python 3.12 virtualenv 예시:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

테스트 도구까지 설치하려면:

```bash
python -m pip install -r requirements-dev.txt
```

`requirements.txt`는 테스트된 Python 3.12 Linux runtime dependency가 version pinning 되어 있습니다.

---

## 4. Ditto 환경

프로젝트에는 Ditto source가 `core/ditto-talkinghead`에 포함되어 있지만 **model checkpoint는 포함되어 있지 않습니다.**

Conda 환경 생성:

```bash
conda env create -f environment.yaml
conda activate ditto
```

Ditto Python 경로 확인:

```bash
which python
```

확인한 절대 경로를 이후 `.env`의 `DITTO_PYTHON`에 지정하는 것을 권장합니다.

예:

```env
DITTO_PYTHON=/home/user/miniconda3/envs/ditto/bin/python
```

`DITTO_PYTHON`을 지정하지 않으면 application을 실행한 Python interpreter가 Ditto 실행에도 사용됩니다.

---

## 5. Ditto checkpoint 배치

코드가 기본으로 기대하는 경로는 다음과 같습니다.

```text
core/ditto-talkinghead/
└── checkpoints/
    ├── ditto_trt_Ampere_Plus/
    └── ditto_cfg/
        └── v0.4_hubert_cfg_trt.pkl
```

기본 환경변수:

```env
DITTO_ROOT=core/ditto-talkinghead
DITTO_DATA_ROOT=core/ditto-talkinghead/checkpoints/ditto_trt_Ampere_Plus
DITTO_CFG_PKL=core/ditto-talkinghead/checkpoints/ditto_cfg/v0.4_hubert_cfg_trt.pkl
```

다른 위치에 설치했다면 위 값을 실제 경로로 변경하면 됩니다. 상대 경로는 프로젝트 루트를 기준으로 해석됩니다.

---

## 6. `.env` 생성

```bash
cp .env.example .env
```

최소한 아래 두 secret은 반드시 변경해야 합니다.

### `SESSION_SECRET`

32자 이상의 랜덤 문자열이 필요합니다.

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

### `CREDENTIAL_MASTER_KEY`

사용자 API Key / token 암호화에 사용하는 Fernet key입니다.

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

생성한 값을 `.env`에 넣습니다.

```env
SESSION_SECRET=<generated-random-secret>
CREDENTIAL_MASTER_KEY=<generated-fernet-key>
```

> 기존 DB에서 credential을 이미 저장한 뒤 `CREDENTIAL_MASTER_KEY`를 바꾸면 기존 secret을 복호화할 수 없습니다.

---

## 7. OpenAI credential 정책 선택

### 사용자별 BYOK 모드

기본값입니다.

```env
OPENAI_KEY_MODE=user
```

각 사용자가 로그인 후 **API / 연결 설정** 화면에서 자신의 OpenAI API Key를 등록합니다.

### 서버 공용 Key 모드

```env
OPENAI_KEY_MODE=server
SERVER_OPENAI_API_KEY=sk-...
```

이 모드에서는 사용자별 OpenAI Key 입력 UI가 숨겨지고 서버 key를 모든 lecture job이 사용합니다.

Moodle credential은 OpenAI와 달리 항상 사용자별 credential을 사용합니다.

---

## 8. GPU 설정

기본값은 4개의 동시 job / 4개의 GPU입니다.

```env
JOB_CONCURRENCY=4
JOB_GPU_IDS=0,1,2,3
MAX_RUNNING_JOBS_PER_USER=1
```

GPU 한 장만 사용하는 서버라면 다음처럼 설정합니다.

```env
JOB_CONCURRENCY=1
JOB_GPU_IDS=0
MAX_RUNNING_JOBS_PER_USER=1
```

`JOB_GPU_IDS`는 일반 CUDA index뿐 아니라 GPU UUID / MIG UUID 형식도 받을 수 있습니다.

`JOB_GPU_IDS`를 사용하는 경우 `DITTO_GPU`를 같이 지정하지 않는 것을 권장합니다. embedded supervisor가 각 runner의 `CUDA_VISIBLE_DEVICES`를 직접 설정합니다.

---

## 9. Preflight

환경 설정 후 다음 검사를 실행합니다.

```bash
python scripts/preflight.py
```

검사 항목:

- 주요 Python package import 가능 여부
- FFmpeg / FFprobe 존재 여부
- `SESSION_SECRET`
- `CREDENTIAL_MASTER_KEY`
- server OpenAI mode의 API Key 설정 여부
- Ditto `inference.py`
- Ditto data root
- Ditto config pickle
- `DITTO_PYTHON` 실행 파일

정상 예시:

```text
OK: 필수 패키지, 설정 및 외부 실행 파일 경로 확인 완료
OpenAI/Moodle 연결, CUDA 및 Ditto 모델 실행 여부는 실제 환경에서 확인하세요.
```

---

# 실행

## 기본 실행

```bash
source .venv/bin/activate
python app.py
```

기본 주소:

```text
http://localhost:8001
```

기본 binding:

```env
APP_HOST=0.0.0.0
APP_PORT=8001
```

개발 중 reload가 필요하면:

```env
APP_RELOAD=1
```

프로덕션에서는 HTTPS reverse proxy 뒤에서 실행하고 다음 값을 설정하는 것을 권장합니다.

```env
APP_ENV=production
TRUSTED_HOSTS=example.com,www.example.com
```

`APP_ENV=production`이면 session cookie에 `Secure` 옵션이 적용됩니다.

> 현재 app 구조는 내부 worker singleton을 포함하므로 동일한 `DATA_DIR`을 공유하는 `uvicorn --workers N` 다중 프로세스 실행과 맞지 않습니다. 기본적으로 application process는 하나만 실행하고, 내부 worker의 `JOB_CONCURRENCY`로 GPU 병렬성을 조절하세요.

---

# 최초 사용 순서

1. `/register`에서 사용자 계정을 생성합니다.
2. `/settings/credentials`에서 OpenAI / Moodle 연결 정보를 설정합니다.
3. `/lectures/new`에서 새 강의를 생성합니다.
4. 강의 제목과 상세 요청을 입력합니다.
5. Text / Image / TTS 모델 및 voice를 선택합니다.
6. 목표 강의시간과 슬라이드 수를 선택합니다.
7. 교수 portrait 이미지를 업로드합니다.
8. 필요하면 Moodle 자동 업로드를 활성화합니다.
9. 생성 후 lecture detail 화면에서 진행률을 확인합니다.
10. 완료되면 PPTX, 최종 영상, narration, avatar, Quiz JSON을 다운로드합니다.

---

## 강의 입력 제한

현재 웹 UI/API validation 기준:

| 항목 | 제한 |
|---|---|
| 제목 | 1~200자 |
| 강의 요청(topic) | 1~20,000자 |
| 목표 강의시간 | 30 / 40 / 50 / 60분 |
| 목표 슬라이드 수 | 8~12장 |
| 모델/voice 문자열 | 1~128자 |
| portrait 형식 | PNG / JPEG / WebP |
| portrait 기본 최대 크기 | 10 MiB |
| portrait 기본 최대 픽셀 | 16,000,000 pixels |

업로드된 portrait는 metadata가 제거되고 PNG로 정규화되며 최대 2048×2048 범위로 축소됩니다.

---

# OpenAI 설정

웹 강의 생성 기본 모델은 다음 환경변수로 결정됩니다.

```env
LECTURE_TEXT_MODEL=gpt-5.1
LECTURE_IMAGE_MODEL=gpt-image-2
LECTURE_TTS_MODEL=gpt-4o-mini-tts
LECTURE_TTS_VOICE=alloy
```

코드 기본값도 위와 동일합니다.

기본 lecture format:

```env
LECTURE_TARGET_DURATION_MINUTES=40
LECTURE_TARGET_SLIDE_COUNT=10
LECTURE_DURATION_GENERATION_RATIO=1.05
LECTURE_DURATION_MAX_RETRIES=3
```

웹 폼에서는 강의시간 30/40/50/60분, 슬라이드 8~12장을 선택할 수 있습니다.

TTS는 긴 narration을 OpenAI Audio API 한도에 맞게 chunk로 분할한 뒤 FFmpeg로 합칩니다.

```env
LECTURE_TTS_CHUNK_CHARS=3900
```

내부 상한은 4096자입니다.

## 목표 강의시간 보장

`target_duration_minutes`는 단순한 LLM 프롬프트 힌트가 아니라 **실제 생성 결과의 최소 강의시간 기준**으로 사용됩니다.

강의 생성 시 다음 순서로 시간을 확인합니다.

1. planner가 목표시간보다 약간 긴 narration을 생성하도록 요청합니다.
2. TTS 생성 후 FFprobe로 실제 narration 재생시간을 측정합니다.
3. 목표시간보다 짧으면 슬라이드 구조와 핵심 내용은 유지한 채 narration 설명을 자동 보강합니다.
4. 보강된 narration으로 필요한 TTS를 다시 생성하고 재생시간을 다시 확인합니다.
5. 최대 재시도 횟수 안에 목표시간을 충족하지 못하면 작업을 성공 처리하지 않습니다.
6. 최종 MP4 합성 후에도 실제 영상 길이가 목표시간 이상인지 한 번 더 검증합니다.

관련 설정:

```env
# 최초 narration 생성 목표에 적용하는 여유 비율
# 40분 설정 시 기본값 1.05는 약 42분 분량을 목표로 생성
LECTURE_DURATION_GENERATION_RATIO=1.05

# 실제 TTS가 목표시간보다 짧을 때 narration 자동 보강 최대 횟수
LECTURE_DURATION_MAX_RETRIES=3
```

TTS 캐시는 narration 내용 기준으로 검증하므로, 보강 과정에서는 **내용이 변경된 슬라이드의 음성만 다시 생성**하고 변경되지 않은 슬라이드는 기존 결과를 재사용합니다.

---

# 슬라이드 생성 방식

기본값:

```env
LECTURE_RENDER_SLIDES_WITH_IMAGE_MODEL=true
OPENAI_SLIDE_IMAGE_QUALITY=high
```

`LECTURE_RENDER_SLIDES_WITH_IMAGE_MODEL=true`이고 사용자가 이미지 생성을 활성화하면, OpenAI Image API에 **완성형 16:9 강의 슬라이드 전체 이미지** 생성을 요청합니다.

생성된 슬라이드는 최종적으로 1920×1080 PNG로 정규화되고, 동일 이미지를 이용해 PPTX가 생성됩니다.

Image model 기반 전체 슬라이드 생성을 끄면 로컬 slide composition 경로와 별도 보조 이미지 생성 경로를 사용합니다.

슬라이드 prompt에는 최종 영상에서 아바타가 올라가는 우측 하단 영역을 비워두도록 safe zone 정보가 포함됩니다.

---

# 교수 아바타 처리

강의 생성 시 portrait 이미지는 Ditto 입력 전에 background preparation 단계를 거칩니다.

기본 설정:

```env
AVATAR_INPUT_MODE=auto
AVATAR_CHROMA_COLOR=auto
AVATAR_CHROMA_SIMILARITY=0.12
AVATAR_CHROMA_BLEND=0.06
BACKGROUND_REMOVAL_REQUIRED=true
REMBG_MODEL=u2net_human_seg
```

`AVATAR_INPUT_MODE=auto`에서는 입력 이미지의 투명도 / chroma 특성을 검사해 적절한 전처리 경로를 선택합니다.

배경 제거가 필요한 경우 `rembg`를 이용해 foreground를 만든 뒤 chroma background 위에 합성하고 Ditto에 전달합니다.

최종 영상에서는 FFmpeg `chromakey` filter로 Ditto avatar background를 제거하고 슬라이드 오른쪽 아래에 overlay합니다.

---

# 작업 큐와 GPU worker

## SQLite queue

현재 지원되는 queue backend는 `sqlite`입니다.

```env
JOB_QUEUE_BACKEND=sqlite
```

다른 backend를 설정하면 오류가 발생합니다. Redis adapter는 현재 구현되어 있지 않습니다.

기본 queue 설정:

```env
JOB_CONCURRENCY=4
MAX_RUNNING_JOBS_PER_USER=1
JOB_GPU_IDS=0,1,2,3
JOB_POLL_SECONDS=2
JOB_HEARTBEAT_SECONDS=10
JOB_LEASE_SECONDS=60
JOB_TIMEOUT_SECONDS=7200
JOB_MAX_ATTEMPTS=3
JOB_RETRY_SECONDS=10
```

동작 방식:

- supervisor가 `JOB_CONCURRENCY`만큼 GPU slot을 생성
- queue에서 job lease 획득
- GPU 하나를 할당
- 별도 `core.jobs.runner` process 실행
- runner process tree 전체에 GPU를 고정
- heartbeat로 lease 연장
- timeout / worker crash / lease loss 처리
- retry 가능한 오류는 queue로 재등록
- 동일 사용자의 동시 실행은 `MAX_RUNNING_JOBS_PER_USER`로 제한

`JOB_LEASE_SECONDS`는 `3 × JOB_HEARTBEAT_SECONDS`보다 커야 합니다.

---

# 데이터와 산출물

기본 데이터 디렉터리:

```env
DATA_DIR=data
DATABASE_PATH=./data/ai_prof_lite.db
```

SQLite는 foreign key, WAL mode, busy timeout을 사용합니다.

강의별 파일은 대략 아래 형태로 생성됩니다.

```text
data/
├── ai_prof_lite.db
├── lecture-worker.lock
├── uploads/
│   └── <uuid>.png
└── lectures/
    └── <lecture_id>/
        ├── source/
        │   ├── portrait.png                # AI Instructor 생성 강의의 source
        │   └── lecture_settings.json
        ├── cache/
        │   ├── images/
        │   ├── slides/
        │   └── tts/
        └── runs/
            └── <run_token>/
                ├── lecture_plan.json
                ├── quiz.json
                ├── lecture.pptx
                ├── slides/
                │   └── ... slide PNG files
                ├── audio/
                │   └── slide_XXX.wav
                ├── narration.wav
                ├── slides.mp4
                ├── avatar.mp4
                └── final_lecture.mp4
```

실제 파일명 일부는 stage 구현에 따라 세부적으로 달라질 수 있지만, 모든 실행 결과는 lecture/run 단위로 격리됩니다.

실패하거나 재시도된 이전 run directory는 즉시 재사용하지 않으며, 참조되지 않는 orphan run은 retention 시간이 지난 뒤 정리됩니다.

```env
LECTURE_ORPHAN_RUN_RETENTION_HOURS=24
```

---

# Moodle 연동

Moodle 연결 정보는 사용자별로 저장됩니다.

필수 입력:

- Moodle HTTPS base URL
- Moodle Web Service Token

Moodle client는 redirect를 따라가지 않으며, 등록된 최종 주소에 직접 연결하도록 되어 있습니다.

기본 설정:

```env
MOODLE_TIMEOUT=120
MOODLE_VERIFY_SSL=true
```

외부 Moodle은 기본적으로 HTTPS와 public/global IP를 요구합니다. 내부망 Moodle을 명시적으로 허용해야 하는 운영 환경에서는 코드의 URL policy가 다음 allowlist 설정을 지원합니다.

```env
MOODLE_ALLOWED_ORIGINS=https://moodle.example.com
MOODLE_PRIVATE_ORIGINS=http://10.0.0.20:8080
```

`MOODLE_PRIVATE_ORIGINS`에 등록된 origin에 한해서 private network 주소 및 HTTP 연결을 허용합니다. loopback, link-local, multicast, reserved address는 허용하지 않습니다.

## 사용하는 Moodle Web Service function

표준 Moodle function:

```text
core_webservice_get_site_info
core_enrol_get_users_courses
core_course_get_contents
```

새 VideoTracker activity 생성 기능을 사용하려면 Moodle 쪽에 다음 custom external function이 필요합니다.

```text
mod_videotracker_create_activity
mod_videotracker_set_video
```

기존 VideoTracker에 영상을 연결하는 경우 `mod_videotracker_set_video`가 사용됩니다.

업로드 흐름:

```text
final_lecture.mp4
      │
      ▼
/webservice/upload.php
      │
      ▼
 draft item id
      │
      ▼
mod_videotracker_set_video
      │
      ▼
 VideoTracker
```

---

## Moodle activity 생성의 중복 방지

새 VideoTracker 생성은 비멱등 작업입니다.

따라서 activity 생성 요청의 결과가 불명확한 상태에서 자동 retry로 새 activity를 다시 만들지 않습니다. 코드에서는 `moodle_create` checkpoint를 생성 요청 전에 `running` 상태로 기록합니다.

이 상태에서 장애가 발생하면 Moodle에서 실제 activity 생성 여부를 확인한 뒤 아래 스크립트로 CMID를 연결할 수 있습니다.

```bash
python scripts/resolve_deployment.py --lecture-id <LECTURE_ID> --cmid <CMID>
```

CMID가 해당 Moodle course에 실제 존재하는지 검증한 뒤 lecture 또는 예약 게시 작업을 재개합니다.

---

# AI Instructor

AI Instructor는 정해진 학기 일정에 맞춰 AI가 Moodle 강좌/섹션/강의 주제를 선택하고 강의를 미리 생성한 뒤 게시 시점에 Moodle에 업로드하는 기능입니다.

설정 가능한 주요 항목:

- 활성화 여부
- timezone
- 게시 요일
- 게시 시각
- lead time
- 주당 생성 제한
- 학기 시작일
- 총 학기 주차
- 전체 Moodle 강좌 또는 선택된 강좌만 사용
- 운영 지침
- Text / Image / TTS model 및 voice
- 목표 강의시간
- 목표 슬라이드 수
- 이미지 생성 여부
- AI Instructor 전용 avatar

AI Instructor는 최근 생성된 자동 강의 제목을 참고해 중복을 피하고, 현재 학기 주차를 기준으로 강의 난이도와 주제를 결정하도록 prompt가 구성되어 있습니다.

기본 polling / recovery 설정:

```env
AI_INSTRUCTOR_POLL_SECONDS=60
AI_INSTRUCTOR_LEASE_SECONDS=180
AI_INSTRUCTOR_HEARTBEAT_SECONDS=30
AI_INSTRUCTOR_MAX_ATTEMPTS=3
AI_INSTRUCTOR_RETRY_MINUTES=10
AI_INSTRUCTOR_CATCHUP_GRACE_MINUTES=120
```

`AI_INSTRUCTOR_CATCHUP_GRACE_MINUTES`는 서버가 중단되었다가 다시 실행됐을 때 지나간 최근 예약 슬롯을 복구할 수 있는 범위입니다.

---

# 예약 게시 scheduler

AI Instructor가 생성한 강의는 영상 제작을 먼저 끝낸 뒤, 실제 게시 예정 시간까지 Moodle upload를 보류할 수 있습니다.

worker의 `deploy` stage는 publish schedule이 존재하면 Moodle에 즉시 업로드하지 않고 종료합니다. 이후 publish scheduler가 해당 예약을 독점적으로 처리합니다.

기본 설정:

```env
LECTURE_PUBLISH_POLL_SECONDS=30
LECTURE_PUBLISH_MAX_ATTEMPTS=3
LECTURE_PUBLISH_RETRY_MINUTES=15
LECTURE_PUBLISH_LEASE_SECONDS=180
LECTURE_PUBLISH_HEARTBEAT_SECONDS=30
LECTURE_PUBLISH_TIMEZONE=Asia/Seoul
```

---

# 보안 관련 구현

현재 코드에는 다음 보호 장치가 포함되어 있습니다.

- Argon2 password hashing
- session 기반 인증
- CSRF token 검증
- 로그인 IP/account 단위 in-process rate limit
- production session cookie `Secure`
- optional Trusted Host middleware
- security headers middleware
- request body size 제한
- portrait MIME / 실제 이미지 형식 검증
- portrait decompression bomb 방어
- API credential Fernet 암호화
- OpenAI / Moodle credential 저장 전 연결 검증
- Moodle URL validation 및 redirect 차단
- user_id 기반 lecture/credential 접근 분리
- worker lease token을 이용한 stale runner write 방지

`.env`, runtime DB, generated media, Ditto checkpoint는 Git에 commit하지 않도록 `.gitignore`에 포함되어 있습니다.

---

# 주요 환경변수

## 필수 / 핵심

| 변수 | 기본값 | 설명 |
|---|---|---|
| `SESSION_SECRET` | 없음 | 32자 이상 session secret, 필수 |
| `CREDENTIAL_MASTER_KEY` | 없음 | Fernet credential encryption key, 필수 |
| `OPENAI_KEY_MODE` | `user` | `user` 또는 `server` |
| `SERVER_OPENAI_API_KEY` | 없음 | server mode에서 필수 |
| `DATA_DIR` | `data` | runtime data directory |
| `DATABASE_PATH` | `./data/ai_prof_lite.db` | SQLite DB path |
| `APP_HOST` | `0.0.0.0` | bind host |
| `APP_PORT` | `8001` | bind port |
| `APP_ENV` | `development` | `production`이면 secure cookie 사용 |
| `TRUSTED_HOSTS` | 빈 값 | comma-separated allowed hosts |
| `REGISTRATION_CODE` | 빈 값 | 설정 시 회원가입에 공용 가입 코드 요구 |

## Lecture / OpenAI

| 변수 | 기본값 |
|---|---|
| `LECTURE_TEXT_MODEL` | `gpt-5.1` |
| `LECTURE_IMAGE_MODEL` | `gpt-image-2` |
| `LECTURE_TTS_MODEL` | `gpt-4o-mini-tts` |
| `LECTURE_TTS_VOICE` | `alloy` |
| `LECTURE_TARGET_DURATION_MINUTES` | `40` |
| `LECTURE_TARGET_SLIDE_COUNT` | `10` |
| `LECTURE_DURATION_GENERATION_RATIO` | `1.05` |
| `LECTURE_DURATION_MAX_RETRIES` | `3` |
| `LECTURE_RENDER_SLIDES_WITH_IMAGE_MODEL` | `true` |
| `OPENAI_SLIDE_IMAGE_QUALITY` | `high` |
| `OPENAI_TIMEOUT_SECONDS` | `120` |
| `LECTURE_TTS_CHUNK_CHARS` | `3900` |

## Worker

| 변수 | 기본값 |
|---|---|
| `JOB_QUEUE_BACKEND` | `sqlite` |
| `JOB_CONCURRENCY` | `4` |
| `MAX_RUNNING_JOBS_PER_USER` | `1` |
| `JOB_GPU_IDS` | concurrency에 따라 `0..N-1` |
| `JOB_POLL_SECONDS` | `2` |
| `JOB_HEARTBEAT_SECONDS` | `10` |
| `JOB_LEASE_SECONDS` | `60` |
| `JOB_TIMEOUT_SECONDS` | `7200` |
| `JOB_MAX_ATTEMPTS` | `3` |
| `JOB_RETRY_SECONDS` | `10` |

## Ditto / media

| 변수 | 기본값 |
|---|---|
| `DITTO_ROOT` | `core/ditto-talkinghead` |
| `DITTO_DATA_ROOT` | `core/ditto-talkinghead/checkpoints/ditto_trt_Ampere_Plus` |
| `DITTO_CFG_PKL` | `core/ditto-talkinghead/checkpoints/ditto_cfg/v0.4_hubert_cfg_trt.pkl` |
| `DITTO_PYTHON` | application Python |
| `FFMPEG_BIN` | `ffmpeg` |
| `FFPROBE_BIN` | `ffprobe` |
| `MEDIA_PROCESS_TIMEOUT_SECONDS` | `3600` |
| `LECTURE_ORPHAN_RUN_RETENTION_HOURS` | `24` |

---

# 테스트

개발 의존성을 설치한 뒤:

```bash
pytest
```

또는:

```bash
python -m pytest
```

`pytest.ini`에서 `tests/`를 기본 test path로 사용하며, bundled Ditto source는 test discovery 대상에서 제외됩니다.

주요 테스트 범위:

- 인증
- route 권한 / 응답
- queue / worker
- GPU config
- planner
- narration
- slide 생성
- chroma/background 관련 unit logic
- cleanup
- publishing
- AI Instructor scheduler
- version metadata
- pipeline checkpoint 동작

---

# Troubleshooting

## `SESSION_SECRET must be a random secret...`

`.env`의 `SESSION_SECRET`이 없거나 짧거나 example placeholder입니다.

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

생성한 값으로 교체하세요.

---

## `CREDENTIAL_MASTER_KEY is not configured.`

Fernet key를 생성해 `.env`에 지정하세요.

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

---

## `Missing Ditto files`

아래 항목을 확인하세요.

```text
DITTO_ROOT/inference.py
DITTO_DATA_ROOT
DITTO_CFG_PKL
portrait image
narration audio
```

먼저 다음 명령으로 설정을 점검할 수 있습니다.

```bash
python scripts/preflight.py
```

---

## Ditto가 잘못된 Python으로 실행됨

`.env`에 Ditto conda environment의 Python 절대 경로를 지정하세요.

```env
DITTO_PYTHON=/absolute/path/to/conda/envs/ditto/bin/python
```

---

## GPU가 한 장인데 worker가 시작되지 않음

기본 concurrency가 4이므로 GPU 한 장 환경에서는 다음처럼 변경하세요.

```env
JOB_CONCURRENCY=1
JOB_GPU_IDS=0
```

---

## `JOB_LEASE_SECONDS must be greater than 3 * JOB_HEARTBEAT_SECONDS`

예를 들어 아래 조합은 정상입니다.

```env
JOB_HEARTBEAT_SECONDS=10
JOB_LEASE_SECONDS=60
```

---

## `Another lecture worker supervisor is already running`

이미 같은 `DATA_DIR`을 사용하는 app/worker가 실행 중입니다.

`app.py` 자체가 worker를 포함하므로 별도의 `python worker.py`를 중복 실행하지 않았는지 확인하세요.

---

## 강의가 실패 후 다시 실행되지 않음

lecture detail 화면에서 실패한 작업에 대해 retry를 요청할 수 있습니다.

checkpoint가 정상이라면 완료된 stage는 건너뛰고 실패 지점부터 이어집니다.

---

## Moodle 새 activity 생성 결과가 불명확함

Moodle에서 실제 VideoTracker 생성 여부를 확인한 뒤 CMID를 사용해 복구합니다.

```bash
python scripts/resolve_deployment.py --lecture-id <LECTURE_ID> --cmid <CMID>
```

이 스크립트는 CMID가 해당 강좌에 존재하는지 확인한 뒤 재시도 상태로 전환합니다.

---

## Moodle 연결 실패

다음을 확인하세요.

- URL이 최종 HTTPS 주소인지
- Web Service가 활성화되어 있는지
- token이 유효한지
- 필요한 standard/custom external function 권한이 있는지
- 서버에서 Moodle host로 outbound HTTPS 연결이 가능한지
- TLS 인증서가 유효한지

개발 환경에서만 TLS 검증을 끌 수 있지만 권장하지 않습니다.

```env
MOODLE_VERIFY_SSL=false
```

---

# 프로젝트 구조

```text
.
├── app.py                         # FastAPI entrypoint + schedulers + embedded worker
├── worker.py                      # GPU job supervisor
├── core/
│   ├── config.py                  # 공통 환경설정
│   ├── database/                  # SQLite, migrations, secret encryption
│   ├── jobs/                      # queue abstraction, SQLite queue, runner
│   ├── moodle/                    # low-level Moodle REST client
│   ├── openai/                    # OpenAI client / realtime helper
│   └── ditto-talkinghead/         # bundled Ditto source (checkpoint 제외)
├── modules/
│   ├── auth/                      # login/register/session/rate limit
│   ├── credentials/               # OpenAI/Moodle/etc credential UI/storage
│   ├── dashboard/
│   ├── image/                     # OpenAI image generation helper
│   ├── instructor/                # AI Instructor profile/agent/scheduler
│   ├── lecture/                   # lecture pipeline, media, queue integration
│   ├── moodle/                    # Moodle course/VideoTracker service
│   └── users/
├── scripts/
│   ├── preflight.py
│   ├── resolve_deployment.py
│   ├── avatar_input_smoke.py
│   └── chroma_smoke.py
├── templates/                     # Jinja2 UI
├── static/
├── tests/
├── requirements.txt
├── requirements-dev.txt
├── requirements-full.txt
├── environment.yaml              # Ditto conda environment
├── .env.example
└── LICENSE
```

---

# 운영 시 주의사항

- runtime DB와 생성 미디어는 기본적으로 로컬 filesystem에 저장됩니다.
- app process를 여러 개 띄우는 구조가 필요하면 embedded worker singleton, SQLite queue/data directory, scheduler ownership을 고려한 별도 배포 설계가 필요합니다.
- OpenAI API, Image API, TTS 사용에는 사용량에 따른 비용이 발생할 수 있습니다.
- Ditto/TensorRT 성능과 호환성은 GPU 세대, CUDA, NVIDIA driver, TensorRT 환경에 영향을 받습니다.
- Moodle custom VideoTracker external function은 Moodle 서버 측에 별도로 제공되어야 합니다.
- `CREDENTIAL_MASTER_KEY`는 DB backup과 함께 안전하게 보관해야 합니다.
- `.env`, DB, checkpoint, 생성 미디어는 repository에 commit하지 마세요.

---

# 라이선스

이 저장소의 원본 AI Professor Lite source code는 현재 공식 open-source license가 지정되지 않은 상태입니다.

사용, 수정, 재배포, 상업적 이용에 대한 조건은 반드시 [`LICENSE`](./LICENSE)를 확인하세요.

Ditto TalkingHead 및 기타 third-party component는 각각 upstream license와 사용 조건을 따릅니다.
