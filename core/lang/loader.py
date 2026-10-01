from __future__ import annotations

import xml.etree.ElementTree as ET
from functools import cache
from pathlib import Path

from core.lang.config import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES

XML_DIR = Path(__file__).resolve().parent / "xml"


@cache
def load_language(language: str) -> dict[str, str]:
    code = language if language in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE
    path = XML_DIR / f"{code}.xml"
    tree = ET.parse(path)
    root = tree.getroot()
    return {
        str(node.get("name")): node.text or ""
        for node in root.findall("string")
        if node.get("name")
    }


def translate(key: str, language: str, **values: object) -> str:
    messages = load_language(language)
    text = messages.get(key)
    if text is None and language != DEFAULT_LANGUAGE:
        text = load_language(DEFAULT_LANGUAGE).get(key)
    if text is None:
        text = key

    if values:
        try:
            text = text.format(**values)
        except (KeyError, ValueError, IndexError):
            # A broken translation should not make a page fail to render.
            return text
    return text


def clear_language_cache() -> None:
    load_language.cache_clear()
