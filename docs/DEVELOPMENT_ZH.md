[한국어](./DEVELOPMENT.md) | [English](./DEVELOPMENT_EN.md) | [日本語](./DEVELOPMENT_JA.md) | **中文**

# 开发者指南

[README](../README_ZH.md) | [安装与运维](./INSTALLATION_ZH.md) | [参与贡献](../CONTRIBUTING_ZH.md)

## 课程生成流程

```text
课程主题 / 要求 / 参考资料 / 教师图片
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

Pipeline stage:

| Stage | 作用 |
|---|---|
| `plan` | 生成课程结构、narration、Quiz |
| `images` | 生成幻灯片视觉素材 |
| `slides` | 生成 PPTX 和幻灯片 PNG |
| `narration` | 生成 TTS 并验证实际时长 |
| `timeline` | 根据 narration 时长生成幻灯片视频 |
| `avatar` | 生成 Ditto 教师虚拟形象视频 |
| `compose` | 合成幻灯片、虚拟形象和音频 |
| `deploy` | 发布到 Moodle |

已完成的 stage 会记录为 checkpoint。重试时，如果该 stage 仍有有效输出，则会直接复用。

---

## 多语言

UI 支持语言:

| Code | 语言 |
|---|---|
| `ko` | 한국어 |
| `en` | English |
| `ja` | 日本語 |
| `zh` | 中文 |

语言选择优先级:

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
规范化为支持的语言
          │
          ▼
没有匹配时使用 ko
```

新账户的默认值为 `auto`。

### 文件结构

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

Jinja 公共设置:

```text
core/templates.py
```

顶部语言选择器:

```text
templates/base.html
static/language-selector.js
```

### 在模板中添加字符串

模板中面向用户显示的文本使用 translation key 管理。

```jinja2
<h1>{{ t("dashboard.title") }}</h1>
<button>{{ t("common.save") }}</button>
```

XML 中需要为所有语言添加相同的 key。

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

动态值:

```xml
<string name="lecture.hello_user">안녕하세요, {name}님.</string>
```

```jinja2
{{ t("lecture.hello_user", name=user.name) }}
```

如果所选语言中没有该 key，则使用 `ko`；如果 `ko` 中也没有，则直接返回 key 字符串。

### 添加新语言

例如添加法语 `fr` 时:

1. 添加 `core/lang/xml/fr.xml`。
2. 填入与现有 XML 相同的 key。
3. 在 `core/lang/config.py` 的 `SUPPORTED_LANGUAGES` 中添加 `fr`。
4. 在 `LANGUAGE_ALIASES` 中添加需要的 locale alias。
5. 渲染全部模板并检查是否存在缺失 key。

XML loader 使用缓存。开发过程中修改 XML 后若没有立即生效，请重启应用程序。

### CSP

本项目不允许 inline JavaScript event handler。

会被 CSP 阻止的 inline event handler 示例:

```html
<select onchange="this.form.submit()">
```

事件处理应在静态 JS 中注册。

```javascript
select.addEventListener("change", () => {
    select.form?.submit();
});
```

保持 CSP 启用，并在静态 JavaScript 中注册事件处理。

---

## 测试

```bash
python -m pytest
```

单独运行测试:

```bash
python -m pytest tests/test_pipeline.py
python -m pytest tests/test_worker.py
python -m pytest tests/test_security.py
```

修改代码后的最低检查项:

```bash
python scripts/preflight.py
python -m pytest
```

---

## 项目结构

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
