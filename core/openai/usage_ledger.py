from __future__ import annotations

import asyncio
import json
import os
from dataclasses import asdict, is_dataclass
from typing import Any

import httpx
from openai import APIConnectionError, APIStatusError

from core.config import openai_key_mode, server_openai_account_budget_usd
from core.database.client import get_connection
from core.openai.usage_pricing import (
    TokenRate,
    _EMBEDDING_RATES,
    _IMAGE_OUTPUT_PRICE,
    _IMAGE_RATES,
    _TEXT_RATES,
    _TTS_MODELS,
    _bool_env,
    _embedding_rate,
    _json_override,
    _normalize_model,
    _number,
    _positive_float_env,
    _rough_tokens,
    _text_rate,
)


class OpenAIBudgetExceeded(RuntimeError):
    """Raised before a paid OpenAI request when the user's budget is exhausted."""


class OpenAIAmbiguousRequestError(RuntimeError):
    """A paid request may have reached OpenAI; automatic replay is unsafe."""


def _field(obj: Any, name: str, default: Any = 0) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


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


async def _account_budget(db, *, user_id: int) -> float | None:
    if openai_key_mode() == "server":
        return server_openai_account_budget_usd()
    setting = await _fetchone(
        db,
        "SELECT openai_budget_usd FROM user_settings WHERE user_id = ?",
        (user_id,),
    )
    if not setting or setting["openai_budget_usd"] is None:
        return None
    return _number(setting["openai_budget_usd"])


def _ambiguous_provider_error(exc: BaseException) -> bool:
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError, APIConnectionError, httpx.TransportError)):
        return True
    if isinstance(exc, APIStatusError):
        return exc.status_code == 408 or exc.status_code >= 500
    return False


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


async def usage_summary(user_id: int) -> dict[str, Any]:
    db = await get_connection()
    try:
        await _delete_stale_reservations(db, user_id=user_id)
        await db.commit()
        row = await _fetchone(
            db,
            """
            SELECT
              COALESCE(SUM(CASE WHEN status='finalized' THEN cost_usd ELSE 0 END), 0) AS spent,
              COALESCE(SUM(CASE WHEN status IN ('reserved','ambiguous') THEN reserved_cost_usd ELSE 0 END), 0) AS reserved
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
        budget = await _account_budget(db, user_id=user_id)
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
        budget = await _account_budget(db, user_id=user_id)
        totals = await _fetchone(
            db,
            """SELECT
              COALESCE(SUM(CASE WHEN status='finalized' THEN cost_usd ELSE 0 END), 0) AS spent,
              COALESCE(SUM(CASE WHEN status IN ('reserved','ambiguous') THEN reserved_cost_usd ELSE 0 END), 0) AS reserved
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


async def mark_ambiguous_usage(event_id: int, exc: BaseException) -> None:
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
        existing["billing_state"] = "ambiguous"
        existing["provider_error_type"] = type(exc).__name__
        existing["provider_error"] = str(exc)[:1000]
        await db.execute(
            """UPDATE openai_usage_events
               SET status='ambiguous', metadata_json=?
               WHERE id=? AND status='reserved'""",
            (json.dumps(_jsonable(existing), ensure_ascii=False), event_id),
        )
        await db.commit()
    finally:
        await db.close()


async def _raise_after_provider_error(event_id: int, exc: BaseException) -> None:
    if _ambiguous_provider_error(exc):
        await mark_ambiguous_usage(event_id, exc)
        raise OpenAIAmbiguousRequestError(
            "OpenAI 요청 결과가 불명확하여 비용 예약을 보존했습니다. 자동 재시도하지 않습니다."
        ) from exc
    await cancel_reservation(event_id)
    raise exc


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
