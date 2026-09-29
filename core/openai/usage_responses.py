import asyncio
from typing import Any
import math
import os

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
    _bool_env,
    _embedding_rate,
    _number,
    _positive_float_env,
    _rough_tokens,
    _text_rate,
)
from core.openai.usage_provider_common import _pricing_snapshot, _request_id

async def _count_response_input_tokens(client, *, model: str, **kwargs) -> int | None:
    if not _bool_env("OPENAI_USE_INPUT_TOKEN_COUNT", True):
        return None
    resource = getattr(getattr(client, "responses", None), "input_tokens", None)
    creator = getattr(resource, "create", None)
    if creator is None:
        return None
    payload = {"model": model}
    for key in (
        "input",
        "instructions",
        "text",
        "tools",
        "reasoning",
        "truncation",
        "conversation",
        "metadata",
        "previous_response_id",
    ):
        if key in kwargs and kwargs[key] is not None:
            payload[key] = kwargs[key]
    try:
        counted = await creator(**payload)
    except Exception:
        return None
    value = _field(counted, "input_tokens")
    tokens = int(_number(value))
    return tokens if tokens > 0 else None

def _response_usage_cost(model: str, usage: Any) -> tuple[float, dict]:
    rate = _text_rate(model)
    if not rate:
        raise RuntimeError(
            f"가격 정보가 없는 OpenAI 텍스트 모델입니다: {model}. "
            "OPENAI_PRICING_JSON에 단가를 등록하세요."
        )
    input_tokens = int(_number(_field(usage, "input_tokens")))
    output_tokens = int(_number(_field(usage, "output_tokens")))
    details = _field(usage, "input_tokens_details", {})
    cached = int(_number(_field(details, "cached_tokens")))
    uncached = max(0, input_tokens - cached)
    cost = (
        uncached * rate.input_per_million
        + cached * rate.cached_input_per_million
        + output_tokens * rate.output_per_million
    ) / 1_000_000
    return cost, {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_input_tokens": cached,
        "usage": _jsonable(usage),
        "pricing": _pricing_snapshot("responses", model),
        "metadata": {"billing_basis": "response_usage"},
    }


async def _response_reserve_cost(client, model: str, kwargs: dict, *, budget_input_bytes: int = 0) -> float:
    rate = _text_rate(model)
    if not rate:
        raise RuntimeError(
            f"가격 정보가 없는 OpenAI 텍스트 모델입니다: {model}. "
            "OPENAI_PRICING_JSON에 단가를 등록하세요."
        )
    input_tokens = await _count_response_input_tokens(client, **kwargs)
    if input_tokens is None:
        input_tokens = _rough_tokens(kwargs.get("input"))
    input_tokens += max(0, math.ceil(int(budget_input_bytes) / 2.0))
    max_output_tokens = int(
        kwargs.get("max_output_tokens")
        or os.getenv("OPENAI_RESPONSE_RESERVE_OUTPUT_TOKENS", "32768")
    )
    max_output_tokens = max(1, max_output_tokens)
    estimated = (
        input_tokens * rate.input_per_million
        + max_output_tokens * rate.output_per_million
    ) / 1_000_000
    floor = _positive_float_env("OPENAI_RESPONSE_RESERVE_MIN_USD", 0.005)
    return max(floor, estimated)


async def responses_create(
    client,
    *,
    user_id: int,
    lecture_id: int | None = None,
    budget_input_bytes: int = 0,
    usage_context: dict | None = None,
    **kwargs,
):
    model = str(kwargs.get("model") or "")
    context = usage_context or {}
    event = await reserve_usage(
        user_id=user_id,
        lecture_id=lecture_id,
        kind="responses",
        endpoint="responses.create",
        operation=context.get("operation"),
        stage=context.get("stage"),
        item_key=context.get("item_key"),
        item_index=context.get("item_index"),
        metadata=context.get("metadata") or {},
        model=model,
        reserve_usd=await _response_reserve_cost(client, model, kwargs, budget_input_bytes=budget_input_bytes),
    )
    try:
        response = await client.responses.create(**kwargs)
    except asyncio.CancelledError as exc:
        await mark_ambiguous_usage(event, exc)
        raise
    except Exception as exc:
        await _raise_after_provider_error(event, exc)
    try:
        cost, values = _response_usage_cost(model, getattr(response, "usage", None))
        await finalize_usage(event, request_id=_request_id(response), **values, cost_usd=cost)
    except asyncio.CancelledError as exc:
        await mark_ambiguous_usage(event, exc)
        raise
    except Exception as exc:
        await mark_ambiguous_usage(event, exc)
        raise OpenAIAmbiguousRequestError(
            "OpenAI 요청은 완료됐지만 비용 기록을 확정하지 못해 자동 재시도하지 않습니다."
        ) from exc
    return response


async def embeddings_create(client, *, user_id: int, lecture_id: int | None = None, usage_context: dict | None = None, **kwargs):
    model = str(kwargs.get("model") or "text-embedding-3-small")
    rate = _embedding_rate(model)
    if rate is None:
        raise RuntimeError(f"가격 정보가 없는 OpenAI 임베딩 모델입니다: {model}")
    inputs = kwargs.get("input") or []
    rough_tokens = _rough_tokens(inputs)
    context = usage_context or {}
    event = await reserve_usage(
        user_id=user_id,
        lecture_id=lecture_id,
        kind="embeddings",
        endpoint="embeddings.create",
        operation=context.get("operation"),
        stage=context.get("stage"),
        item_key=context.get("item_key"),
        item_index=context.get("item_index"),
        metadata=context.get("metadata") or {},
        model=model,
        reserve_usd=(rough_tokens * float(rate) / 1_000_000) * 1.25,
    )
    try:
        response = await client.embeddings.create(**kwargs)
    except asyncio.CancelledError as exc:
        await mark_ambiguous_usage(event, exc)
        raise
    except Exception as exc:
        await _raise_after_provider_error(event, exc)
    try:
        usage = getattr(response, "usage", None)
        tokens = int(_number(_field(usage, "prompt_tokens", _field(usage, "total_tokens", 0))))
        await finalize_usage(
            event,
            cost_usd=tokens * float(rate) / 1_000_000,
            input_tokens=tokens,
            request_id=_request_id(response),
            usage=_jsonable(usage),
            pricing=_pricing_snapshot("embeddings", model),
            metadata={"billing_basis": "embedding_usage"},
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
