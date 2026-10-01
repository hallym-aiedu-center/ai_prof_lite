from __future__ import annotations

DEFAULT_LANGUAGE = "ko"
AUTO_LANGUAGE = "auto"

# Keep this small and explicit. Language packs live under core/lang/xml/<code>.xml.
SUPPORTED_LANGUAGES: dict[str, str] = {
    "ko": "한국어",
    "en": "English",
    "ja": "日本語",
    "zh": "中文",
}

LANGUAGE_ALIASES: dict[str, str] = {
    "ko": "ko",
    "ko-kr": "ko",
    "en": "en",
    "en-us": "en",
    "en-gb": "en",
    "ja": "ja",
    "ja-jp": "ja",
    "zh": "zh",
    "zh-cn": "zh",
    "zh-sg": "zh",
    "zh-hans": "zh",
    "zh-tw": "zh",
    "zh-hk": "zh",
    "zh-hant": "zh",
}
