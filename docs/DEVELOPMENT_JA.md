[한국어](./DEVELOPMENT.md) | [English](./DEVELOPMENT_EN.md) | **日本語** | [中文](./DEVELOPMENT_ZH.md)

# 開発者ガイド

[README](../README_JA.md) | [インストール・運用](./INSTALLATION_JA.md) | [コントリビューション](../CONTRIBUTING_JA.md)

## 講義生成フロー

```text
講義テーマ / 要求事項 / 参考資料 / 教授画像
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

パイプライン stage:

| Stage | 役割 |
|---|---|
| `plan` | 講義構成、narration、Quiz の生成 |
| `images` | スライド用ビジュアル素材の生成 |
| `slides` | PPTX とスライド PNG の生成 |
| `narration` | TTS の生成と実際の長さの検証 |
| `timeline` | narration の長さに合わせたスライド動画の生成 |
| `avatar` | Ditto 教授アバター動画の生成 |
| `compose` | スライド、アバター、音声の合成 |
| `deploy` | Moodle への配布 |

完了した stage は checkpoint として記録されます。再試行時に有効な生成物が残っていれば、その stage を再利用します。

---

## 多言語

UI 対応言語:

| Code | 言語 |
|---|---|
| `ko` | 한국어 |
| `en` | English |
| `ja` | 日本語 |
| `zh` | 中文 |

言語選択の優先順位:

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
対応言語に正規化
          │
          ▼
一致しない場合は ko
```

新規アカウントのデフォルト値は `auto` です。

### ファイル構造

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

上部の言語セレクター:

```text
templates/base.html
static/language-selector.js
```

### テンプレートに文字列を追加

テンプレート内でユーザーに表示する文言は translation key で管理します。

```jinja2
<h1>{{ t("dashboard.title") }}</h1>
<button>{{ t("common.save") }}</button>
```

XML にはすべての言語で同じ key を追加します。

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

動的な値:

```xml
<string name="lecture.hello_user">안녕하세요, {name}님.</string>
```

```jinja2
{{ t("lecture.hello_user", name=user.name) }}
```

選択した言語に key がない場合は `ko` を使用し、`ko` にもない場合は key 文字列自体を返します。

### 新しい言語を追加

たとえばフランス語 `fr` を追加する場合:

1. `core/lang/xml/fr.xml` を追加します。
2. 既存 XML と同じ key を用意します。
3. `core/lang/config.py` の `SUPPORTED_LANGUAGES` に `fr` を追加します。
4. 必要な locale alias を `LANGUAGE_ALIASES` に追加します。
5. すべてのテンプレートをレンダリングし、欠落した key がないか確認します。

XML loader はキャッシュを使用します。開発中に XML を変更してもすぐ反映されない場合は、アプリケーションを再起動してください。

### CSP

このプロジェクトでは inline JavaScript event handler を許可していません。

CSP によってブロックされる inline event handler の例:

```html
<select onchange="this.form.submit()">
```

イベント処理は静的 JS で登録します。

```javascript
select.addEventListener("change", () => {
    select.form?.submit();
});
```

CSP は維持し、イベント処理は静的 JavaScript で登録してください。

---

## テスト

```bash
python -m pytest
```

個別テスト:

```bash
python -m pytest tests/test_pipeline.py
python -m pytest tests/test_worker.py
python -m pytest tests/test_security.py
```

コード修正後の最低限の確認項目:

```bash
python scripts/preflight.py
python -m pytest
```

---

## プロジェクト構造

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
