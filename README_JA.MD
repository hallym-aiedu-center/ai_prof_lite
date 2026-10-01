[한국어](./README.MD) | [English](./README_EN.MD) | **日本語** | [中文](./README_ZH.MD)

# AI Professor Lite

> Version `1.0.0`

AI Professor Lite は、講義設計、スライド、音声、教授アバター動画、最終 MP4 の合成、Moodle 配信までを一つの流れで扱う self-hosted 講義制作アプリケーションです。

Web UI は FastAPI、ジョブ管理は SQLite ベースのキューを使用します。時間のかかるメディア生成処理は GPU ごとの独立 runner で実行します。OpenAI は講義設計、画像、TTS、参考資料 RAG に使用し、Ditto TalkingHead は教授アバター動画の生成に使用します。


## 画面と生成例

ダッシュボードでは、接続状態、生成中の講義、Ditto エンジンの状態、最近のジョブを一画面で確認できます。

<p align="center">
  <img src="docs/images/dashboard.png" alt="AI Professor Lite ダッシュボード" width="100%">
</p>

講義詳細画面では、現在の生成 stage と進捗率を確認できます。生成完了後は PPTX、最終講義 MP4、narration WAV、Quiz JSON などの成果物をダウンロードできます。デスクトップとモバイルの両方に対応しています。

<table>
  <tr>
    <td width="72%"><img src="docs/images/lecture-progress-desktop.png" alt="講義生成の進捗画面 - デスクトップ"></td>
    <td width="28%"><img src="docs/images/lecture-progress-mobile.png" alt="講義生成の進捗画面 - モバイル"></td>
  </tr>
  <tr>
    <td align="center"><sub>デスクトップの講義詳細 / 生成進捗</sub></td>
    <td align="center"><sub>モバイルの講義詳細</sub></td>
  </tr>
</table>

### 実際の講義動画生成フロー

AI Professor Lite は、生成した PPT / スライド、TTS 音声（`narration.wav`）、教授画像から生成した Ditto TalkingHead を FFmpeg で合成し、最終講義動画 `final_lecture.mp4` を生成します。

<table>
  <tr>
    <td width="52%"><img src="docs/images/generated-slide.png" alt="生成された講義スライドの例"></td>
    <td width="14%" align="center"><img src="docs/images/narration-wav.png" alt="narration.wav 音声" width="120"></td>
    <td width="34%"><img src="docs/images/professor-avatar-source.png" alt="TalkingHead 生成に使用する教授画像"></td>
  </tr>
  <tr>
    <td align="center"><sub>PPT / 生成された講義スライド</sub></td>
    <td align="center"><sub><code>narration.wav</code></sub></td>
    <td align="center"><sub>Ditto TalkingHead 用の教授画像</sub></td>
  </tr>
</table>

<p align="center"><strong>PPT / スライド + 音声 + TalkingHead → <code>final_lecture.mp4</code></strong></p>

<p align="center">
  <img src="docs/images/final-lecture-preview.png" alt="スライドと TalkingHead を合成した最終講義動画のフレーム" width="100%">
</p>

<p align="center"><sub>最終講義動画の実例フレーム — スライドと TalkingHead が一つの動画として合成されます。</sub></p>

> リポジトリには README 用の軽量な静止画像例のみを含めます。生成された MP4 や WAV などの大容量成果物は、アプリケーションの講義詳細画面で管理します。

---

## 主な機能

- アカウント登録 / ログインとユーザー単位のデータ分離
- 韓国語 / 英語 / 日本語 / 中国語 UI
- ブラウザ言語の自動判定とユーザー設定による固定
- ユーザー別 OpenAI BYOK またはサーバー共通 API Key
- PDF / TXT / Markdown / DOCX / PPTX 参考資料
- 参考資料全文入力または embedding ベース RAG
- 講義構成、スライド構成、narration、Quiz 生成
- GPT Image によるスライド画像生成
- PowerPoint (`.pptx`) と 1920×1080 PNG 出力
- OpenAI TTS による講義音声生成
- 目標講義時間に合わせた narration 自動補強
- Ditto TalkingHead による教授アバター動画
- 背景除去 / chroma key 前処理
- FFmpeg による最終 MP4 合成
- PPT レビュー、承認、修正、処理再開
- Moodle course / section / VideoTracker 連携
- AI Instructor による学期単位の自動講義生成と予約配信
- SQLite lease queue、retry、heartbeat、checkpoint 復旧
- マルチ GPU worker
- ユーザー別 OpenAI 使用量表示

---

## 必要環境

### Docker

- Linux
- Docker Engine
- NVIDIA Driver
- NVIDIA Container Toolkit
- Git
- Git LFS
- OpenSSL
- NVIDIA GPU

ホストで次のコマンドが動作する必要があります。

```bash
nvidia-smi
docker run --rm --gpus all nvidia/cuda:12.1.1-base-ubuntu22.04 nvidia-smi
```

### 手動インストール

- Linux / POSIX
- Python 3.10
- FFmpeg / FFprobe
- NVIDIA GPU + CUDA / TensorRT
- SQLite

アプリケーションと Ditto は同じ Python 3.10 環境で実行します。

---

# クイックスタート

## Docker

Docker 導入は `setup.sh` または `setup_en.sh` を使用します。

```bash
git clone <REPOSITORY_URL>
cd ai_prof_lite

chmod +x setup.sh
./setup.sh
```

英語のセットアップメッセージを使う場合:

```bash
chmod +x setup_en.sh
./setup_en.sh
```

セットアップスクリプトは次を処理します。

- Docker / GPU / 必須コマンド確認
- Ditto checkpoint 準備
- `.env` 作成と必須 secret 設定
- OpenAI Key 運用方式の選択
- GPU 数に合わせた worker 設定
- Docker image build
- GPU passthrough 確認
- 既存コンテナの存在確認
- 永続データ保存先の選択と `/app/data` への bind mount
- HTTP readiness 確認

既定値:

```text
Container    : ai-prof-lite
Image        : ai-prof-lite:latest
Internal     : 8002
Runtime      : Python 3.10
Runtime path : /opt/conda/envs/runtime/bin/python
Data default : <project>/data
```

外部ポートと永続データ保存先はセットアップ中に選択できます。データ保存先の入力で Enter を押すと、プロジェクトの `data/` ディレクトリを使用します。

非対話実行例:

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

状態確認:

```bash
docker logs -f ai-prof-lite
docker exec ai-prof-lite nvidia-smi
docker restart ai-prof-lite
```

---

# 手動インストール

## 1. Python 3.10 環境

アプリケーションと Ditto は 1 つの Python 3.10 環境で実行します。

```bash
conda env create -f environment.yaml
conda activate ditto

python --version
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

開発 / テスト依存関係:

```bash
python -m pip install -r requirements-dev.txt
```

アプリケーション用の別 Python 環境や個別の `DITTO_PYTHON` 設定は不要です。有効化した Python 環境で `app.py` と Ditto inference を実行します。

## 2. Ditto checkpoint

既定の配置:

```text
core/ditto-talkinghead/
└── checkpoints/
    ├── ditto_trt_Ampere_Plus/
    └── ditto_cfg/
        └── v0.4_hubert_cfg_trt.pkl
```

環境変数:

```env
DITTO_ROOT=core/ditto-talkinghead
DITTO_DATA_ROOT=core/ditto-talkinghead/checkpoints/ditto_trt_Ampere_Plus
DITTO_CFG_PKL=core/ditto-talkinghead/checkpoints/ditto_cfg/v0.4_hubert_cfg_trt.pkl
```

## 3. `.env`

```bash
cp .env.example .env
```

必須 secret を生成します。

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

```env
SESSION_SECRET=<random-secret>
CREDENTIAL_MASTER_KEY=<fernet-key>
```

credential 保存後に `CREDENTIAL_MASTER_KEY` を変更すると、既存 credential は復号できません。

## 4. Preflight

```bash
python scripts/preflight.py
```

## 5. 起動

```bash
python app.py
```

既定 URL:

```text
http://localhost:8001
```

必要に応じて変更します。

```env
APP_HOST=0.0.0.0
APP_PORT=8001
```

開発時 reload:

```env
APP_RELOAD=1
```

`app.py` は lecture worker supervisor を内部で起動します。同じ `DATA_DIR` で別の `worker.py` を実行すると worker lock が競合します。

---

# 初回設定

1. アカウントを作成します。
2. Profile で UI 言語を選択します。
3. `API / 接続設定` で OpenAI credential を登録します。
4. Moodle を使う場合は Moodle Web Service credential を登録します。
5. 講義を作成し、必要なら参考資料を添付します。
6. PPT review で内容を確認して承認します。
7. 完了後、PPTX、動画、音声、Quiz JSON などを取得します。
8. Moodle が設定されていれば VideoTracker へ配信できます。

---

# 講義生成パイプライン

```text
トピック / 要件 / 参考資料 / 教授画像
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
                    └── Moodle VideoTracker（任意）
```

| Stage | 内容 |
|---|---|
| `plan` | 講義構成、narration、Quiz |
| `images` | スライド視覚素材 |
| `slides` | PPTX と PNG |
| `narration` | TTS と実時間検証 |
| `timeline` | narration に合わせた slide video |
| `avatar` | Ditto 教授アバター動画 |
| `compose` | slide / avatar / audio 合成 |
| `deploy` | Moodle 配信 |

完了済み stage は checkpoint に記録され、retry 時には有効な成果物を再利用します。

---

# OpenAI 設定

## ユーザー別 BYOK

```env
OPENAI_KEY_MODE=user
```

各アカウントが自分の OpenAI API Key を登録します。

## サーバー共通 Key

```env
OPENAI_KEY_MODE=server
SERVER_OPENAI_API_KEY=sk-...
```

必要に応じてアカウント単位の予算上限を設定できます。

```env
SERVER_OPENAI_ACCOUNT_BUDGET_USD=
```

Moodle credential は OpenAI 設定に関係なくユーザー単位です。

---

# 参考資料

対応形式:

```text
.pdf
.txt
.md
.docx
.pptx
```

既定制限:

```env
MAX_REFERENCE_FILES=5
MAX_REFERENCE_FILE_BYTES=10485760
MAX_REFERENCE_UPLOAD_BYTES=26214400
MAX_REFERENCE_CONTEXT_CHARS=120000
```

RAG:

```env
REFERENCE_RAG_CHUNK_CHARS=2600
REFERENCE_RAG_CHUNK_OVERLAP_CHARS=260
REFERENCE_RAG_TOP_K=16
REFERENCE_RAG_MAX_CHUNKS=0
REFERENCE_EMBEDDING_BATCH_SIZE=64
REFERENCE_EMBEDDING_MODEL=text-embedding-3-small
```

`REFERENCE_RAG_MAX_CHUNKS=0` は chunk 数無制限です。

---

# GPU / Worker

既定:

```env
JOB_CONCURRENCY=4
JOB_GPU_IDS=0,1,2,3
MAX_RUNNING_JOBS_PER_USER=1
```

GPU 1枚:

```env
JOB_CONCURRENCY=1
JOB_GPU_IDS=0
MAX_RUNNING_JOBS_PER_USER=1
```

`JOB_GPU_IDS` は CUDA index、GPU UUID、MIG UUID に対応します。

Queue:

```env
JOB_POLL_SECONDS=2
JOB_HEARTBEAT_SECONDS=10
JOB_LEASE_SECONDS=60
JOB_TIMEOUT_SECONDS=7200
JOB_MAX_ATTEMPTS=3
JOB_RETRY_SECONDS=10
```

通常運用では `app.py` の embedded worker を使用します。

---

# 目標講義時間

既定値:

```env
LECTURE_TARGET_DURATION_MINUTES=40
LECTURE_TARGET_SLIDE_COUNT=10
LECTURE_DURATION_GENERATION_RATIO=1.05
LECTURE_DURATION_MAX_RETRIES=3
```

TTS 生成後に実際の音声時間を測定し、目標より短い場合は narration を補強します。

---

# Moodle

Moodle はユーザー別 Web Service credential を使用します。

対応処理:

- course 取得
- section 取得
- VideoTracker 取得
- 既存 activity への動画接続
- 新規 VideoTracker activity 作成
- 完了講義の配信
- AI Instructor からの予約配信

Moodle を設定しなくても講義生成は利用できます。

---

# AI Instructor

AI Instructor は学期スケジュールに合わせて講義生成を予約します。

- Moodle course 選択
- 講義日程計算
- 教授アバター管理
- 講義自動生成
- 実行 / 失敗状態追跡
- Moodle 予約配信
- サーバー停止後の catch-up

```env
AI_INSTRUCTOR_CATCHUP_GRACE_MINUTES=120
```

---

# 多言語対応

UI 対応言語:

| Code | 言語 |
|---|---|
| `ko` | 한국어 |
| `en` | English |
| `ja` | 日本語 |
| `zh` | 中文 |

言語決定順:

```text
ユーザー設定
    │
    ├── ko / en / ja / zh
    │
    └── auto
          │
          ▼
Browser Accept-Language
          │
          ▼
対応言語へ normalize
          │
          ▼
一致しない場合 ko
```

新規アカウントは `auto` が既定です。

## ファイル構成

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

Jinja 共通設定:

```text
core/templates.py
```

ヘッダーの言語 selector:

```text
templates/base.html
static/language-selector.js
```

## UI 文字列の追加

template のユーザー表示文字列は translation key で管理します。

```jinja2
<h1>{{ t("dashboard.title") }}</h1>
<button>{{ t("common.save") }}</button>
```

全 language pack に同じ key を追加します。

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

named placeholder:

```xml
<string name="lecture.hello_user">こんにちは、{name}さん。</string>
```

```jinja2
{{ t("lecture.hello_user", name=user.name) }}
```

選択言語に key がなければ `ko` に fallback し、`ko` にもない場合は key 自体を返します。

## 言語追加

フランス語 `fr` の例:

1. `core/lang/xml/fr.xml` を追加
2. 既存ファイルと同じ key を用意
3. `core/lang/config.py` の `SUPPORTED_LANGUAGES` に追加
4. 必要な locale alias を `LANGUAGE_ALIASES` に追加
5. template をレンダリングして未翻訳 key を確認

XML loader は cache されます。開発中に XML を変更して反映されない場合はアプリケーションを再起動してください。

## CSP

inline JavaScript event handler は禁止されています。

CSP により block される inline event handler の例:

```html
<select onchange="this.form.submit()">
```

static JavaScript 側で event を登録します。

```javascript
select.addEventListener("change", () => {
    select.form?.submit();
});
```

CSP は維持し、UI event は static JavaScript から登録します。

---

# データ

既定 DB:

```text
data/ai_prof_lite.db
```

講義成果物:

```text
data/lectures/<lecture_id>/
```

upload と AI Instructor データも `DATA_DIR` 配下です。

Docker のセットアップスクリプトは永続データの保存先をユーザーに確認します。既定値はプロジェクトの `data/` で、選択した host ディレクトリを container の `/app/data` に bind mount します。非対話セットアップでは `DATA_DIR` 環境変数で指定できます。

アプリケーションは `DATA_DIR` 配下に必要なファイルとサブディレクトリを作成します。実際に選択したデータディレクトリと `.env` をバックアップしてください。

---

# セキュリティ

- Argon2 password hashing
- Session cookie
- CSRF validation
- Fernet credential encryption
- Trusted Host
- Content Security Policy
- Upload size limit
- ユーザー単位 access check

本番環境:

```env
APP_ENV=production
TRUSTED_HOSTS=example.com,www.example.com
```

`SESSION_SECRET` と `CREDENTIAL_MASTER_KEY` は runtime secret として `.env` で管理します。

---

# テスト

```bash
python -m pytest
```

例:

```bash
python -m pytest tests/test_pipeline.py
python -m pytest tests/test_worker.py
python -m pytest tests/test_security.py
```

deploy 前の最低確認:

```bash
python scripts/preflight.py
python -m pytest
```

---

# トラブルシューティング

## `Another lecture worker supervisor is already running`

同じ `DATA_DIR` を使用する worker が既に起動しています。

```bash
cat data/lecture-worker.lock
ps -fp "$(cat data/lecture-worker.lock)"
```

または:

```bash
fuser -v data/lecture-worker.lock
```

既存プロセスを正常終了してから `app.py` を再起動します。

`lecture-worker.lock` は `flock` で管理されます。所有プロセスが動作中の場合、ファイルだけを削除しても active lock は解除されません。

## Ditto file がない

```env
DITTO_ROOT=core/ditto-talkinghead
DITTO_DATA_ROOT=core/ditto-talkinghead/checkpoints/ditto_trt_Ampere_Plus
DITTO_CFG_PKL=core/ditto-talkinghead/checkpoints/ditto_cfg/v0.4_hubert_cfg_trt.pkl
```

を確認してください。

## GPU 数と worker 設定が合わない

GPU 1枚:

```env
JOB_CONCURRENCY=1
JOB_GPU_IDS=0
```

## Credential を復号できない

credential 作成時と現在の `CREDENTIAL_MASTER_KEY` が異なる場合、既存 credential の復号に失敗します。

---

# プロジェクト構成

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

# ライセンス

Apache License 2.0。詳細は [`LICENSE`](./LICENSE) を参照してください。
