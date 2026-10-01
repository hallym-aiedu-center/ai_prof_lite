from __future__ import annotations

import contextlib
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from core.jobs.base import LeaseLost

AsyncFn = Callable[..., Awaitable[Any]]


async def mark_attempt_started(
    *,
    lecture_id: int,
    lease_token: str,
    attempts: int,
    update_publish_schedule_fn: AsyncFn,
    update_lecture_fn: AsyncFn,
) -> None:
    await update_publish_schedule_fn(
        lecture_id,
        lease_token=lease_token,
        attempts=attempts,
        last_error=None,
    )
    await update_lecture_fn(
        lecture_id,
        status_message="예약 시각 도달 · Moodle에 강의 영상을 업로드하는 중",
    )


async def mark_published(
    *,
    lecture_id: int,
    lease_token: str,
    update_publish_schedule_fn: AsyncFn,
) -> None:
    now_utc = (
        datetime.now(timezone.utc)
        .replace(tzinfo=None)
        .strftime("%Y-%m-%d %H:%M:%S")
    )
    await update_publish_schedule_fn(
        lecture_id,
        lease_token=lease_token,
        clear_lease=True,
        status="published",
        published_at=now_utc,
        last_error=None,
    )


async def release_cancelled(
    *,
    lecture_id: int,
    lease_token: str,
    update_publish_schedule_fn: AsyncFn,
) -> None:
    with contextlib.suppress(LeaseLost, ValueError):
        await update_publish_schedule_fn(
            lecture_id,
            lease_token=lease_token,
            clear_lease=True,
            status="pending",
        )


async def release_not_ready(
    *,
    lecture_id: int,
    lease_token: str,
    update_publish_schedule_fn: AsyncFn,
    update_lecture_fn: AsyncFn,
) -> None:
    try:
        # Fence the projection write while the lease is still live.  Clearing the
        # lease first would make a subsequent ownership-checked lecture update
        # impossible and reintroduce stale-writer races.
        await update_publish_schedule_fn(
            lecture_id,
            lease_token=lease_token,
            last_error=None,
        )
        await update_lecture_fn(
            lecture_id,
            status_message="예약 시각 도달 · 최종 강의 영상 생성 완료 대기 중",
        )
        await update_publish_schedule_fn(
            lecture_id,
            lease_token=lease_token,
            clear_lease=True,
            status="pending",
            last_error=None,
        )
    except LeaseLost:
        return


async def settle_source_failed(
    *,
    lecture_id: int,
    lease_token: str,
    error: Exception,
    settle_source_failed_publish_schedule_fn: AsyncFn,
) -> None:
    try:
        await settle_source_failed_publish_schedule_fn(
            lecture_id,
            lease_token=lease_token,
            last_error=str(error),
        )
    except LeaseLost:
        return


async def settle_ambiguous(
    *,
    lecture_id: int,
    lease_token: str,
    error: Exception,
    update_publish_schedule_fn: AsyncFn,
    update_lecture_fn: AsyncFn,
) -> None:
    try:
        error_text = str(error)[:1200]
        await update_publish_schedule_fn(
            lecture_id,
            lease_token=lease_token,
            last_error=error_text,
        )
        await update_lecture_fn(
            lecture_id,
            status_message="강의 생성 완료 · Moodle 활동 생성 결과 수동 확인 필요",
        )
        await update_publish_schedule_fn(
            lecture_id,
            lease_token=lease_token,
            clear_lease=True,
            status="failed",
            last_error=error_text,
        )
    except LeaseLost:
        return


async def settle_unexpected_failure(
    *,
    lecture_id: int,
    lease_token: str,
    error: Exception,
    attempts: int,
    max_attempts: int,
    retry_minutes: int,
    update_publish_schedule_fn: AsyncFn,
    update_lecture_fn: AsyncFn,
) -> None:
    error_text = f"{type(error).__name__}: {error}"[:1200]
    if attempts < max_attempts:
        retry_at = (
            datetime.now(timezone.utc).replace(tzinfo=None)
            + timedelta(minutes=retry_minutes)
        ).strftime("%Y-%m-%d %H:%M:%S")
        try:
            await update_publish_schedule_fn(
                lecture_id,
                lease_token=lease_token,
                last_error=error_text,
            )
            await update_lecture_fn(
                lecture_id,
                status_message=(
                    f"Moodle 업로드 재시도 대기 중 · {retry_minutes}분 후 재시도"
                ),
            )
            await update_publish_schedule_fn(
                lecture_id,
                lease_token=lease_token,
                clear_lease=True,
                status="pending",
                scheduled_at=retry_at,
                last_error=error_text,
            )
        except LeaseLost:
            return
        return

    try:
        await update_publish_schedule_fn(
            lecture_id,
            lease_token=lease_token,
            last_error=error_text,
        )
        await update_lecture_fn(
            lecture_id,
            status_message="강의 생성 완료 · Moodle 예약 업로드 실패",
        )
        await update_publish_schedule_fn(
            lecture_id,
            lease_token=lease_token,
            clear_lease=True,
            status="failed",
            last_error=error_text,
        )
    except LeaseLost:
        return
