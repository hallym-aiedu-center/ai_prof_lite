from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TokenRate:
    input_per_million: float
    output_per_million: float = 0.0
    cached_input_per_million: float = 0.0


_TEXT_RATES = {
    "gpt-5.1": TokenRate(1.25, 10.0, 0.125),
    "gpt-5": TokenRate(1.25, 10.0, 0.125),
    "gpt-4.1": TokenRate(2.0, 8.0, 0.50),
    "gpt-4o-mini": TokenRate(0.15, 0.60, 0.075),
}
_EMBEDDING_RATES = {
    "text-embedding-3-small": 0.02,
    "text-embedding-3-large": 0.13,
}
_TTS_MODELS = ("gpt-4o-mini-tts", "tts-1-hd", "tts-1")

_IMAGE_RATES = {
    # text input / image input / image output, USD per 1M tokens
    "gpt-image-2": (2.5, 4.0, 15.0),
    "gpt-image-1": (5.0, 10.0, 40.0),
}
_IMAGE_OUTPUT_PRICE = {
    "gpt-image-2": {
        "low": {"1024x1024": 0.006, "1024x1536": 0.005, "1536x1024": 0.005},
        "medium": {"1024x1024": 0.053, "1024x1536": 0.041, "1536x1024": 0.041},
        "high": {"1024x1024": 0.211, "1024x1536": 0.165, "1536x1024": 0.165},
    },
    "gpt-image-1": {
        "low": {"1024x1024": 0.011, "1024x1536": 0.016, "1536x1024": 0.016},
        "medium": {"1024x1024": 0.042, "1024x1536": 0.063, "1536x1024": 0.063},
        "high": {"1024x1024": 0.167, "1024x1536": 0.250, "1536x1024": 0.250},
    },
}


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _positive_float_env(name: str, default: float) -> float:
    value = _number(os.getenv(name, default))
    return value if value > 0 else float(default)


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _normalize_model(model: str) -> str:
    value = str(model or "").strip()
    families = sorted(
        {*_TEXT_RATES, *_EMBEDDING_RATES, *_IMAGE_RATES, *_TTS_MODELS},
        key=len,
        reverse=True,
    )
    for base in families:
        if value == base or value.startswith(base + "-"):
            return base
    return value


def _json_override(kind: str, model: str) -> dict | None:
    raw = os.getenv("OPENAI_PRICING_JSON", "").strip()
    if not raw:
        return None
    try:
        payload = json.loads(raw)
        item = payload.get(kind, {}).get(model) or payload.get(kind, {}).get(_normalize_model(model))
        return item if isinstance(item, dict) else None
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def _text_rate(model: str) -> TokenRate | None:
    override = _json_override("text", model)
    if override:
        return TokenRate(
            _number(override.get("input")),
            _number(override.get("output")),
            _number(override.get("cached_input")),
        )
    return _TEXT_RATES.get(_normalize_model(model))


def _embedding_rate(model: str) -> float | None:
    override = _json_override("embedding", model)
    if override:
        return _number(override.get("input"))
    return _EMBEDDING_RATES.get(_normalize_model(model))


def _rough_tokens(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        return max(1, math.ceil(len(value) / 3.0)) if value else 0
    if isinstance(value, bytes):
        return max(1, math.ceil(len(value) / 2.0)) if value else 0
    if isinstance(value, dict):
        return sum(_rough_tokens(key) + _rough_tokens(item) for key, item in value.items())
    if isinstance(value, (list, tuple, set)):
        return sum(_rough_tokens(item) for item in value)
    return _rough_tokens(str(value))
