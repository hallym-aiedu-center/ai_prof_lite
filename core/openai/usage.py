from __future__ import annotations

import inspect
import io
import json
import math
import os
import wave
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any

from core.database.client import get_connection


class OpenAIBudgetExceeded(RuntimeError):
    """Raised before a paid OpenAI request when the user's budget is exhausted."""


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


def _field(obj: Any, name: str, default: Any = 0) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


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


def _reservation_ttl_minutes() -> int:
    raw = os.getenv("OPENAI_USAGE_RESERVATION_TTL_MINUTES", "180").strip()
    try:
        value = int(raw)
    except ValueError:
        value = 180
    return max(15, min(24 * 60, value))


async def _delete_stale_reservations(db, *, user_id: int) -> None:
    ttl = _reservation_ttl_minutes()
    await db.execute(
        """DELETE FROM openai_usage_events
           WHERE user_id=? AND status='reserved'
             AND created_at < datetime('now', ?)""",
        (user_id, f"-{ttl} minutes"),
    )


async def _fetchone(db, sql: str, params: tuple = ()):
    return await (await db.execute(sql, params)).fetchone()


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


async def usage_summary(user_id: int) -> dict[str, float | None]:
    db = await get_connection()
    try:
        await _delete_stale_reservations(db, user_id=user_id)
        await db.commit()
        setting = await _fetchone(
            db,
            "SELECT openai_budget_usd FROM user_settings WHERE user_id = ?",
            (user_id,),
        )
        row = await _fetchone(
            db,
            """
            SELECT
              COALESCE(SUM(CASE WHEN status='finalized' THEN cost_usd ELSE 0 END), 0) AS spent,
              COALESCE(SUM(CASE WHEN status='reserved' THEN reserved_cost_usd ELSE 0 END), 0) AS reserved
            FROM openai_usage_events WHERE user_id = ?
            """,
            (user_id,),
        )
        breakdown_rows = await (
            await db.execute(
                """
                SELECT kind, COALESCE(SUM(cost_usd), 0) AS amount
                FROM openai_usage_events
                WHERE user_id=? AND status='finalized'
                GROUP BY kind
                ORDER BY amount DESC, kind ASC
                """,
                (user_id,),
            )
        ).fetchall()
        budget = _number(setting["openai_budget_usd"]) if setting and setting["openai_budget_usd"] is not None else None
        spent = _number(row["spent"] if row else 0)
        reserved = _number(row["reserved"] if row else 0)
        remaining = None if budget is None else max(0.0, budget - spent - reserved)
        return {
            "budget": budget,
            "spent": spent,
            "reserved": reserved,
            "remaining": remaining,
            "over_budget": 0.0 if budget is None else max(0.0, spent + reserved - budget),
            "breakdown": {str(item["kind"]): _number(item["amount"]) for item in breakdown_rows},
        }
    finally:
        await db.close()


async def list_usage_events(user_id: int, *, limit: int = 30) -> list[dict[str, Any]]:
    db = await get_connection()
    try:
        rows = await (
            await db.execute(
                """
                SELECT *
                FROM openai_usage_events
                WHERE user_id=?
                ORDER BY id DESC
                LIMIT ?
                """,
                (user_id, max(1, int(limit))),
            )
        ).fetchall()
    finally:
        await db.close()

    events: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        for key in ("metadata_json", "usage_json", "pricing_json"):
            raw = item.get(key)
            if raw:
                try:
                    item[key[:-5]] = json.loads(raw)
                except (TypeError, ValueError, json.JSONDecodeError):
                    item[key[:-5]] = {}
            else:
                item[key[:-5]] = {}
        events.append(item)
    return events


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "model_dump"):
        try:
            return _jsonable(value.model_dump())
        except Exception:
            pass
    if hasattr(value, "dict"):
        try:
            return _jsonable(value.dict())
        except Exception:
            pass
    if hasattr(value, "__dict__"):
        try:
            return _jsonable(vars(value))
        except Exception:
            pass
    return str(value)


async def reserve_usage(
    *,
    user_id: int,
    kind: str,
    model: str,
    reserve_usd: float,
    lecture_id: int | None = None,
    endpoint: str | None = None,
    operation: str | None = None,
    stage: str | None = None,
    item_key: str | None = None,
    item_index: int | None = None,
    metadata: dict | None = None,
) -> int:
    reserve_usd = max(0.0, float(reserve_usd))
    db = await get_connection()
    try:
        await db.execute("BEGIN IMMEDIATE")
        await _delete_stale_reservations(db, user_id=user_id)
        setting = await _fetchone(
            db,
            "SELECT openai_budget_usd FROM user_settings WHERE user_id = ?",
            (user_id,),
        )
        budget = _number(setting["openai_budget_usd"]) if setting and setting["openai_budget_usd"] is not None else None
        totals = await _fetchone(
            db,
            """SELECT
              COALESCE(SUM(CASE WHEN status='finalized' THEN cost_usd ELSE 0 END), 0) AS spent,
              COALESCE(SUM(CASE WHEN status='reserved' THEN reserved_cost_usd ELSE 0 END), 0) AS reserved
            FROM openai_usage_events WHERE user_id = ?""",
            (user_id,),
        )
        committed = _number(totals["spent"]) + _number(totals["reserved"])
        if budget is not None and committed + reserve_usd > budget + 1e-12:
            await db.rollback()
            raise OpenAIBudgetExceeded(
                f"OpenAI 비용 한도 ${budget:.2f} 중 ${committed:.4f}가 이미 사용/예약되어 "
                f"이번 {kind} 요청(${reserve_usd:.4f} 예약)을 실행할 수 없습니다."
            )
        cursor = await db.execute(
            """INSERT INTO openai_usage_events
               (user_id, lecture_id, kind, endpoint, operation, stage, item_key, item_index,
                model, status, reserved_cost_usd, cost_usd, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'reserved', ?, 0, ?)""",
            (
                user_id,
                lecture_id,
                kind,
                endpoint,
                operation,
                stage,
                item_key,
                item_index,
                model,
                reserve_usd,
                json.dumps(_jsonable(metadata or {}), ensure_ascii=False),
            ),
        )
        await db.commit()
        return int(cursor.lastrowid)
    finally:
        await db.close()


async def cancel_reservation(event_id: int) -> None:
    db = await get_connection()
    try:
        await db.execute("DELETE FROM openai_usage_events WHERE id = ? AND status='reserved'", (event_id,))
        await db.commit()
    finally:
        await db.close()


async def finalize_usage(
    event_id: int,
    *,
    cost_usd: float,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cached_input_tokens: int = 0,
    metadata: dict | None = None,
    usage: dict | None = None,
    pricing: dict | None = None,
    request_id: str | None = None,
) -> None:
    db = await get_connection()
    try:
        row = await _fetchone(db, "SELECT metadata_json FROM openai_usage_events WHERE id=?", (event_id,))
        existing = {}
        raw = row["metadata_json"] if row else None
        if raw:
            try:
                existing = json.loads(raw)
            except (TypeError, ValueError, json.JSONDecodeError):
                existing = {}
        merged = existing | _jsonable(metadata or {})
        await db.execute(
            """UPDATE openai_usage_events
               SET status='finalized', reserved_cost_usd=0, cost_usd=?, input_tokens=?,
                   output_tokens=?, cached_input_tokens=?, request_id=?, metadata_json=?,
                   usage_json=?, pricing_json=?
               WHERE id=? AND status='reserved'""",
            (
                max(0.0, float(cost_usd)),
                max(0, int(input_tokens)),
                max(0, int(output_tokens)),
                max(0, int(cached_input_tokens)),
                (request_id or None),
                json.dumps(merged, ensure_ascii=False),
                json.dumps(_jsonable(usage or {}), ensure_ascii=False),
                json.dumps(_jsonable(pricing or {}), ensure_ascii=False),
                event_id,
            ),
        )
        await db.commit()
    finally:
        await db.close()


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
        cost, values = _response_usage_cost(model, getattr(response, "usage", None))
        await finalize_usage(event, request_id=_request_id(response), **values, cost_usd=cost)
        return response
    except BaseException:
        await cancel_reservation(event)
        raise


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
        return response
    except BaseException:
        await cancel_reservation(event)
        raise


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
        return response
    except BaseException:
        await cancel_reservation(event)
        raise


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
        content = await _read_audio_response(response)
        measured = _tts_usage_cost(model, getattr(response, "usage", None))
        if measured:
            cost, values = measured
            await finalize_usage(event, request_id=_request_id(response), cost_usd=cost, **values)
        else:
            cost, values = tts_cost(model, text=text, audio_bytes=content)
            await finalize_usage(event, request_id=_request_id(response), cost_usd=cost, **values)
        return content
    except BaseException:
        await cancel_reservation(event)
        raise
