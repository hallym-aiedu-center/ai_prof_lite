from __future__ import annotations

import asyncio
import os

from core.jobs.base import LeaseLost
from modules.lecture.publish_attempt import (
    _run_claimed_publish as _run_claimed_publish_impl,
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
        except Exception as exc:
            # Fail closed: if ownership cannot be renewed/verified, the active
            # publish task must stop rather than continue external Moodle calls.
            raise LeaseLost("예약 게시 lease heartbeat 갱신에 실패했습니다.") from exc
        if not renewed:
            raise LeaseLost("예약 게시 lease 소유권을 잃었습니다.")


async def _run_claimed_publish(
    lecture_id: int,
    lease_token: str,
) -> None:
    await _run_claimed_publish_impl(
        lecture_id,
        lease_token,
        get_publish_schedule_fn=get_publish_schedule,
        ensure_lecture_ready_for_publish_fn=ensure_lecture_ready_for_publish,
        update_publish_schedule_fn=update_publish_schedule,
        update_lecture_fn=update_lecture,
        deploy_lecture_to_moodle_fn=deploy_lecture_to_moodle,
        settle_source_failed_publish_schedule_fn=(
            settle_source_failed_publish_schedule
        ),
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
        _run_claimed_publish(
            lecture_id,
            lease_token,
        ),
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
