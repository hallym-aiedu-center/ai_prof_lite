import asyncio
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
from core.openai.usage_pricing import (
    _IMAGE_OUTPUT_PRICE,
    _IMAGE_RATES,
    _json_override,
    _normalize_model,
    _number,
)
from core.openai.usage_provider_common import _pricing_snapshot, _request_id


def _image_output_reserve_cost(model: str, *, size: str, quality: str) -> float:
    """Pre-request budget hold only; never used as finalized image cost."""
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


def _image_usage_cost(model: str, usage: Any) -> tuple[float, dict]:
    """Calculate finalized image cost only from provider-reported usage."""
    if usage is None:
        raise RuntimeError("OpenAI Image 응답에 provider usage가 없습니다.")

    override = _json_override("image", model)
    rates = _IMAGE_RATES.get(_normalize_model(model))
    if override:
        rates = (
            _number(override.get("text_input")),
            _number(override.get("image_input")),
            _number(override.get("image_output")),
        )
    if not rates:
        raise RuntimeError(f"가격 정보가 없는 OpenAI 이미지 모델입니다: {model}")

    input_tokens = int(_number(_field(usage, "input_tokens")))
    output_tokens = int(_number(_field(usage, "output_tokens")))
    if input_tokens <= 0 and output_tokens <= 0:
        raise RuntimeError("OpenAI Image provider usage의 token 수가 비어 있습니다.")

    input_details = _field(usage, "input_tokens_details", {})
    text_input = int(_number(_field(input_details, "text_tokens", input_tokens)))
    image_input = int(_number(_field(input_details, "image_tokens")))
    output_details = _field(usage, "output_tokens_details", {})
    image_output = int(_number(_field(output_details, "image_tokens", output_tokens)))

    cost = (
        text_input * rates[0] + image_input * rates[1] + image_output * rates[2]
    ) / 1_000_000
    return cost, {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "usage": _jsonable(usage),
        "pricing": _pricing_snapshot("images", model),
        "metadata": {
            "billing_basis": "image_usage",
            "usage_source": "provider",
            "text_input_tokens": text_input,
            "image_input_tokens": image_input,
            "image_output_tokens": image_output,
        },
    }


async def images_generate(
    client,
    *,
    user_id: int,
    lecture_id: int | None = None,
    usage_context: dict | None = None,
    **kwargs,
):
    model = str(kwargs.get("model") or "")
    size = str(kwargs.get("size") or "1024x1024")
    quality = str(kwargs.get("quality") or "medium")

    # Reservation is only a budget hold. Final cost/tokens always come from
    # response.usage and never from this table value.
    reserve_estimate = _image_output_reserve_cost(model, size=size, quality=quality)
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
        reserve_usd=reserve_estimate * 1.25,
    )

    try:
        response = await client.images.generate(**kwargs)
    except asyncio.CancelledError as exc:
        await mark_ambiguous_usage(event, exc)
        raise
    except Exception as exc:  # noqa: BLE001 - provider boundary
        await _raise_after_provider_error(event, exc)

    try:
        cost, values = _image_usage_cost(model, getattr(response, "usage", None))
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
            "OpenAI 이미지 요청은 완료됐지만 provider 실측 usage를 확정하지 못해 자동 재시도하지 않습니다."
        ) from exc

    return response
