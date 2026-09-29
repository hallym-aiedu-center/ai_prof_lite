from typing import Any

from core.openai.usage_ledger import _field, _jsonable
from core.openai.usage_pricing import (
    _IMAGE_RATES,
    _embedding_rate,
    _json_override,
    _normalize_model,
    _number,
    _text_rate,
)

def _request_id(response: Any) -> str | None:
    for key in ("request_id", "_request_id"):
        value = _field(response, key, None)
        if value:
            return str(value)
    http_response = _field(response, "http_response", None) or _field(response, "response", None)
    headers = _field(http_response, "headers", {})
    if isinstance(headers, dict):
        for key in ("x-request-id", "openai-request-id"):
            if headers.get(key):
                return str(headers[key])
    return None


def _pricing_snapshot(kind: str, model: str, extra: dict | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"kind": kind, "model": model}
    if kind == "responses":
        rate = _text_rate(model)
        if rate:
            payload["rates"] = {
                "input_per_million": rate.input_per_million,
                "cached_input_per_million": rate.cached_input_per_million,
                "output_per_million": rate.output_per_million,
            }
    elif kind == "embeddings":
        rate = _embedding_rate(model)
        if rate is not None:
            payload["rates"] = {"input_per_million": rate}
    elif kind == "images":
        rates = _IMAGE_RATES.get(_normalize_model(model))
        override = _json_override("image", model)
        if override:
            rates = (
                _number(override.get("text_input")),
                _number(override.get("image_input")),
                _number(override.get("image_output")),
            )
        if rates:
            payload["rates"] = {
                "text_input_per_million": rates[0],
                "image_input_per_million": rates[1],
                "image_output_per_million": rates[2],
            }
    elif kind == "tts":
        base = _normalize_model(model)
        if base == "gpt-4o-mini-tts":
            payload["rates"] = {
                "input_per_million": 0.60,
                "output_per_million": 12.0,
            }
        elif base == "tts-1":
            payload["rates"] = {"per_million_characters": 15.0}
        elif base == "tts-1-hd":
            payload["rates"] = {"per_million_characters": 30.0}
    if extra:
        payload.update(_jsonable(extra))
    return payload
