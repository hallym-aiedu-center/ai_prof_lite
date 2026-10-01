from unittest.mock import AsyncMock

import pytest

from core.jobs.base import LeaseLost
from modules.lecture.publish_attempt_state import (
    release_not_ready,
    settle_ambiguous,
    settle_unexpected_failure,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("handler", [release_not_ready, settle_ambiguous])
async def test_lost_publish_lease_never_updates_lecture_projection(handler):
    update_schedule = AsyncMock(side_effect=LeaseLost("stale"))
    update_lecture = AsyncMock()
    kwargs = {
        "lecture_id": 7,
        "lease_token": "old-token",
        "update_publish_schedule_fn": update_schedule,
        "update_lecture_fn": update_lecture,
    }
    if handler is settle_ambiguous:
        kwargs["error"] = RuntimeError("ambiguous")

    await handler(**kwargs)

    update_lecture.assert_not_awaited()


@pytest.mark.asyncio
async def test_lost_publish_lease_during_retry_never_updates_lecture_projection():
    update_schedule = AsyncMock(side_effect=LeaseLost("stale"))
    update_lecture = AsyncMock()

    await settle_unexpected_failure(
        lecture_id=7,
        lease_token="old-token",
        error=RuntimeError("temporary"),
        attempts=1,
        max_attempts=3,
        retry_minutes=5,
        update_publish_schedule_fn=update_schedule,
        update_lecture_fn=update_lecture,
    )

    update_lecture.assert_not_awaited()
