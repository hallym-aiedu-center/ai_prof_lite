import asyncio
import base64
import inspect
import json
import os
from typing import Any

from core.openai.usage_ledger import (
    OpenAIAmbiguousRequestError,
    _field,
    _jsonable,
    _raise_after_provider_error,
    finalize_usage,
    mark_ambiguous_usage,
    reserve_usage,
)
from core.openai.usage_pricing import _json_override, _normalize_model, _number
from core.openai.usage_provider_common import _pricing_snapshot, _request_id


def _tts_usage_cost(model: str, usage: Any) -> tuple[float, dict]:
    """Calculate finalized TTS cost only from provider-reported usage."""
    base = _normalize_model(model)
    if base != "gpt-4o-mini-tts":
        raise RuntimeError(
            f"토큰 usage 기반 TTS 과금을 지원하지 않는 모델입니다: {model}"
        )
    if usage is None:
        raise RuntimeError("OpenAI Speech 응답에 provider usage가 없습니다.")

    input_tokens = int(_number(_field(usage, "input_tokens")))
    output_tokens = int(_number(_field(usage, "output_tokens")))
    if input_tokens <= 0 and output_tokens <= 0:
        raise RuntimeError("OpenAI Speech provider usage의 token 수가 비어 있습니다.")

    # Speech SSE usage currently reports input/output/total tokens.
    # Keep cached handling defensive in case the provider adds it later.
    details = _field(usage, "input_tokens_details", None)
    if details is None:
        details = _field(usage, "input_token_details", {})
    cached = int(_number(_field(details, "cached_tokens")))
    cached = max(0, min(cached, input_tokens))
    uncached = input_tokens - cached

    cost = (uncached * 0.60 + cached * 0.0 + output_tokens * 12.0) / 1_000_000
    return cost, {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_input_tokens": cached,
        "usage": _jsonable(usage),
        "pricing": _pricing_snapshot("tts", model),
        "metadata": {
            "billing_basis": "speech_usage",
            "usage_source": "provider",
        },
    }


def tts_cost(model: str, *, text: str, audio_bytes: bytes) -> tuple[float, dict]:
    """Compatibility helper for character-billed legacy TTS models only.

    gpt-4o-mini-tts MUST be finalized from provider-reported Speech SSE usage;
    deriving tokens from text length, audio duration, or byte length is forbidden.
    """
    del audio_bytes
    base = _normalize_model(model)
    if base == "gpt-4o-mini-tts":
        raise RuntimeError(
            "gpt-4o-mini-tts 비용은 provider의 speech.audio.done usage로만 확정합니다."
        )
    if base == "tts-1":
        return len(text) * 15.0 / 1_000_000, {
            "pricing": _pricing_snapshot("tts", model),
            "metadata": {
                "billing_basis": "characters",
                "characters": len(text),
                "usage_source": "request_exact",
            },
        }
    if base == "tts-1-hd":
        return len(text) * 30.0 / 1_000_000, {
            "pricing": _pricing_snapshot("tts", model),
            "metadata": {
                "billing_basis": "characters",
                "characters": len(text),
                "usage_source": "request_exact",
            },
        }
    override = _json_override("tts", model)
    if override and _number(override.get("per_million_characters")):
        return len(text) * _number(override["per_million_characters"]) / 1_000_000, {
            "pricing": _pricing_snapshot("tts", model),
            "metadata": {
                "billing_basis": "characters",
                "characters": len(text),
                "usage_source": "request_exact",
            },
        }
    raise RuntimeError(f"가격 정보가 없는 OpenAI TTS 모델입니다: {model}")


def _tts_reserve_cost(model: str, text: str) -> float:
    """Pre-request budget hold only; never written as finalized token usage."""
    base = _normalize_model(model)
    if base == "gpt-4o-mini-tts":
        # This is only a temporary budget reservation. Final accounting always
        # comes from speech.audio.done provider usage.
        raw = os.getenv("OPENAI_TTS_RESERVE_USD", "0.10")
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = 0.10
        return max(0.01, value)
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


def _parse_speech_sse(payload: bytes) -> tuple[bytes, dict]:
    """Extract audio bytes and exact provider usage from Speech API SSE."""
    if not payload:
        raise RuntimeError("OpenAI Speech SSE 응답이 비어 있습니다.")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError("OpenAI Speech 응답이 SSE 형식이 아닙니다.") from exc

    audio_parts: list[bytes] = []
    usage: dict | None = None

    # SSE records are separated by a blank line. Accept both LF and CRLF.
    normalized = text.replace("\r\n", "\n")
    for block in normalized.split("\n\n"):
        data_lines: list[str] = []
        for line in block.splitlines():
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
        if not data_lines:
            continue

        raw = "\n".join(data_lines).strip()
        if not raw or raw == "[DONE]":
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("OpenAI Speech SSE JSON 파싱에 실패했습니다.") from exc

        event_type = str(event.get("type") or "")
        if event_type == "speech.audio.delta":
            encoded = event.get("audio")
            if not isinstance(encoded, str) or not encoded:
                raise RuntimeError("speech.audio.delta 이벤트에 audio가 없습니다.")
            try:
                audio_parts.append(base64.b64decode(encoded))
            except Exception as exc:
                raise RuntimeError(
                    "speech.audio.delta base64 디코딩에 실패했습니다."
                ) from exc
        elif event_type == "speech.audio.done":
            candidate = event.get("usage")
            if isinstance(candidate, dict):
                usage = candidate
        elif event_type == "speech.audio.error":
            raise RuntimeError(f"OpenAI Speech SSE error: {event.get('error')}")

    if not audio_parts:
        raise RuntimeError("OpenAI Speech SSE에서 audio chunk를 받지 못했습니다.")
    if usage is None:
        raise RuntimeError(
            "OpenAI Speech SSE의 speech.audio.done에 provider usage가 없습니다."
        )

    return b"".join(audio_parts), usage


def _prepare_gpt4o_sse_kwargs(kwargs: dict) -> dict:
    request = dict(kwargs)
    request.setdefault("response_format", "wav")
    request["stream_format"] = "sse"

    extra_headers = dict(request.get("extra_headers") or {})
    extra_headers["Accept"] = "text/event-stream"
    request["extra_headers"] = extra_headers
    return request


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
    base = _normalize_model(model)
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

    request_kwargs = (
        _prepare_gpt4o_sse_kwargs(kwargs) if base == "gpt-4o-mini-tts" else kwargs
    )

    try:
        response = await client.audio.speech.create(**request_kwargs)
    except asyncio.CancelledError as exc:
        await mark_ambiguous_usage(event, exc)
        raise
    except Exception as exc:  # noqa: BLE001 - provider boundary
        await _raise_after_provider_error(event, exc)

    try:
        raw = await _read_audio_response(response)

        if base == "gpt-4o-mini-tts":
            content, usage = _parse_speech_sse(raw)
            cost, values = _tts_usage_cost(model, usage)
            await finalize_usage(
                event,
                request_id=_request_id(response),
                cost_usd=cost,
                **values,
            )
        else:
            # tts-1/tts-1-hd do not support Speech SSE usage. Their published
            # billing unit is characters, so exact request character count is used.
            content = raw
            cost, values = tts_cost(model, text=text, audio_bytes=content)
            await finalize_usage(
                event,
                request_id=_request_id(response),
                cost_usd=cost,
                **values,
            )
    except asyncio.CancelledError as exc:
        await mark_ambiguous_usage(event, exc)
        raise
    except Exception as exc:
        await mark_ambiguous_usage(event, exc)
        raise OpenAIAmbiguousRequestError(
            "OpenAI 요청은 완료됐지만 provider 실측 usage를 확정하지 못해 자동 재시도하지 않습니다."
        ) from exc

    return content
