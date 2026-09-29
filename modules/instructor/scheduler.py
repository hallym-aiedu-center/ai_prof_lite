from __future__ import annotations

import asyncio
import contextlib
import os
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from core.jobs.base import LeaseLost
from core.jobs.errors import retryable
from core.jobs.factory import get_queue
from modules.instructor.agent import create_delegated_lecture
from modules.instructor.repository import (
    count_runs_between,
    fail_instructor_run,
    list_enabled_profiles,
    recover_stale_instructor_runs,
    renew_instructor_run_lease,
    reserve_instructor_run,
)

_task: asyncio.Task | None = None
_stop_event: asyncio.Event | None = None


def _poll_seconds() -> int:
    return max(30, int(os.getenv("AI_INSTRUCTOR_POLL_SECONDS", "60")))


def _planning_lease_seconds() -> int:
    return max(60, int(os.getenv("AI_INSTRUCTOR_LEASE_SECONDS", "180")))


def _planning_heartbeat_seconds() -> int:
    configured = max(10, int(os.getenv("AI_INSTRUCTOR_HEARTBEAT_SECONDS", "30")))
    return min(configured, max(10, _planning_lease_seconds() // 3))


def _planning_max_attempts() -> int:
    return max(1, int(os.getenv("AI_INSTRUCTOR_MAX_ATTEMPTS", "3")))


def _planning_retry_minutes() -> int:
    return max(1, int(os.getenv("AI_INSTRUCTOR_RETRY_MINUTES", "10")))


def _catchup_grace_minutes() -> int:
    """How far past a missed publish slot the planner may catch up after downtime."""
    return max(0, min(1440, int(os.getenv("AI_INSTRUCTOR_CATCHUP_GRACE_MINUTES", "120"))))


def _utc_sql(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")


def _term_start(profile: dict, now_local: datetime) -> date:
    raw = str(profile.get("semester_start_date") or "").strip()
    if raw:
        try:
            return date.fromisoformat(raw)
        except ValueError:
            pass
    # Backward-compatible fallback for pre-v13 profiles: current week's Monday.
    return now_local.date() - timedelta(days=now_local.weekday())


def _term_weeks(profile: dict) -> int:
    return max(1, min(30, int(profile.get("semester_weeks") or 15)))


def _week_number(term_start: date, slot_day: date) -> int:
    return ((slot_day - term_start).days // 7) + 1


def _candidate_slots(profile: dict, now_utc: datetime) -> list[tuple[datetime, int]]:
    zone = ZoneInfo(profile.get("timezone") or "Asia/Seoul")
    now_local = now_utc.astimezone(zone)
    lead_hours = max(1, min(168, int(profile.get("lead_hours") or 24)))
    horizon = now_local + timedelta(hours=lead_hours)
    catchup_floor = now_local - timedelta(minutes=_catchup_grace_minutes())
    weekdays = {int(v) for v in profile.get("weekdays_json") or [] if 0 <= int(v) <= 6}
    value = profile.get("publish_hour")
    hour = max(0, min(23, int(18 if value is None else value)))
    minute = max(0, min(59, int(profile.get("publish_minute") or 0)))

    term_start = _term_start(profile, now_local)
    total_weeks = _term_weeks(profile)
    term_end_exclusive = term_start + timedelta(days=total_weeks * 7)

    slots: list[tuple[datetime, int]] = []
    day = max(catchup_floor.date(), term_start)
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
        week_number = _week_number(term_start, day)
        if (
            1 <= week_number <= total_weeks
            and local_slot.weekday() in weekdays
            and catchup_floor <= local_slot <= horizon
        ):
            slots.append((local_slot, week_number))
        day += timedelta(days=1)
    return sorted(slots, key=lambda item: item[0])


async def _planning_heartbeat(run_id: int, planning_token: str) -> None:
    while True:
        await asyncio.sleep(_planning_heartbeat_seconds())
        if not await renew_instructor_run_lease(
            run_id,
            planning_token,
            lease_seconds=_planning_lease_seconds(),
        ):
            raise LeaseLost("AI instructor planning lease was lost or account became inactive.")


async def _plan_profile(profile: dict) -> None:
    now_utc = datetime.now(timezone.utc)
    weekdays = {int(v) for v in profile.get("weekdays_json") or [] if 0 <= int(v) <= 6}
    weekly_limit = max(1, min(max(1, len(weekdays)), int(profile.get("weekly_limit") or 1)))
    slots = _candidate_slots(profile, now_utc)
    total_weeks = _term_weeks(profile)
    zone = ZoneInfo(profile.get("timezone") or "Asia/Seoul")
    term_start = _term_start(profile, now_utc.astimezone(zone))

    for slot, week_number in slots:
        academic_week_start_date = term_start + timedelta(days=(week_number - 1) * 7)
        week_start_local = datetime(
            academic_week_start_date.year,
            academic_week_start_date.month,
            academic_week_start_date.day,
            0,
            0,
            tzinfo=zone,
        )
        week_end_local = week_start_local + timedelta(days=7)
        existing = await count_runs_between(
            int(profile["user_id"]),
            _utc_sql(week_start_local),
            _utc_sql(week_end_local),
        )
        if existing >= weekly_limit:
            continue

        scheduled_at = _utc_sql(slot)
        reservation = await reserve_instructor_run(
            user_id=int(profile["user_id"]),
            scheduled_at=scheduled_at,
            timezone=profile.get("timezone") or "Asia/Seoul",
            week_number=week_number,
            lease_seconds=_planning_lease_seconds(),
            max_attempts=_planning_max_attempts(),
            retry_minutes=_planning_retry_minutes(),
        )
        if reservation is None:
            continue

        run_id, planning_token = reservation
        heartbeat = asyncio.create_task(
            _planning_heartbeat(run_id, planning_token),
            name=f"instructor-planning-heartbeat-{run_id}",
        )
        planning = asyncio.create_task(
            create_delegated_lecture(
                run_id=run_id,
                planning_token=planning_token,
                profile=profile,
                scheduled_at_utc=scheduled_at,
                week_number=week_number,
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
                await fail_instructor_run(
                    run_id=run_id,
                    planning_token=planning_token,
                    error="scheduler cancelled",
                )
            raise
        except LeaseLost:
            # Ownership can be lost to lease recovery or immediate account deactivation.
            pass
        except Exception as exc:  # noqa: BLE001
            with contextlib.suppress(Exception):
                await fail_instructor_run(
                    run_id=run_id,
                    planning_token=planning_token,
                    error=f"{type(exc).__name__}: {exc}"[:1200],
                    retryable=retryable(exc),
                    max_attempts=_planning_max_attempts(),
                )
        finally:
            for task in (planning, heartbeat):
                task.cancel()
            await asyncio.gather(planning, heartbeat, return_exceptions=True)


async def _recover_abandoned_plans() -> None:
    lecture_ids = await recover_stale_instructor_runs()
    queue = get_queue()
    for lecture_id in lecture_ids:
        await queue.enqueue(lecture_id)


async def _loop() -> None:
    assert _stop_event is not None
    while not _stop_event.is_set():
        try:
            await _recover_abandoned_plans()
            profiles = await list_enabled_profiles()
            for profile in profiles:
                await _plan_profile(profile)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            print(f"[AIInstructor] scheduler error: {exc}")

        try:
            await asyncio.wait_for(_stop_event.wait(), timeout=_poll_seconds())
        except asyncio.TimeoutError:
            pass


async def start_instructor_scheduler() -> None:
    global _task, _stop_event
    if _task and not _task.done():
        return
    _stop_event = asyncio.Event()
    _task = asyncio.create_task(_loop(), name="ai-instructor-scheduler")


async def stop_instructor_scheduler() -> None:
    global _task, _stop_event
    if _stop_event is not None:
        _stop_event.set()
    if _task is not None:
        try:
            await asyncio.wait_for(_task, timeout=5.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            _task.cancel()
        _task = None
    _stop_event = None
