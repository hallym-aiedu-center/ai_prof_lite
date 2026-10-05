[한국어](./INSTALLATION.md) | [English](./INSTALLATION_EN.md) | **日本語** | [中文](./INSTALLATION_ZH.md)

# インストール・運用

[README](../README_JA.md) | [開発者ガイド](./DEVELOPMENT_JA.md) | [コントリビューション](../CONTRIBUTING_JA.md)

## 要件

### Docker インストール

- Linux
- Docker Engine
- NVIDIA Driver
- NVIDIA Container Toolkit
- Git
- Git LFS
- OpenSSL
- NVIDIA GPU (Ampere 以降)

ホスト上で次の 2 つのコマンドが正常に実行できる必要があります。

```bash
nvidia-smi
docker run --rm --gpus all nvidia/cuda:12.1.1-base-ubuntu22.04 nvidia-smi
```

### 手動インストール

- Linux / POSIX 環境
- Python 3.10
- FFmpeg / FFprobe
- NVIDIA GPU (Ampere 以降) + CUDA / TensorRT 環境
- SQLite

アプリケーションと Ditto は同じ Python 3.10 環境で実行します。

---

## クイックスタート

### Docker インストール

Docker インストールは `setup.sh` または `setup_en.sh` を基準にします。

```bash
git clone https://github.com/hallym-aied/AI_Prof.git
cd ai_prof_lite

chmod +x setup.sh
./setup.sh
```

英語版インストールスクリプト:

```bash
chmod +x setup_en.sh
./setup_en.sh
```

インストールスクリプトは次の処理を行います。

- Docker / GPU / 必須コマンドの確認
- Ditto checkpoint の準備
- `.env` の作成と必須 secret の設定
- OpenAI Key ポリシーの選択
- GPU 数に合わせた worker 設定
- Docker image の build
- GPU passthrough の確認
- 既存コンテナの有無を確認
- 永続データ保存先の選択と `/app/data` への bind mount
- HTTP readiness の確認

Docker のデフォルト設定:

```text
Container    : ai-prof-lite
Image        : ai-prof-lite:latest
Internal     : 8002
Runtime      : Python 3.10
Runtime path : /opt/conda/envs/runtime/bin/python
Data default : <project>/data
```

外部ポートと永続データの保存先はインストール中に選択できます。データパスの入力で Enter を押すと、プロジェクトの `data/` ディレクトリを使用します。

非対話インストールの例:

```bash
EXTERNAL_PORT=18002 \
DATA_DIR=/srv/ai-prof-lite-data \
SETUP_OPENAI_KEY_MODE=user \
SETUP_JOB_CONCURRENCY=1 \
./setup.sh
```

主な override:

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

#### Reverse proxy / 元のクライアント IP

AI Professor Lite を Nginx、Traefik などの reverse proxy の背後で実行する場合は、`FORWARDED_ALLOW_IPS` に **信頼できる proxy の IP または Docker network の範囲だけ**を指定してください。Uvicorn は信頼済み proxy が渡す `X-Forwarded-For` を使って、`request.client.host` を元のクライアント IP に復元します。

この設定はログインや会員登録などの IP ベース rate limit にも使用されます。Proxy を信頼しない場合、すべてのリクエストが同じ proxy IP から来たように見え、複数ユーザーが 1 つの rate-limit quota を共有することがあります。

Docker ポートを直接公開して使用する基本構成では、デフォルト値を維持してください。

```env
FORWARDED_ALLOW_IPS=127.0.0.1
```

たとえば Nginx が Docker network `172.20.0.0/24` からアプリケーションにアクセスする場合:

```env
FORWARDED_ALLOW_IPS=172.20.0.0/24
```

Nginx の例:

```nginx
location / {
    proxy_pass http://ai-prof-lite:8002;

    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

> **注意:** アプリケーションの `8002` ポートが信頼できないクライアントに直接公開されている場合、`FORWARDED_ALLOW_IPS=*` は使用しないでください。クライアントが `X-Forwarded-For` を偽装し、IP ベースの rate limit を回避できる可能性があります。

---

## 手動インストール

### 1. Python 3.10 環境

アプリケーションと Ditto は 1 つの Python 3.10 環境で一緒に実行します。

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

アプリケーション用の別 Python 環境や別の `DITTO_PYTHON` 設定は必要ありません。現在有効な Python 環境で `app.py` と Ditto inference が一緒に実行されます。

### 2. Ditto checkpoint

デフォルトパス:

```text
core/ditto-talkinghead/
└── checkpoints/
    ├── ditto_trt_Ampere_Plus/
    └── ditto_cfg/
        └── v0.4_hubert_cfg_trt.pkl
```

関連する環境変数:

```env
DITTO_ROOT=core/ditto-talkinghead
DITTO_DATA_ROOT=core/ditto-talkinghead/checkpoints/ditto_trt_Ampere_Plus
DITTO_CFG_PKL=core/ditto-talkinghead/checkpoints/ditto_cfg/v0.4_hubert_cfg_trt.pkl
```

### 3. 環境変数

```bash
cp .env.example .env
```

必須 secret:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

`.env`:

```env
SESSION_SECRET=<random-secret>
CREDENTIAL_MASTER_KEY=<fernet-key>
```

`CREDENTIAL_MASTER_KEY` を変更すると、以前の key で暗号化して保存した credential は復号できなくなります。

### 4. Preflight

```bash
python scripts/preflight.py
```

### 5. 実行

```bash
python app.py
```

デフォルトアドレス:

```text
http://localhost:8001
```

アプリケーションのホストとポートは `.env` で変更できます。

```env
APP_HOST=0.0.0.0
APP_PORT=8001
```

開発環境 reload:

```env
APP_RELOAD=1
```

`app.py` は lecture worker supervisor を内部で起動します。同じ `DATA_DIR` で別に `worker.py` を実行すると worker lock が競合します。

---

## OpenAI 設定

### ユーザー別 BYOK

デフォルトモード:

```env
OPENAI_KEY_MODE=user
```

各アカウントが自分の OpenAI API Key を登録します。

### サーバー共通 Key

```env
OPENAI_KEY_MODE=server
SERVER_OPENAI_API_KEY=sk-...
```

ユーザーごとの予算上限を設定できます。

```env
SERVER_OPENAI_ACCOUNT_BUDGET_USD=
```

Moodle credential は OpenAI Key ポリシーに関係なく常にユーザーごとに保存されます。

---

## 参考資料

対応形式:

```text
.pdf
.txt
.md
.docx
.pptx
```

デフォルト制限:

```env
MAX_REFERENCE_FILES=5
MAX_REFERENCE_FILE_BYTES=10485760
MAX_REFERENCE_UPLOAD_BYTES=26214400
MAX_REFERENCE_CONTEXT_CHARS=120000
```

RAG 設定:

```env
REFERENCE_RAG_CHUNK_CHARS=2600
REFERENCE_RAG_CHUNK_OVERLAP_CHARS=260
REFERENCE_RAG_TOP_K=16
REFERENCE_RAG_MAX_CHUNKS=0
REFERENCE_EMBEDDING_BATCH_SIZE=64
REFERENCE_EMBEDDING_MODEL=text-embedding-3-small
```

`REFERENCE_RAG_MAX_CHUNKS=0` は chunk 数を制限しないことを意味します。

---

## GPU / Worker

デフォルト設定:

```env
JOB_CONCURRENCY=4
JOB_GPU_IDS=0,1,2,3
MAX_RUNNING_JOBS_PER_USER=1
```

GPU が 1 枚の場合:

```env
JOB_CONCURRENCY=1
JOB_GPU_IDS=0
MAX_RUNNING_JOBS_PER_USER=1
```

`JOB_GPU_IDS` には CUDA index、GPU UUID、MIG UUID を使用できます。

作業キュー関連設定:

```env
JOB_POLL_SECONDS=2
JOB_HEARTBEAT_SECONDS=10
JOB_LEASE_SECONDS=60
JOB_TIMEOUT_SECONDS=7200
JOB_MAX_ATTEMPTS=3
JOB_RETRY_SECONDS=10
```

`app.py` が embedded worker を起動するため、通常運用では `worker.py` を別に実行する必要はありません。

---

## 目標講義時間

デフォルト値:

```env
LECTURE_TARGET_DURATION_MINUTES=40
LECTURE_TARGET_SLIDE_COUNT=10
LECTURE_DURATION_GENERATION_RATIO=1.05
LECTURE_DURATION_MAX_RETRIES=3
```

TTS 生成後に実際の音声時間を測定し、目標より短い場合は narration を補強します。

---

## データ

デフォルト DB:

```text
data/ai_prof_lite.db
```

講義の生成物:

```text
data/lectures/<lecture_id>/
```

アップロードファイルと AI Instructor のデータも `DATA_DIR` 配下に保存されます。

Docker インストールスクリプトは永続データの保存先をユーザーに確認します。デフォルトはプロジェクトの `data/` で、選択したホストディレクトリをコンテナの `/app/data` に bind mount します。非対話インストールでは `DATA_DIR` 環境変数でパスを指定できます。

アプリケーションは `DATA_DIR` 配下に必要なデータファイルとサブディレクトリを作成します。実際に選択したデータディレクトリと `.env` がバックアップ対象です。

---

## セキュリティ

- パスワード: Argon2
- Session cookie
- CSRF 検証
- Credential: Fernet 暗号化
- Trusted Host 制限
- Content Security Policy
- アップロードサイズ制限
- ユーザーごとのデータアクセス検証

本番環境:

```env
APP_ENV=production
TRUSTED_HOSTS=example.com,www.example.com

# Reverse proxy を使用する場合のみ、信頼できる proxy IP/network を指定します。
# Docker ポートを直接公開する基本構成では 127.0.0.1 を維持します。
FORWARDED_ALLOW_IPS=127.0.0.1
```

Reverse proxy の背後で運用する場合は、`FORWARDED_ALLOW_IPS` を実際の proxy IP または内部 network 範囲に制限してください。この値は元のクライアント IP の復元と IP ベース rate limit の正確性に影響します。

`SESSION_SECRET` と `CREDENTIAL_MASTER_KEY` は runtime secret であり、`.env` で管理します。

---

## トラブルシューティング

### `Another lecture worker supervisor is already running`

同じ `DATA_DIR` を使用する worker がすでに実行中です。

lock を所有しているプロセスを確認します。

```bash
cat data/lecture-worker.lock
ps -fp "$(cat data/lecture-worker.lock)"
```

または:

```bash
fuser -v data/lecture-worker.lock
```

既存プロセスを正常終了してから `app.py` を再実行してください。

`lecture-worker.lock` は `flock` で管理されます。lock を所有するプロセスが動作している間は、ファイルだけを削除しても active lock は解除されません。

### Ditto ファイルが見つからない

Ditto checkpoint のパスと `.env` 設定を確認してください。

```env
DITTO_ROOT=core/ditto-talkinghead
DITTO_DATA_ROOT=core/ditto-talkinghead/checkpoints/ditto_trt_Ampere_Plus
DITTO_CFG_PKL=core/ditto-talkinghead/checkpoints/ditto_cfg/v0.4_hubert_cfg_trt.pkl
```

### GPU 数と worker 設定が一致しない

GPU が 1 枚の場合は次のように減らします。

```env
JOB_CONCURRENCY=1
JOB_GPU_IDS=0
```

### Credential の復号に失敗する

credential を保存した時点の `CREDENTIAL_MASTER_KEY` と現在の値が異なる場合、既存 credential の復号に失敗します。
