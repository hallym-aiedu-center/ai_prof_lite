import asyncio
from unittest.mock import AsyncMock

import pytest

from core.jobs.base import LeaseLost
from modules.lecture import publish_scheduler


@pytest.mark.asyncio
async def test_publish_is_cancelled_when_heartbeat_loses_lease(monkeypatch):
    started = asyncio.Event()
    cancelled = asyncio.Event()
    lease_lost = False

    monkeypatch.setattr(
        publish_scheduler,
        "claim_publish_schedule",
        AsyncMock(return_value="lease-token"),
    )
    monkeypatch.setattr(
        publish_scheduler,
        "get_publish_schedule",
        AsyncMock(return_value={"attempts": 0}),
    )
    monkeypatch.setattr(
        publish_scheduler,
        "ensure_lecture_ready_for_publish",
        AsyncMock(return_value={"final_video_path": "final.mp4"}),
    )
    monkeypatch.setattr(publish_scheduler, "_heartbeat_seconds", lambda: 0)

    async def renew(*args, **kwargs):
        nonlocal lease_lost
        await started.wait()
        lease_lost = True
        return False

    async def update_schedule(*args, **kwargs):
        if lease_lost:
            raise LeaseLost("stale lease")

    async def deploy(*args, **kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    monkeypatch.setattr(publish_scheduler, "renew_publish_schedule_lease", renew)
    monkeypatch.setattr(publish_scheduler, "update_publish_schedule", update_schedule)
    monkeypatch.setattr(publish_scheduler, "update_lecture", AsyncMock())
    monkeypatch.setattr(publish_scheduler, "deploy_lecture_to_moodle", deploy)

    await asyncio.wait_for(publish_scheduler._run_one(123), timeout=1)

    assert started.is_set()
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_publish_heartbeat_error_fails_closed(monkeypatch):
    monkeypatch.setattr(publish_scheduler, "_heartbeat_seconds", lambda: 0)
    monkeypatch.setattr(
        publish_scheduler,
        "renew_publish_schedule_lease",
        AsyncMock(side_effect=RuntimeError("db unavailable")),
    )

    with pytest.raises(LeaseLost, match="heartbeat"):
        await publish_scheduler._lease_heartbeat(123, "lease-token")
