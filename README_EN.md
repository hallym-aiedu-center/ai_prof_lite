[한국어](./README.md) | **English** | [日本語](./README_JA.md) | [中文](./README_ZH.md)

# AI Professor Lite

> Version `1.0.0`

AI Professor Lite is a self-hosted lecture production application that handles lecture planning, slides, audio, professor avatar video, final MP4 production, and Moodle publishing in a single workflow.

It uses a FastAPI-based web UI and a SQLite job queue, while media generation tasks run in independent runners for each GPU. OpenAI is used for lecture planning, images, TTS, and reference-material RAG, and Ditto TalkingHead is used to generate professor avatar videos.

## Screenshots and Output Examples

The dashboard shows connection status, lectures in progress, Ditto engine status, and recent jobs at a glance.

<p align="center">
  <img src="docs/images/dashboard.png" alt="AI Professor Lite dashboard" width="100%">
</p>

The lecture detail page shows the current generation stage and progress. After completion, outputs such as PPTX, the final lecture MP4, narration WAV, and Quiz JSON can be downloaded. Both desktop and mobile UIs are supported.

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

### Lecture Video Generation Flow

AI Professor Lite combines generated PPT/slides, TTS audio (`narration.wav`), and a Ditto TalkingHead created from a professor image with FFmpeg to produce the final lecture video, `final_lecture.mp4`.

<table>
  <tr>
    <td width="52%"><img src="docs/images/generated-slide.png" alt="Generated lecture slide example"></td>
    <td width="14%" align="center"><img src="docs/images/narration-wav.png" alt="narration.wav audio" width="120"></td>
    <td width="34%"><img src="docs/images/professor-avatar-source.png" alt="Professor image used for Ditto TalkingHead"></td>
  </tr>
  <tr>
    <td align="center"><sub>PPT / generated lecture slide</sub></td>
    <td align="center"><sub><code>narration.wav</code></sub></td>
    <td align="center"><sub>Professor image for Ditto TalkingHead</sub></td>
  </tr>
</table>

<p align="center"><strong>PPT / Slides + Audio + TalkingHead → <code>final_lecture.mp4</code></strong></p>

<p align="center">
  <img src="docs/images/final-lecture-preview.png" alt="Final lecture video frame with PPT and TalkingHead composited" width="100%">
</p>

<p align="center"><sub>Example frame from an actual generated lecture video — slides and TalkingHead are composited into a single video.</sub></p>


AI Professor Preview: [https://aiproflite.k-university.ai/](https://aiproflite.k-university.ai/)

Moodle Integration Plugin: [Link coming soon]

Generated Video Preview: https://ailms.k-university.ai/login/index.php

---

## Features

- Sign-up / login and per-user data separation
- Korean / English / Japanese / Chinese UI
- Automatic browser-language detection and persistent user language selection
- Per-user OpenAI BYOK or a shared server API key
- PDF / TXT / Markdown / DOCX / PPTX reference materials
- Full-context reference input or embedding-based RAG
- Lecture plan, slide structure, narration, and Quiz generation
- GPT Image-based slide image generation
- PowerPoint (`.pptx`) and 1920×1080 slide PNG generation
- OpenAI TTS-based lecture audio generation
- Automatic narration expansion to match target lecture duration
- Professor avatar video generation with Ditto TalkingHead
- Background removal / chroma key preprocessing
- Final lecture MP4 composition with FFmpeg
- PPT review, approval / revision / resume
- Moodle course / section / SimpleVideoTracker integration
- Semester-based automatic lecture generation and scheduled publishing with AI Instructor
- SQLite lease queue, retry, heartbeat, and checkpoint recovery
- Multi-GPU workers
- Per-user OpenAI usage tracking

---

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
git clone https://github.com/hallym-aied/AI_Prof_lite.git ai_prof_lite
cd ai_prof_lite

chmod +x setup.sh
./setup.sh
```

English setup script:

```bash
chmod +x setup_en.sh
./setup_en.sh
```

For detailed Docker installation, manual installation, environment variables, GPU/Worker settings, data and security, and troubleshooting, see [`docs/INSTALLATION_EN.md`](./docs/INSTALLATION_EN.md).

---

## Initial Setup

1. Create an account.
2. Choose the default language in your profile.
3. Register your OpenAI credential under `API / Connection Settings`.
4. If you use Moodle, register your Moodle Web Service information.
5. Create a new lecture and attach reference materials if needed.
6. Review the slides at the PPT review stage and approve them.
7. After generation completes, download outputs such as PPTX, video, audio, and Quiz JSON.
8. If Moodle is configured, publish the lecture to SimpleVideoTracker.

---

## Documentation

- [Installation & Operations](./docs/INSTALLATION_EN.md)
- [Developer Guide](./docs/DEVELOPMENT_EN.md)
- [Contributing](./CONTRIBUTING_EN.md)

---

## Moodle

Moodle integration uses per-user Web Service credentials.

Supported flow:

- Course lookup
- Section lookup
- SimpleVideoTracker lookup
- Attach a video to an existing activity
- Create a new SimpleVideoTracker activity
- Publish immediately after lecture generation
- Scheduled publishing with AI Instructor

Lecture generation works even without Moodle.

---

## AI Instructor

AI Instructor plans lectures according to the semester schedule and schedules generation jobs.

Main features:

- Select the Moodle course to manage
- Calculate lecture schedules
- Manage professor avatars
- Automatically generate upcoming lectures
- Track failed / interrupted jobs
- Schedule Moodle publishing
- Catch up after a server restart

Recovery grace period:

```env
AI_INSTRUCTOR_CATCHUP_GRACE_MINUTES=120
```

---

## Support

Please use GitHub Issues for bug reports and feature requests.

---

## Project and Contributors

AI Professor Lite is an **open-source project led by students**. Technical advice and project support were provided during development.

### Current Contributors

| GitHub | Role |
|---|---|
| [@Iamjunseok](https://github.com/Iamjunseok) | Developer / Collaborator |
| [@waitinghm-creator](https://github.com/waitinghm-creator) | Developer / Collaborator |
| [@hero707](https://github.com/hero707) | Technical Advisor / Project Support |
| [@hallymgitoslab](https://github.com/hallymgitoslab) | Project Support / Contributor |

---

## Acknowledgement

This research was supported by the ANCHOR program(Glocal University30) through the Gangwon ANCHOR Center, funded by the Ministry of Education(MOE) and the Gangwon State(G.S.),Republic of Korea.(2026-ANCHOR-10-009)

---

## License

Apache License 2.0. See [`LICENSE`](./LICENSE) for the full license text.
