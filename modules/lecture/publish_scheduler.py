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
    claim_publish_schedule,
    get_publish_schedule,
    list_due_publish_schedule_ids,
    renew_publish_schedule_lease,
    settle_source_failed_publish_schedule,
    update_lecture,
    update_publish_schedule,
)

_task: asyncio.Task | None = None
_stop_event: asyncio.Event | None = None


def _poll_seconds() -> int:
    return max(15, int(os.getenv("LECTURE_PUBLISH_POLL_SECONDS", "30")))


def _max_attempts() -> int:
    return max(1, int(os.getenv("LECTURE_PUBLISH_MAX_ATTEMPTS", "3")))


def _retry_minutes() -> int:
    return max(5, int(os.getenv("LECTURE_PUBLISH_RETRY_MINUTES", "15")))


def _lease_seconds() -> int:
    # Moodle video uploads can be long. The heartbeat keeps this lease alive;
    # the lease only needs to be long enough to tolerate brief scheduler stalls.
    return max(60, int(os.getenv("LECTURE_PUBLISH_LEASE_SECONDS", "180")))


def _heartbeat_seconds() -> int:
    configured = max(10, int(os.getenv("LECTURE_PUBLISH_HEARTBEAT_SECONDS", "30")))
    return min(configured, max(10, _lease_seconds() // 3))


async def _lease_heartbeat(lecture_id: int, lease_token: str) -> None:
    while True:
        await asyncio.sleep(_heartbeat_seconds())
        try:
            renewed = await renew_publish_schedule_lease(
                lecture_id,
                lease_token,
                lease_seconds=_lease_seconds(),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            # Fail closed: if ownership cannot be renewed/verified, the active
            # publish task must stop rather than continue external Moodle calls.
            raise LeaseLost("예약 게시 lease heartbeat 갱신에 실패했습니다.") from exc
        if not renewed:
            raise LeaseLost("예약 게시 lease 소유권을 잃었습니다.")


async def _run_claimed_publish(lecture_id: int, lease_token: str) -> None:
    attempts = 0
    try:
        schedule = await get_publish_schedule(lecture_id)
        attempts = int((schedule or {}).get("attempts") or 0)

        # A schedule can become due before media rendering finishes. Waiting for
        # final_video_path is not a Moodle upload attempt and must not consume the
        # retry budget.
        await ensure_lecture_ready_for_publish(lecture_id)

        attempts += 1
        await update_publish_schedule(
            lecture_id,
            lease_token=lease_token,
            attempts=attempts,
            last_error=None,
        )
        await update_lecture(
            lecture_id,
            status_message="예약 시각 도달 · Moodle에 강의 영상을 업로드하는 중",
        )

        await deploy_lecture_to_moodle(
            lecture_id,
            publish_lease_token=lease_token,
        )
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        await update_publish_schedule(
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
            await update_publish_schedule(
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
            await update_publish_schedule(
                lecture_id,
                lease_token=lease_token,
                clear_lease=True,
                status="pending",
                last_error=None,
            )
        await update_lecture(
            lecture_id,
            status_message="예약 시각 도달 · 최종 강의 영상 생성 완료 대기 중",
        )
    except PublishSourceFailedError as exc:
        # The source-failure observation can go stale while a user retry is
        # completing. Re-check lecture.status and settle the publish row in one
        # SQLite write transaction so a recovered lecture is never overwritten
        # with a late publish failure.
        try:
            still_failed = await settle_source_failed_publish_schedule(
                lecture_id,
                lease_token=lease_token,
                last_error=str(exc),
            )
        except LeaseLost:
            return
        if still_failed:
            await update_lecture(
                lecture_id,
                status_message="강의 생성 실패 · Moodle 예약 게시 중단",
            )
    except AmbiguousDeploymentError as exc:
        with contextlib.suppress(LeaseLost):
            await update_publish_schedule(
                lecture_id,
                lease_token=lease_token,
                clear_lease=True,
                status="failed",
                last_error=str(exc)[:1200],
            )
        await update_lecture(
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
                await update_publish_schedule(
                    lecture_id,
                    lease_token=lease_token,
                    clear_lease=True,
                    status="pending",
                    scheduled_at=retry_at,
                    last_error=f"{type(exc).__name__}: {exc}"[:1200],
                )
            await update_lecture(
                lecture_id,
                status_message=(
                    f"Moodle 업로드 재시도 대기 중 · {_retry_minutes()}분 후 재시도"
                ),
            )
        else:
            with contextlib.suppress(LeaseLost):
                await update_publish_schedule(
                    lecture_id,
                    lease_token=lease_token,
                    clear_lease=True,
                    status="failed",
                    last_error=f"{type(exc).__name__}: {exc}"[:1200],
                )
            await update_lecture(
                lecture_id,
                status_message="강의 생성 완료 · Moodle 예약 업로드 실패",
            )


async def _run_one(lecture_id: int) -> None:
    lease_token = await claim_publish_schedule(
        lecture_id,
        lease_seconds=_lease_seconds(),
    )
    if not lease_token:
        return

    heartbeat = asyncio.create_task(
        _lease_heartbeat(lecture_id, lease_token),
        name=f"publish-heartbeat-{lecture_id}",
    )
    publishing = asyncio.create_task(
        _run_claimed_publish(lecture_id, lease_token),
        name=f"publish-work-{lecture_id}",
    )
    try:
        done, _ = await asyncio.wait(
            {publishing, heartbeat},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if heartbeat in done:
            # _lease_heartbeat only completes by raising LeaseLost (or another
            # unexpected exception). Raising here immediately fences the worker.
            heartbeat.result()
        publishing.result()
    except LeaseLost:
        # A recovered/expired lease belongs to another scheduler now. The finally
        # block cancels any in-flight Moodle request and stale state writes are
        # already fenced by lease_token checks in the repository.
        return
    finally:
        for task in (publishing, heartbeat):
            task.cancel()
        await asyncio.gather(publishing, heartbeat, return_exceptions=True)


async def _scheduler_loop() -> None:
    assert _stop_event is not None
    while not _stop_event.is_set():
        try:
            due = await list_due_publish_schedule_ids(limit=10)
            for lecture_id in due:
                await _run_one(lecture_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            print(f"[PublishScheduler] error: {exc}")

        try:
            await asyncio.wait_for(_stop_event.wait(), timeout=_poll_seconds())
        except asyncio.TimeoutError:
            pass


async def start_publish_scheduler() -> None:
    global _task, _stop_event
    if _task and not _task.done():
        return
    _stop_event = asyncio.Event()
    _task = asyncio.create_task(_scheduler_loop(), name="lecture-publish-scheduler")


async def stop_publish_scheduler() -> None:
    global _task, _stop_event
    if not _task:
        return
    if _stop_event:
        _stop_event.set()
    _task.cancel()
    await asyncio.gather(_task, return_exceptions=True)
    _task = None
    _stop_event = None
