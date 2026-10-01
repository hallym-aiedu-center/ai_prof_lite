[한국어](./README.MD) | [English](./README_EN.MD) | [日本語](./README_JA.MD) | **中文**

# AI Professor Lite

> Version `1.0.0`

AI Professor Lite 是一个 self-hosted 课程制作应用，用一套流程完成课程规划、幻灯片、语音、教师头像视频、最终 MP4 合成以及 Moodle 发布。

Web UI 基于 FastAPI，任务管理使用 SQLite 队列。耗时的媒体任务由按 GPU 隔离的 runner 执行。OpenAI 用于课程规划、图片、TTS 和参考资料 RAG，Ditto TalkingHead 用于生成教师头像视频。


## 界面与生成示例

仪表盘可以集中查看连接状态、正在生成的课程、Ditto 引擎状态以及最近的任务。

<p align="center">
  <img src="docs/images/dashboard.png" alt="AI Professor Lite 仪表盘" width="100%">
</p>

课程详情页会显示当前生成 stage 和进度。生成完成后，可以下载 PPTX、最终课程 MP4、narration WAV、Quiz JSON 等产物，并同时支持桌面端与移动端布局。

<table>
  <tr>
    <td width="72%"><img src="docs/images/lecture-progress-desktop.png" alt="课程生成进度 - 桌面端"></td>
    <td width="28%"><img src="docs/images/lecture-progress-mobile.png" alt="课程生成进度 - 移动端"></td>
  </tr>
  <tr>
    <td align="center"><sub>桌面端课程详情 / 生成进度</sub></td>
    <td align="center"><sub>移动端课程详情</sub></td>
  </tr>
</table>

实际生成流程会创建幻灯片和讲解音频，使用 Ditto TalkingHead 驱动教师图片，然后通过 FFmpeg 将它们合成为一个最终课程视频。

<table>
  <tr>
    <td width="60%"><img src="docs/images/generated-slide.png" alt="生成的课程幻灯片示例"></td>
    <td width="40%"><img src="docs/images/professor-avatar-source.png" alt="教师头像源图片示例"></td>
  </tr>
  <tr>
    <td align="center"><sub>生成的课程幻灯片</sub></td>
    <td align="center"><sub>用于 TalkingHead 生成的教师图片</sub></td>
  </tr>
</table>

**PPT / 幻灯片 + narration + TalkingHead → `final_lecture.mp4`**

> 仓库只保留用于 README 的轻量静态图片。生成的 MP4、WAV 等大型产物由应用的课程详情页进行管理。

---

## 主要功能

- 用户注册 / 登录和用户级数据隔离
- 韩语 / 英语 / 日语 / 中文 UI
- 自动检测浏览器语言，并支持用户固定语言
- 用户级 OpenAI BYOK 或服务器共用 API Key
- PDF / TXT / Markdown / DOCX / PPTX 参考资料
- 参考资料全文输入或 embedding RAG
- 课程方案、幻灯片结构、narration、Quiz 生成
- GPT Image 幻灯片图片生成
- PowerPoint (`.pptx`) 和 1920×1080 PNG 输出
- OpenAI TTS 课程音频
- 根据目标课程时长自动补充 narration
- Ditto TalkingHead 教师头像视频
- 背景移除 / chroma key 预处理
- FFmpeg 最终 MP4 合成
- PPT 检查、批准、修改和继续执行
- Moodle course / section / VideoTracker 集成
- AI Instructor 学期级自动课程生成和定时发布
- SQLite lease queue、retry、heartbeat、checkpoint 恢复
- 多 GPU worker
- 用户级 OpenAI 用量查看

---

## 环境要求

### Docker

- Linux
- Docker Engine
- NVIDIA Driver
- NVIDIA Container Toolkit
- Git
- Git LFS
- OpenSSL
- NVIDIA GPU

宿主机验证命令：

```bash
nvidia-smi
docker run --rm --gpus all nvidia/cuda:12.1.1-base-ubuntu22.04 nvidia-smi
```

### 手动安装

- Linux / POSIX
- Python 3.10
- FFmpeg / FFprobe
- NVIDIA GPU + CUDA / TensorRT
- SQLite

应用和 Ditto 在同一个 Python 3.10 环境中运行。

---

# 快速开始

## Docker

Docker 安装通过 `setup.sh` 或 `setup_en.sh` 完成。

```bash
git clone <REPOSITORY_URL>
cd ai_prof_lite

chmod +x setup.sh
./setup.sh
```

如需英文安装提示：

```bash
chmod +x setup_en.sh
./setup_en.sh
```

安装脚本会处理：

- Docker / GPU / 必要命令检查
- Ditto checkpoint 准备
- `.env` 创建和必需 secret 设置
- OpenAI Key 模式选择
- 根据 GPU 数量配置 worker
- Docker image build
- GPU passthrough 检查
- 检查已有容器
- 选择持久化数据目录并 bind mount 到 `/app/data`
- HTTP readiness 检查

默认值：

```text
Container    : ai-prof-lite
Image        : ai-prof-lite:latest
Internal     : 8002
Runtime      : Python 3.10
Runtime path : /opt/conda/envs/runtime/bin/python
Data default : <project>/data
```

外部端口和持久化数据目录可在安装过程中选择。在数据目录提示处直接按 Enter 会使用项目的 `data/` 目录。

非交互安装示例：

```bash
EXTERNAL_PORT=18002 \
DATA_DIR=/srv/ai-prof-lite-data \
SETUP_OPENAI_KEY_MODE=user \
SETUP_JOB_CONCURRENCY=1 \
./setup.sh
```

主要 override：

```text
EXTERNAL_PORT
SETUP_OPENAI_KEY_MODE
SETUP_JOB_CONCURRENCY
IMAGE_NAME
CONTAINER_NAME
ENV_FILE
DATA_DIR
```

常用命令：

```bash
docker logs -f ai-prof-lite
docker exec ai-prof-lite nvidia-smi
docker restart ai-prof-lite
```

---

# 手动安装

## 1. Python 3.10 环境

应用和 Ditto 在同一个 Python 3.10 环境中运行。

```bash
conda env create -f environment.yaml
conda activate ditto

python --version
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

开发 / 测试依赖：

```bash
python -m pip install -r requirements-dev.txt
```

不需要单独的应用 Python 环境，也不需要额外设置 `DITTO_PYTHON`。`app.py` 和 Ditto inference 使用当前激活的 Python 环境。

## 2. Ditto checkpoint

默认目录：

```text
core/ditto-talkinghead/
└── checkpoints/
    ├── ditto_trt_Ampere_Plus/
    └── ditto_cfg/
        └── v0.4_hubert_cfg_trt.pkl
```

环境变量：

```env
DITTO_ROOT=core/ditto-talkinghead
DITTO_DATA_ROOT=core/ditto-talkinghead/checkpoints/ditto_trt_Ampere_Plus
DITTO_CFG_PKL=core/ditto-talkinghead/checkpoints/ditto_cfg/v0.4_hubert_cfg_trt.pkl
```

## 3. `.env`

```bash
cp .env.example .env
```

生成必需 secret：

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

```env
SESSION_SECRET=<random-secret>
CREDENTIAL_MASTER_KEY=<fernet-key>
```

保存 credential 后如果修改 `CREDENTIAL_MASTER_KEY`，原有 credential 将无法解密。

## 4. Preflight

```bash
python scripts/preflight.py
```

## 5. 启动

```bash
python app.py
```

默认地址：

```text
http://localhost:8001
```

需要时修改：

```env
APP_HOST=0.0.0.0
APP_PORT=8001
```

开发 reload：

```env
APP_RELOAD=1
```

`app.py` 会在内部启动 lecture worker supervisor。在同一个 `DATA_DIR` 上额外运行 `worker.py` 会产生 worker lock 冲突。

---

# 首次设置

1. 创建账号。
2. 在 Profile 中选择 UI 语言。
3. 在 `API / 连接设置` 中添加 OpenAI credential。
4. 如需 Moodle 发布，添加 Moodle Web Service credential。
5. 创建课程，并按需上传参考资料。
6. 在 PPT review 阶段检查并批准内容。
7. 完成后下载 PPTX、视频、音频、Quiz JSON 等结果。
8. 配置 Moodle 后可发布到 VideoTracker。

---

# 课程生成流程

```text
主题 / 要求 / 参考资料 / 教师图片
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
                    └── Moodle VideoTracker（可选）
```

| Stage | 作用 |
|---|---|
| `plan` | 课程结构、narration、Quiz |
| `images` | 幻灯片视觉素材 |
| `slides` | PPTX 和 PNG |
| `narration` | TTS 和实际时长检查 |
| `timeline` | 根据 narration 生成 slide video |
| `avatar` | Ditto 教师头像视频 |
| `compose` | slide / avatar / audio 合成 |
| `deploy` | Moodle 发布 |

已完成 stage 会记录 checkpoint。重试时会复用仍然有效的结果。

---

# OpenAI 配置

## 用户级 BYOK

```env
OPENAI_KEY_MODE=user
```

每个账号保存自己的 OpenAI API Key。

## 服务器共用 Key

```env
OPENAI_KEY_MODE=server
SERVER_OPENAI_API_KEY=sk-...
```

可设置每账号预算上限：

```env
SERVER_OPENAI_ACCOUNT_BUDGET_USD=
```

Moodle credential 始终按用户保存。

---

# 参考资料

支持格式：

```text
.pdf
.txt
.md
.docx
.pptx
```

默认限制：

```env
MAX_REFERENCE_FILES=5
MAX_REFERENCE_FILE_BYTES=10485760
MAX_REFERENCE_UPLOAD_BYTES=26214400
MAX_REFERENCE_CONTEXT_CHARS=120000
```

RAG：

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

# GPU / Worker

默认：

```env
JOB_CONCURRENCY=4
JOB_GPU_IDS=0,1,2,3
MAX_RUNNING_JOBS_PER_USER=1
```

单 GPU：

```env
JOB_CONCURRENCY=1
JOB_GPU_IDS=0
MAX_RUNNING_JOBS_PER_USER=1
```

`JOB_GPU_IDS` 支持 CUDA index、GPU UUID 和 MIG UUID。

Queue：

```env
JOB_POLL_SECONDS=2
JOB_HEARTBEAT_SECONDS=10
JOB_LEASE_SECONDS=60
JOB_TIMEOUT_SECONDS=7200
JOB_MAX_ATTEMPTS=3
JOB_RETRY_SECONDS=10
```

正常部署使用 `app.py` 启动的 embedded worker。

---

# 目标课程时长

默认：

```env
LECTURE_TARGET_DURATION_MINUTES=40
LECTURE_TARGET_SLIDE_COUNT=10
LECTURE_DURATION_GENERATION_RATIO=1.05
LECTURE_DURATION_MAX_RETRIES=3
```

TTS 完成后会测量实际音频时长。低于目标时会自动补充 narration。

---

# Moodle

Moodle 使用用户级 Web Service credential。

支持：

- course 查询
- section 查询
- VideoTracker 查询
- 连接到现有 activity
- 新建 VideoTracker activity
- 发布已完成课程
- AI Instructor 定时发布

不配置 Moodle 也可以正常生成课程。

---

# AI Instructor

AI Instructor 根据学期计划安排课程生成。

- Moodle course 选择
- 课程日期计算
- 教师头像管理
- 自动课程生成
- 运行 / 失败状态跟踪
- Moodle 定时发布
- 服务中断后的 catch-up

```env
AI_INSTRUCTOR_CATCHUP_GRACE_MINUTES=120
```

---

# 多语言

UI 支持：

| Code | 语言 |
|---|---|
| `ko` | 한국어 |
| `en` | English |
| `ja` | 日本語 |
| `zh` | 中文 |

语言选择顺序：

```text
用户设置
    │
    ├── ko / en / ja / zh
    │
    └── auto
          │
          ▼
Browser Accept-Language
          │
          ▼
映射到支持的语言
          │
          ▼
无匹配时使用 ko
```

新账号默认是 `auto`。

## 文件结构

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

Jinja 公共配置：

```text
core/templates.py
```

顶部语言选择器：

```text
templates/base.html
static/language-selector.js
```

## 添加 UI 文本

template 中的用户可见文本通过 translation key 管理。

```jinja2
<h1>{{ t("dashboard.title") }}</h1>
<button>{{ t("common.save") }}</button>
```

所有语言文件添加相同 key。

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

支持 named placeholder：

```xml
<string name="lecture.hello_user">你好，{name}。</string>
```

```jinja2
{{ t("lecture.hello_user", name=user.name) }}
```

当前语言缺少 key 时 fallback 到 `ko`；`ko` 也没有时返回 key 本身。

## 添加语言

以法语 `fr` 为例：

1. 添加 `core/lang/xml/fr.xml`
2. 保持与现有语言文件相同的 key 集合
3. 在 `core/lang/config.py` 的 `SUPPORTED_LANGUAGES` 中添加 `fr`
4. 按需在 `LANGUAGE_ALIASES` 中添加 locale alias
5. 渲染 template 并检查缺失 key

XML loader 使用 cache。开发时修改 XML 后如果没有立即生效，重启应用。

## CSP

禁止 inline JavaScript event handler。

CSP 会阻止的 inline event handler 示例：

```html
<select onchange="this.form.submit()">
```

事件通过静态 JavaScript 注册：

```javascript
select.addEventListener("change", () => {
    select.form?.submit();
});
```

CSP 保持启用，UI 事件通过静态 JavaScript 绑定。

---

# 数据

默认数据库：

```text
data/ai_prof_lite.db
```

课程结果：

```text
data/lectures/<lecture_id>/
```

上传文件和 AI Instructor 数据也存放在 `DATA_DIR` 下。

Docker 安装脚本会询问持久化数据的保存目录。默认使用项目的 `data/`，并将所选宿主机目录 bind mount 到容器的 `/app/data`。非交互安装时可以通过 `DATA_DIR` 环境变量指定路径。

应用会在 `DATA_DIR` 下创建所需的数据文件和子目录。请备份实际选择的数据目录以及 `.env`。

---

# 安全

- Argon2 密码哈希
- Session cookie
- CSRF 验证
- Fernet credential 加密
- Trusted Host
- Content Security Policy
- 上传大小限制
- 用户级访问控制

生产环境：

```env
APP_ENV=production
TRUSTED_HOSTS=example.com,www.example.com
```

`SESSION_SECRET` 和 `CREDENTIAL_MASTER_KEY` 是通过 `.env` 管理的 runtime secret。

---

# 测试

```bash
python -m pytest
```

示例：

```bash
python -m pytest tests/test_pipeline.py
python -m pytest tests/test_worker.py
python -m pytest tests/test_security.py
```

部署前至少运行：

```bash
python scripts/preflight.py
python -m pytest
```

---

# 故障排查

## `Another lecture worker supervisor is already running`

同一个 `DATA_DIR` 已有 worker。

```bash
cat data/lecture-worker.lock
ps -fp "$(cat data/lecture-worker.lock)"
```

或：

```bash
fuser -v data/lecture-worker.lock
```

正常结束旧进程后再启动 `app.py`。

`lecture-worker.lock` 由 `flock` 管理。持有 lock 的进程仍在运行时，仅删除文件不会释放 active lock。

## 找不到 Ditto 文件

检查：

```env
DITTO_ROOT=core/ditto-talkinghead
DITTO_DATA_ROOT=core/ditto-talkinghead/checkpoints/ditto_trt_Ampere_Plus
DITTO_CFG_PKL=core/ditto-talkinghead/checkpoints/ditto_cfg/v0.4_hubert_cfg_trt.pkl
```

## GPU 数量与 worker 配置不一致

单 GPU：

```env
JOB_CONCURRENCY=1
JOB_GPU_IDS=0
```

## 无法解密已保存 credential

确认保存 credential 后是否修改过 `CREDENTIAL_MASTER_KEY`。

---

# 项目结构

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

# 许可证

Apache License 2.0。详见 [`LICENSE`](./LICENSE)。
