from __future__ import annotations

import asyncio
import contextlib
import os
from datetime import datetime, timedelta, timezone

from core.jobs.base import LeaseLost
from core.jobs.errors import (
    AmbiguousDeploymentError,
    PublishNotReadyError,
    PublishSourceFailedError,
)
from modules.lecture.publishing import (
    deploy_lecture_to_moodle,
    ensure_lecture_ready_for_publish,
)
from modules.lecture.repository import (
    get_publish_schedule,
    settle_source_failed_publish_schedule,
    update_lecture,
    update_publish_schedule,
)


def _max_attempts() -> int:
    return max(1, int(os.getenv("LECTURE_PUBLISH_MAX_ATTEMPTS", "3")))


def _retry_minutes() -> int:
    return max(5, int(os.getenv("LECTURE_PUBLISH_RETRY_MINUTES", "15")))


async def _run_claimed_publish(
    lecture_id: int,
    lease_token: str,
    *,
    get_publish_schedule_fn=get_publish_schedule,
    ensure_lecture_ready_for_publish_fn=ensure_lecture_ready_for_publish,
    update_publish_schedule_fn=update_publish_schedule,
    update_lecture_fn=update_lecture,
    deploy_lecture_to_moodle_fn=deploy_lecture_to_moodle,
    settle_source_failed_publish_schedule_fn=settle_source_failed_publish_schedule,
) -> None:
    attempts = 0
    try:
        schedule = await get_publish_schedule_fn(lecture_id)
        attempts = int((schedule or {}).get("attempts") or 0)

        # A schedule can become due before media rendering finishes. Waiting for
        # final_video_path is not a Moodle upload attempt and must not consume the
        # retry budget.
        await ensure_lecture_ready_for_publish_fn(lecture_id)

        attempts += 1
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

        await deploy_lecture_to_moodle_fn(
            lecture_id,
            publish_lease_token=lease_token,
        )
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        await update_publish_schedule_fn(
            lecture_id,
            lease_token=lease_token,
            clear_lease=True,
            status="published",
            published_at=now_utc,
            last_error=None,
        )
    except asyncio.CancelledError:
        # Shutdown or lease-loss fencing may cancel this task before or after
        # the non-idempotent create request. create_state is deliberately
        # retained; if it is 'running', the next attempt stops as ambiguous.
        with contextlib.suppress(LeaseLost, ValueError):
            await update_publish_schedule_fn(
                lecture_id,
                lease_token=lease_token,
                clear_lease=True,
                status="pending",
            )
        raise
    except LeaseLost:
        # Another process recovered an expired lease. Never let this stale
        # scheduler overwrite the new owner's state.
        return
    except PublishNotReadyError:
        # Rendering is still in progress. Keep the original scheduled_at so the
        # next scheduler poll can retry, but do not spend an upload attempt.
        with contextlib.suppress(LeaseLost):
            await update_publish_schedule_fn(
                lecture_id,
                lease_token=lease_token,
                clear_lease=True,
                status="pending",
                last_error=None,
            )
        await update_lecture_fn(
            lecture_id,
            status_message="예약 시각 도달 · 최종 강의 영상 생성 완료 대기 중",
        )
    except PublishSourceFailedError as exc:
        # The source-failure observation can go stale while a user retry is
        # completing. Re-check lecture.status and settle the publish row in one
        # SQLite write transaction so a recovered lecture is never overwritten
        # with a late publish failure.
        try:
            still_failed = await settle_source_failed_publish_schedule_fn(
                lecture_id,
                lease_token=lease_token,
                last_error=str(exc),
            )
        except LeaseLost:
            return
        if still_failed:
            await update_lecture_fn(
                lecture_id,
                status_message="강의 생성 실패 · Moodle 예약 게시 중단",
            )
    except AmbiguousDeploymentError as exc:
        with contextlib.suppress(LeaseLost):
            await update_publish_schedule_fn(
                lecture_id,
                lease_token=lease_token,
                clear_lease=True,
                status="failed",
                last_error=str(exc)[:1200],
            )
        await update_lecture_fn(
            lecture_id,
            status_message="강의 생성 완료 · Moodle 활동 생성 결과 수동 확인 필요",
        )
    except Exception as exc:  # noqa: BLE001
        if attempts < _max_attempts():
            retry_at = (
                datetime.now(timezone.utc).replace(tzinfo=None)
                + timedelta(minutes=_retry_minutes())
            ).strftime("%Y-%m-%d %H:%M:%S")
            with contextlib.suppress(LeaseLost):
                await update_publish_schedule_fn(
                    lecture_id,
                    lease_token=lease_token,
                    clear_lease=True,
                    status="pending",
                    scheduled_at=retry_at,
                    last_error=f"{type(exc).__name__}: {exc}"[:1200],
                )
            await update_lecture_fn(
                lecture_id,
                status_message=(
                    f"Moodle 업로드 재시도 대기 중 · {_retry_minutes()}분 후 재시도"
                ),
            )
        else:
            with contextlib.suppress(LeaseLost):
                await update_publish_schedule_fn(
                    lecture_id,
                    lease_token=lease_token,
                    clear_lease=True,
                    status="failed",
                    last_error=f"{type(exc).__name__}: {exc}"[:1200],
                )
            await update_lecture_fn(
                lecture_id,
                status_message="강의 생성 완료 · Moodle 예약 업로드 실패",
            )
