import asyncio
import inspect
import io
import math
import wave
from typing import Any

from core.openai.usage_ledger import (
    OpenAIAmbiguousRequestError,
    _field,
    _json_override,
    _jsonable,
    _normalize_model,
    _number,
    _raise_after_provider_error,
    finalize_usage,
    mark_ambiguous_usage,
    reserve_usage,
)
from core.openai.usage_provider_common import _pricing_snapshot, _request_id

def _wav_seconds(content: bytes) -> float:
    try:
        with wave.open(io.BytesIO(content), "rb") as wav:
            return wav.getnframes() / max(1, wav.getframerate())
    except Exception:
        return 0.0


def _tts_usage_cost(model: str, usage: Any) -> tuple[float, dict] | None:
    base = _normalize_model(model)
    if usage is None or base != "gpt-4o-mini-tts":
        return None
    input_tokens = int(_number(_field(usage, "input_tokens")))
    output_tokens = int(_number(_field(usage, "output_tokens")))
    details = _field(usage, "input_tokens_details", {})
    cached = int(_number(_field(details, "cached_tokens")))
    uncached = max(0, input_tokens - cached)
    cost = (uncached * 0.60 + cached * 0.0 + output_tokens * 12.0) / 1_000_000
    return cost, {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_input_tokens": cached,
        "usage": _jsonable(usage),
        "pricing": _pricing_snapshot("tts", model),
        "metadata": {"billing_basis": "speech_usage"},
    }


def tts_cost(model: str, *, text: str, audio_bytes: bytes) -> tuple[float, dict]:
    base = _normalize_model(model)
    if base == "gpt-4o-mini-tts":
        text_tokens = max(1, math.ceil(len(text) / 3.0))
        seconds = _wav_seconds(audio_bytes)
        audio_tokens = max(1, math.ceil(seconds / 60.0 * 1250)) if seconds else max(1, math.ceil(len(audio_bytes) / 48.0))
        cost = text_tokens * 0.60 / 1_000_000 + audio_tokens * 12.0 / 1_000_000
        return cost, {
            "input_tokens": text_tokens,
            "output_tokens": audio_tokens,
            "pricing": _pricing_snapshot("tts", model),
            "metadata": {
                "billing_basis": "derived_audio_duration",
                "audio_seconds": seconds,
            },
        }
    if base == "tts-1":
        return len(text) * 15.0 / 1_000_000, {
            "pricing": _pricing_snapshot("tts", model),
            "metadata": {"billing_basis": "characters", "characters": len(text)}
        }
    if base == "tts-1-hd":
        return len(text) * 30.0 / 1_000_000, {
            "pricing": _pricing_snapshot("tts", model),
            "metadata": {"billing_basis": "characters", "characters": len(text)}
        }
    override = _json_override("tts", model)
    if override and _number(override.get("per_million_characters")):
        return len(text) * _number(override["per_million_characters"]) / 1_000_000, {
            "pricing": _pricing_snapshot("tts", model),
            "metadata": {"billing_basis": "characters", "characters": len(text)}
        }
    raise RuntimeError(f"가격 정보가 없는 OpenAI TTS 모델입니다: {model}")


def _tts_reserve_cost(model: str, text: str) -> float:
    base = _normalize_model(model)
    if base == "gpt-4o-mini-tts":
        text_tokens = max(1, math.ceil(len(text) / 3.0))
        estimate_minutes = max(0.05, len(text) / 700.0)
        audio_tokens = math.ceil(estimate_minutes * 1250)
        return (text_tokens * 0.60 + audio_tokens * 12.0) / 1_000_000 * 1.25
    if base == "tts-1":
        return len(text) * 15.0 / 1_000_000
    if base == "tts-1-hd":
        return len(text) * 30.0 / 1_000_000
    override = _json_override("tts", model)
    if override and _number(override.get("per_million_characters")):
        return len(text) * _number(override["per_million_characters"]) / 1_000_000
    raise RuntimeError(f"가격 정보가 없는 OpenAI TTS 모델입니다: {model}")


async def _read_audio_response(response: Any) -> bytes:
    if hasattr(response, "aread"):
        value = response.aread()
        return await value if inspect.isawaitable(value) else value
    if getattr(response, "content", None) is not None:
        return bytes(response.content)
    if hasattr(response, "read"):
        value = response.read()
        return await value if inspect.isawaitable(value) else value
    raise RuntimeError("Unable to read audio response bytes.")


async def speech_create_bytes(
    client,
    *,
    user_id: int,
    lecture_id: int | None = None,
    usage_context: dict | None = None,
    **kwargs,
) -> bytes:
    model = str(kwargs.get("model") or "")
    text = str(kwargs.get("input") or "")
    context = usage_context or {}
    event = await reserve_usage(
        user_id=user_id,
        lecture_id=lecture_id,
        kind="tts",
        endpoint="audio.speech.create",
        operation=context.get("operation"),
        stage=context.get("stage"),
        item_key=context.get("item_key"),
        item_index=context.get("item_index"),
        metadata=context.get("metadata") or {},
        model=model,
        reserve_usd=_tts_reserve_cost(model, text),
    )
    try:
        response = await client.audio.speech.create(**kwargs)
    except asyncio.CancelledError as exc:
        await mark_ambiguous_usage(event, exc)
        raise
    except Exception as exc:
        await _raise_after_provider_error(event, exc)
    try:
        content = await _read_audio_response(response)
        measured = _tts_usage_cost(model, getattr(response, "usage", None))
        if measured:
            cost, values = measured
            await finalize_usage(event, request_id=_request_id(response), cost_usd=cost, **values)
        else:
            cost, values = tts_cost(model, text=text, audio_bytes=content)
            await finalize_usage(event, request_id=_request_id(response), cost_usd=cost, **values)
    except asyncio.CancelledError as exc:
        await mark_ambiguous_usage(event, exc)
        raise
    except Exception as exc:
        await mark_ambiguous_usage(event, exc)
        raise OpenAIAmbiguousRequestError(
            "OpenAI 요청은 완료됐지만 비용 기록을 확정하지 못해 자동 재시도하지 않습니다."
        ) from exc
    return content
