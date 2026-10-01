from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from core.jobs.base import LeaseLost
from core.jobs.errors import retryable
from core.jobs.factory import get_queue
from modules.instructor.agent import create_delegated_lecture
from modules.instructor.planning import (
    academic_week_window,
    candidate_slots,
    run_reserved_plan,
    term_start,
    term_weeks,
    utc_sql,
    week_number,
)
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
    return max(
        0, min(1440, int(os.getenv("AI_INSTRUCTOR_CATCHUP_GRACE_MINUTES", "120")))
    )


def _utc_sql(dt: datetime) -> str:
    return utc_sql(dt)


def _term_start(profile: dict, now_local: datetime):
    return term_start(profile, now_local)


def _term_weeks(profile: dict) -> int:
    return term_weeks(profile)


def _week_number(term_start_date, slot_day) -> int:
    return week_number(term_start_date, slot_day)


def _candidate_slots(profile: dict, now_utc: datetime) -> list[tuple[datetime, int]]:
    return candidate_slots(
        profile,
        now_utc,
        catchup_grace_minutes=_catchup_grace_minutes(),
    )


async def _planning_heartbeat(run_id: int, planning_token: str) -> None:
    while True:
        await asyncio.sleep(_planning_heartbeat_seconds())
        if not await renew_instructor_run_lease(
            run_id,
            planning_token,
            lease_seconds=_planning_lease_seconds(),
        ):
            raise LeaseLost(
                "AI instructor planning lease was lost or account became inactive."
            )


async def _plan_reserved_slot(
    *,
    profile: dict,
    scheduled_at: str,
    week_number: int,
    total_weeks: int,
    reservation: tuple[int, str],
) -> None:
    run_id, planning_token = reservation
    await run_reserved_plan(
        run_id=run_id,
        planning_token=planning_token,
        profile=profile,
        scheduled_at=scheduled_at,
        week_number_value=week_number,
        total_weeks=total_weeks,
        planning_heartbeat_fn=_planning_heartbeat,
        create_delegated_lecture_fn=create_delegated_lecture,
        fail_instructor_run_fn=fail_instructor_run,
        retryable_fn=retryable,
        max_attempts=_planning_max_attempts(),
    )


async def _plan_profile(profile: dict) -> None:
    now_utc = datetime.now(timezone.utc)
    weekdays = {
        int(value)
        for value in profile.get("weekdays_json") or []
        if 0 <= int(value) <= 6
    }
    weekly_limit = max(
        1, min(max(1, len(weekdays)), int(profile.get("weekly_limit") or 1))
    )
    slots = _candidate_slots(profile, now_utc)
    total_weeks = _term_weeks(profile)
    zone = ZoneInfo(profile.get("timezone") or "Asia/Seoul")
    start = _term_start(profile, now_utc.astimezone(zone))

    for slot, week_no in slots:
        week_start_local, week_end_local = academic_week_window(
            start=start,
            week_number_value=week_no,
            zone=zone,
        )
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
            week_number=week_no,
            lease_seconds=_planning_lease_seconds(),
            max_attempts=_planning_max_attempts(),
            retry_minutes=_planning_retry_minutes(),
        )
        if reservation is None:
            continue

        await _plan_reserved_slot(
            profile=profile,
            scheduled_at=scheduled_at,
            week_number=week_no,
            total_weeks=total_weeks,
            reservation=reservation,
        )


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
            await asyncio.gather(_task, return_exceptions=True)
        _task = None
    _stop_event = None
