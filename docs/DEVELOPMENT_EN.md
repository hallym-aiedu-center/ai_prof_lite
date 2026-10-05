[한국어](./DEVELOPMENT.md) | **English** | [日本語](./DEVELOPMENT_JA.md) | [中文](./DEVELOPMENT_ZH.md)

# Developer Guide

[README](../README_EN.md) | [Installation & Operations](./INSTALLATION_EN.md) | [Contributing](../CONTRIBUTING_EN.md)

## Lecture Generation Flow

```text
Lecture topic / requirements / references / professor image
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

Pipeline stages:

| Stage | Role |
|---|---|
| `plan` | Generate lecture structure, narration, and Quiz |
| `images` | Generate visual assets for slides |
| `slides` | Generate PPTX and slide PNG files |
| `narration` | Generate TTS and verify actual duration |
| `timeline` | Generate slide video based on narration duration |
| `avatar` | Generate the Ditto professor avatar video |
| `compose` | Combine slides, avatar, and audio |
| `deploy` | Deploy to Moodle |

Completed stages are recorded as checkpoints. On retry, a stage is reused if valid output from that stage is still available.

---

## Multilingual Support

Supported UI languages:

| Code | Language |
|---|---|
| `ko` | 한국어 |
| `en` | English |
| `ja` | 日本語 |
| `zh` | 中文 |

Language selection priority:

```text
User setting
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
Fallback to ko if no match
```

The default for new accounts is `auto`.

### File Structure

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

Shared Jinja settings:

```text
core/templates.py
```

Top language selector:

```text
templates/base.html
static/language-selector.js
```

### Adding Strings to Templates

User-facing strings in templates are managed with translation keys.

```jinja2
<h1>{{ t("dashboard.title") }}</h1>
<button>{{ t("common.save") }}</button>
```

Add the same key to every language XML file.

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

Dynamic values:

```xml
<string name="lecture.hello_user">안녕하세요, {name}님.</string>
```

```jinja2
{{ t("lecture.hello_user", name=user.name) }}
```

If a key does not exist in the selected language, the system falls back to `ko`. If it is also missing from `ko`, the key string itself is returned.

### Adding a New Language

For example, to add French `fr`:

1. Add `core/lang/xml/fr.xml`.
2. Fill it with the same keys as the existing XML files.
3. Add `fr` to `SUPPORTED_LANGUAGES` in `core/lang/config.py`.
4. Add the required locale aliases to `LANGUAGE_ALIASES`.
5. Render all templates and check for missing keys.

The XML loader uses a cache. If XML changes do not appear immediately during development, restart the application.

### CSP

The project does not allow inline JavaScript event handlers.

Example of an inline event handler blocked by CSP:

```html
<select onchange="this.form.submit()">
```

Register event handlers in static JavaScript instead.

```javascript
select.addEventListener("change", () => {
    select.form?.submit();
});
```

Keep CSP enabled and register event handling in static JavaScript.

---

## Tests

```bash
python -m pytest
```

Individual tests:

```bash
python -m pytest tests/test_pipeline.py
python -m pytest tests/test_worker.py
python -m pytest tests/test_security.py
```

Minimum checks after modifying code:

```bash
python scripts/preflight.py
python -m pytest
```

---

## Project Structure

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
