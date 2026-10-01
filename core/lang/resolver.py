from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from starlette.requests import Request

from core.lang.config import (
    AUTO_LANGUAGE,
    DEFAULT_LANGUAGE,
    LANGUAGE_ALIASES,
    SUPPORTED_LANGUAGES,
)


def normalize_language(value: str | None) -> str | None:
    if not value:
        return None
    code = value.strip().lower().replace("_", "-")
    if code == AUTO_LANGUAGE:
        return AUTO_LANGUAGE
    if code in LANGUAGE_ALIASES:
        return LANGUAGE_ALIASES[code]
    base = code.split("-", 1)[0]
    return LANGUAGE_ALIASES.get(base)


def browser_language(request: Request | None) -> str:
    if request is None:
        return DEFAULT_LANGUAGE

    header = request.headers.get("accept-language", "")
    candidates: list[tuple[float, int, str]] = []
    for index, item in enumerate(header.split(",")):
        part = item.strip()
        if not part:
            continue
        raw_code, *params = [piece.strip() for piece in part.split(";")]
        quality = 1.0
        for param in params:
            if param.startswith("q="):
                try:
                    quality = float(param[2:])
                except ValueError:
                    quality = 0.0
        normalized = normalize_language(raw_code)
        if normalized and normalized != AUTO_LANGUAGE:
            candidates.append((quality, -index, normalized))

    if not candidates:
        return DEFAULT_LANGUAGE
    candidates.sort(reverse=True)
    return candidates[0][2]


def language_preference(user: Mapping[str, Any] | Any | None) -> str:
    value = None
    if isinstance(user, Mapping):
        value = user.get("language")
    elif user is not None:
        value = getattr(user, "language", None)

    normalized = normalize_language(str(value)) if value else None
    return normalized or AUTO_LANGUAGE


def resolve_language(
    request: Request | None, user: Mapping[str, Any] | Any | None = None
) -> str:
    preference = language_preference(user)
    if preference != AUTO_LANGUAGE and preference in SUPPORTED_LANGUAGES:
        return preference
    return browser_language(request)
