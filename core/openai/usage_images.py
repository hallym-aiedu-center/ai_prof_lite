import asyncio
from typing import Any

from core.openai.usage_ledger import (
    OpenAIAmbiguousRequestError,
    _IMAGE_OUTPUT_PRICE,
    _IMAGE_RATES,
    _field,
    _json_override,
    _jsonable,
    _normalize_model,
    _number,
    _raise_after_provider_error,
    _rough_tokens,
    finalize_usage,
    mark_ambiguous_usage,
    reserve_usage,
)
from core.openai.usage_provider_common import _pricing_snapshot, _request_id

def _image_output_fallback_cost(model: str, *, size: str, quality: str) -> float:
    base = _normalize_model(model)
    override = _json_override("image_output", model)
    if override:
        by_quality = override.get(str(quality or "medium"))
        if isinstance(by_quality, dict):
            value = _number(by_quality.get(size) or by_quality.get("default"))
            if value > 0:
                return value
    table = _IMAGE_OUTPUT_PRICE.get(base)
    if not table:
        raise RuntimeError(f"가격 정보가 없는 OpenAI 이미지 모델입니다: {model}")
    quality_key = str(quality or "medium").lower()
    by_size = table.get(quality_key) or table["medium"]
    if size in by_size:
        return by_size[size]
    return max(by_size.values())


def _image_prompt_input_cost(model: str, prompt: str) -> float:
    rates = _IMAGE_RATES.get(_normalize_model(model))
    override = _json_override("image", model)
    if override:
        rates = (
            _number(override.get("text_input")),
            _number(override.get("image_input")),
            _number(override.get("image_output")),
        )
    if not rates:
        return 0.0
    return _rough_tokens(prompt) * rates[0] / 1_000_000


def _image_usage_cost(model: str, usage: Any) -> tuple[float, dict] | None:
    if usage is None:
        return None
    override = _json_override("image", model)
    rates = _IMAGE_RATES.get(_normalize_model(model))
    if override:
        rates = (
            _number(override.get("text_input")),
            _number(override.get("image_input")),
            _number(override.get("image_output")),
        )
    if not rates:
        return None
    input_tokens = int(_number(_field(usage, "input_tokens")))
    output_tokens = int(_number(_field(usage, "output_tokens")))
    input_details = _field(usage, "input_tokens_details", {})
    text_input = int(_number(_field(input_details, "text_tokens", input_tokens)))
    image_input = int(_number(_field(input_details, "image_tokens")))
    output_details = _field(usage, "output_tokens_details", {})
    image_output = int(_number(_field(output_details, "image_tokens", output_tokens)))
    cost = (text_input * rates[0] + image_input * rates[1] + image_output * rates[2]) / 1_000_000
    return cost, {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "usage": _jsonable(usage),
        "pricing": _pricing_snapshot("images", model),
        "metadata": {
            "billing_basis": "image_usage",
            "text_input_tokens": text_input,
            "image_input_tokens": image_input,
            "image_output_tokens": image_output,
        },
    }


async def images_generate(client, *, user_id: int, lecture_id: int | None = None, usage_context: dict | None = None, **kwargs):
    model = str(kwargs.get("model") or "")
    size = str(kwargs.get("size") or "1024x1024")
    quality = str(kwargs.get("quality") or "medium")
    fallback = _image_output_fallback_cost(model, size=size, quality=quality) + _image_prompt_input_cost(
        model, str(kwargs.get("prompt") or "")
    )
    context = usage_context or {}
    event = await reserve_usage(
        user_id=user_id,
        lecture_id=lecture_id,
        kind="images",
        endpoint="images.generate",
        operation=context.get("operation"),
        stage=context.get("stage"),
        item_key=context.get("item_key"),
        item_index=context.get("item_index"),
        metadata=context.get("metadata") or {},
        model=model,
        reserve_usd=fallback * 1.10,
    )
    try:
        response = await client.images.generate(**kwargs)
    except asyncio.CancelledError as exc:
        await mark_ambiguous_usage(event, exc)
        raise
    except Exception as exc:
        await _raise_after_provider_error(event, exc)
    try:
        measured = _image_usage_cost(model, getattr(response, "usage", None))
        if measured:
            cost, values = measured
            await finalize_usage(event, request_id=_request_id(response), cost_usd=cost, **values)
        else:
            await finalize_usage(
                event,
                cost_usd=fallback,
                request_id=_request_id(response),
                pricing=_pricing_snapshot("images", model, {"fallback_size": size, "fallback_quality": quality}),
                metadata={
                    "billing_basis": "provider_image_table",
                    "size": size,
                    "quality": quality,
                },
            )
    except asyncio.CancelledError as exc:
        await mark_ambiguous_usage(event, exc)
        raise
    except Exception as exc:
        await mark_ambiguous_usage(event, exc)
        raise OpenAIAmbiguousRequestError(
            "OpenAI 요청은 완료됐지만 비용 기록을 확정하지 못해 자동 재시도하지 않습니다."
        ) from exc
    return response
