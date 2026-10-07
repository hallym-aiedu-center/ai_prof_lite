[한국어](./README.md) | [English](./README_EN.md) | [日本語](./README_JA.md) | **中文**

# AI Professor Lite

> Version `1.0.0`

AI Professor Lite 是一款自托管的课程制作应用，可在一个工作流程中完成课程规划、幻灯片、语音、教师头像视频、最终 MP4 制作以及 Moodle 发布。

它使用基于 FastAPI 的 Web UI 和 SQLite 任务队列，媒体生成等较重的任务会在每块 GPU 对应的独立 runner 中运行。OpenAI 用于课程结构、图像、TTS 和参考资料 RAG，Ditto TalkingHead 用于生成教师头像视频。

## 界面与生成示例

在仪表板中可以一览连接状态、正在生成的课程、Ditto 引擎状态和最近任务。

<p align="center">
  <img src="docs/images/dashboard.png" alt="AI Professor Lite 仪表板" width="100%">
</p>

在课程详情页面可以查看当前生成 stage 和进度。生成完成后，可以下载 PPTX、最终课程 MP4、narration WAV、Quiz JSON 等输出文件。桌面端和移动端 UI 均受支持。

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

### 实际课程视频生成流程

AI Professor Lite 将生成的 PPT/幻灯片、TTS 音频（`narration.wav`）以及基于教师图片生成的 Ditto TalkingHead 通过 FFmpeg 合成为最终课程视频 `final_lecture.mp4`。

<table>
  <tr>
    <td width="52%"><img src="docs/images/generated-slide.png" alt="生成的课程幻灯片示例"></td>
    <td width="14%" align="center"><img src="docs/images/narration-wav.png" alt="narration.wav 音频" width="120"></td>
    <td width="34%"><img src="docs/images/professor-avatar-source.png" alt="用于生成 TalkingHead 的教师图片"></td>
  </tr>
  <tr>
    <td align="center"><sub>PPT / 生成的课程幻灯片</sub></td>
    <td align="center"><sub><code>narration.wav</code></sub></td>
    <td align="center"><sub>Ditto TalkingHead 教师图片</sub></td>
  </tr>
</table>

<p align="center"><strong>PPT / 幻灯片 + 音频 + TalkingHead → <code>final_lecture.mp4</code></strong></p>

<p align="center">
  <img src="docs/images/final-lecture-preview.png" alt="PPT 与 TalkingHead 合成后的最终课程视频画面" width="100%">
</p>

<p align="center"><sub>实际最终课程视频画面示例 — 幻灯片与 TalkingHead 会被合成为一个视频。</sub></p>



AI 教师预览: [https://aiproflite.k-university.ai/](https://aiproflite.k-university.ai/)
测试账号:
- Email: `test@mentorix.kr`
- Password: `Test00**`

Moodle 集成插件: [链接准备中]

生成视频预览: https://ailms.k-university.ai/login/index.php
测试账号:
- Username: `testuser`
- Password: `Test00**`

---

## 主要功能

- 注册 / 登录以及按用户隔离数据
- 韩语 / 英语 / 日语 / 中文 UI
- 自动检测浏览器语言，并固定用户语言设置
- 用户自带 OpenAI API Key（BYOK）或服务器共享 API Key
- 支持 PDF / TXT / Markdown / DOCX / PPTX 参考资料
- 参考资料全文输入或基于 embedding 的 RAG
- 生成课程方案、幻灯片结构、narration 和 Quiz
- 基于 GPT Image 生成幻灯片图片
- 生成 PowerPoint（`.pptx`）和 1920×1080 幻灯片 PNG
- 基于 OpenAI TTS 生成课程音频
- 根据目标课程时长自动补充 narration
- 基于 Ditto TalkingHead 生成教师头像视频
- 背景移除 / chroma key 预处理
- 基于 FFmpeg 合成最终课程 MP4
- PPT 审阅后批准 / 修改 / 恢复
- Moodle course / section / SimpleVideoTracker 集成
- 基于 AI Instructor 的学期级自动课程生成和定时发布
- SQLite lease queue、retry、heartbeat、checkpoint 恢复
- 多 GPU worker
- 按用户查看 OpenAI 使用量

---

## 环境要求

### Docker 安装

- Linux
- Docker Engine
- NVIDIA Driver
- NVIDIA Container Toolkit
- Git
- Git LFS
- OpenSSL
- NVIDIA GPU（Ampere 或更新架构）

主机上必须能够正常执行以下两条命令。

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

应用和 Ditto 在同一个 Python 3.10 环境中运行。

---

## 快速开始

### Docker 安装

Docker 安装以 `setup.sh` 或 `setup_en.sh` 为准。

```bash
git clone https://github.com/hallym-aiedu-center/ai_prof_lite.git ai_prof_lite
cd ai_prof_lite

chmod +x setup.sh
./setup.sh

cd ai_prof_lite

chmod +x setup.sh
./setup.sh
```

英文安装脚本：

```bash
chmod +x setup_en.sh
./setup_en.sh
```

有关 Docker 详细安装、手动安装、环境变量、GPU/Worker 设置、数据与安全以及故障排除，请参阅 [`docs/INSTALLATION_ZH.md`](./docs/INSTALLATION_ZH.md)。

---

## 初始设置

1. 创建账户。
2. 在个人资料中选择默认语言。
3. 在 `API / 连接设置` 中注册 OpenAI credential。
4. 如果使用 Moodle，请注册 Moodle Web Service 信息。
5. 创建新课程，并在需要时附加参考资料。
6. 在 PPT 审阅阶段检查幻灯片并批准。
7. 生成完成后，下载 PPTX、视频、音频、Quiz JSON 等输出文件。
8. 如果已配置 Moodle，可发布到 SimpleVideoTracker。

---

## 文档

- [安装与运维](./docs/INSTALLATION_ZH.md)
- [开发者指南](./docs/DEVELOPMENT_ZH.md)
- [贡献指南](./CONTRIBUTING_ZH.md)

---

## Moodle

Moodle 集成使用每个用户各自的 Web Service credential。

支持流程：

- 查询 course
- 查询 section
- 查询 SimpleVideoTracker
- 将视频连接到现有 activity
- 创建新的 SimpleVideoTracker activity
- 课程完成后立即发布
- AI Instructor 定时发布

即使不使用 Moodle，课程生成功能也可以正常工作。

---

## AI Instructor

AI Instructor 会根据学期日程自动规划课程并安排生成任务。

主要功能：

- 选择负责的 Moodle course
- 计算课程日程
- 管理教师头像
- 自动生成计划课程
- 跟踪失败 / 中断状态
- Moodle 定时发布
- 服务器重启后的 catch-up

恢复宽限时间：

```env
AI_INSTRUCTOR_CATCHUP_GRACE_MINUTES=120
```

---

## 支持

错误报告和功能建议请使用 GitHub Issues。

---

## 项目与贡献者

AI Professor Lite 是一个**由学生主导开发的开源项目**。开发过程中得到了技术指导和项目支持。

### 当前贡献者

| GitHub | 角色 |
|---|---|
| [@Iamjunseok](https://github.com/Iamjunseok) | 开发者 / Collaborator |
| [@waitinghm-creator](https://github.com/waitinghm-creator) | 开发者 / Collaborator |
| [@hero707](https://github.com/hero707) | 技术顾问 / 项目支持 |
| [@hallymgitoslab](https://github.com/hallymgitoslab) | 项目支持 / Contributor |

---

## 支持与致谢



This research was supported by the ANCHOR program(Glocal University30) through the Gangwon ANCHOR Center, funded by the Ministry of Education(MOE) and the Gangwon State(G.S.),Republic of Korea.(2026-ANCHOR-10-009)

---

## 许可证

Apache License 2.0。完整许可证内容请参阅 [`LICENSE`](./LICENSE)。
