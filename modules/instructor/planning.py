from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from core.jobs.base import LeaseLost


def utc_sql(dt: datetime) -> str:
    return (
        dt.astimezone(timezone.utc)
        .replace(tzinfo=None)
        .strftime("%Y-%m-%d %H:%M:%S")
    )


def term_start(profile: dict, now_local: datetime) -> date:
    raw = str(profile.get("semester_start_date") or "").strip()
    if raw:
        try:
            return date.fromisoformat(raw)
        except ValueError:
            pass
    return now_local.date() - timedelta(days=now_local.weekday())


def term_weeks(profile: dict) -> int:
    return max(1, min(30, int(profile.get("semester_weeks") or 15)))


def week_number(term_start_date: date, slot_day: date) -> int:
    return ((slot_day - term_start_date).days // 7) + 1


def candidate_slots(
    profile: dict,
    now_utc: datetime,
    *,
    catchup_grace_minutes: int,
) -> list[tuple[datetime, int]]:
    zone = ZoneInfo(profile.get("timezone") or "Asia/Seoul")
    now_local = now_utc.astimezone(zone)
    lead_hours = max(1, min(168, int(profile.get("lead_hours") or 24)))
    horizon = now_local + timedelta(hours=lead_hours)
    catchup_floor = now_local - timedelta(minutes=catchup_grace_minutes)
    weekdays = {
        int(value)
        for value in profile.get("weekdays_json") or []
        if 0 <= int(value) <= 6
    }
    value = profile.get("publish_hour")
    hour = max(0, min(23, int(18 if value is None else value)))
    minute = max(0, min(59, int(profile.get("publish_minute") or 0)))

    start = term_start(profile, now_local)
    total_weeks = term_weeks(profile)
    term_end_exclusive = start + timedelta(days=total_weeks * 7)

    slots: list[tuple[datetime, int]] = []
    day = max(catchup_floor.date(), start)
    last_day = min(horizon.date(), term_end_exclusive - timedelta(days=1))

    while day <= last_day:
        local_slot = datetime(
            day.year,
            day.month,
            day.day,
            hour,
            minute,
            tzinfo=zone,
        )
        number = week_number(start, day)
        if (
            1 <= number <= total_weeks
            and local_slot.weekday() in weekdays
            and catchup_floor <= local_slot <= horizon
        ):
            slots.append((local_slot, number))
        day += timedelta(days=1)
    return sorted(slots, key=lambda item: item[0])


def academic_week_window(
    *,
    start: date,
    week_number_value: int,
    zone: ZoneInfo,
) -> tuple[datetime, datetime]:
    week_start_date = start + timedelta(days=(week_number_value - 1) * 7)
    week_start_local = datetime(
        week_start_date.year,
        week_start_date.month,
        week_start_date.day,
        0,
        0,
        tzinfo=zone,
    )
    return week_start_local, week_start_local + timedelta(days=7)


async def run_reserved_plan(
    *,
    run_id: int,
    planning_token: str,
    profile: dict,
    scheduled_at: str,
    week_number_value: int,
    total_weeks: int,
    planning_heartbeat_fn: Callable[[int, str], Awaitable[None]],
    create_delegated_lecture_fn: Callable[..., Awaitable[Any]],
    fail_instructor_run_fn: Callable[..., Awaitable[Any]],
    retryable_fn: Callable[[BaseException], bool],
    max_attempts: int,
) -> None:
    heartbeat = asyncio.create_task(
        planning_heartbeat_fn(run_id, planning_token),
        name=f"instructor-planning-heartbeat-{run_id}",
    )
    planning = asyncio.create_task(
        create_delegated_lecture_fn(
            run_id=run_id,
            planning_token=planning_token,
            profile=profile,
            scheduled_at_utc=scheduled_at,
            week_number=week_number_value,
            total_weeks=total_weeks,
        ),
        name=f"instructor-planning-{run_id}",
    )
    try:
        done, _ = await asyncio.wait(
            {planning, heartbeat},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if heartbeat in done:
            heartbeat.result()
        planning.result()
    except asyncio.CancelledError:
        with contextlib.suppress(Exception):
            await fail_instructor_run_fn(
                run_id=run_id,
                planning_token=planning_token,
                error="scheduler cancelled",
            )
        raise
    except LeaseLost:
        pass
    except Exception as exc:  # noqa: BLE001
        with contextlib.suppress(Exception):
            await fail_instructor_run_fn(
                run_id=run_id,
                planning_token=planning_token,
                error=f"{type(exc).__name__}: {exc}"[:1200],
                retryable=retryable_fn(exc),
                max_attempts=max_attempts,
            )
    finally:
        for task in (planning, heartbeat):
            task.cancel()
        await asyncio.gather(planning, heartbeat, return_exceptions=True)
