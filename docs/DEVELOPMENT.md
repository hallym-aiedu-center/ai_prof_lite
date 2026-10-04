**한국어** | [English](./DEVELOPMENT_EN.md) | [日本語](./DEVELOPMENT_JA.md) | [中文](./DEVELOPMENT_ZH.md)

# 개발자 가이드

[README](../README.md) | [설치 및 운영](./INSTALLATION.md) | [기여하기](../CONTRIBUTING.md)

## 강의 생성 흐름

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

## 다국어

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

### 파일 구조

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

### 템플릿에 문자열 추가

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

### 새 언어 추가

예를 들어 프랑스어 `fr`을 추가할 경우:

1. `core/lang/xml/fr.xml`을 추가합니다.
2. 기존 XML과 같은 key를 채웁니다.
3. `core/lang/config.py`의 `SUPPORTED_LANGUAGES`에 `fr`을 추가합니다.
4. 필요한 locale alias를 `LANGUAGE_ALIASES`에 추가합니다.
5. 전체 템플릿을 렌더링해 누락 key를 확인합니다.

XML loader는 캐시를 사용합니다. 개발 중 XML을 수정한 뒤 즉시 반영되지 않으면 애플리케이션을 재시작합니다.

### CSP

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

## 테스트

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

## 프로젝트 구조

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
