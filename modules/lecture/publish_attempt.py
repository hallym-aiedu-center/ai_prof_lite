from __future__ import annotations

import asyncio
import os

from core.jobs.base import LeaseLost
from core.jobs.errors import (
    AmbiguousDeploymentError,
    PublishNotReadyError,
    PublishSourceFailedError,
)
from modules.lecture.publish_attempt_state import (
    mark_attempt_started,
    mark_published,
    release_cancelled,
    release_not_ready,
    settle_ambiguous,
    settle_source_failed,
    settle_unexpected_failure,
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

        # A due schedule may arrive before rendering finishes. This readiness
        # check does not consume a Moodle upload attempt.
        await ensure_lecture_ready_for_publish_fn(lecture_id)

        attempts += 1
        await mark_attempt_started(
            lecture_id=lecture_id,
            lease_token=lease_token,
            attempts=attempts,
            update_publish_schedule_fn=update_publish_schedule_fn,
            update_lecture_fn=update_lecture_fn,
        )
        await deploy_lecture_to_moodle_fn(
            lecture_id,
            publish_lease_token=lease_token,
        )
        await mark_published(
            lecture_id=lecture_id,
            lease_token=lease_token,
            update_publish_schedule_fn=update_publish_schedule_fn,
        )
    except asyncio.CancelledError:
        await release_cancelled(
            lecture_id=lecture_id,
            lease_token=lease_token,
            update_publish_schedule_fn=update_publish_schedule_fn,
        )
        raise
    except LeaseLost:
        # Another process recovered an expired lease. Stale owners must stop.
        return
    except PublishNotReadyError:
        await release_not_ready(
            lecture_id=lecture_id,
            lease_token=lease_token,
            update_publish_schedule_fn=update_publish_schedule_fn,
            update_lecture_fn=update_lecture_fn,
        )
    except PublishSourceFailedError as exc:
        await settle_source_failed(
            lecture_id=lecture_id,
            lease_token=lease_token,
            error=exc,
            settle_source_failed_publish_schedule_fn=(
                settle_source_failed_publish_schedule_fn
            ),
            update_lecture_fn=update_lecture_fn,
        )
    except AmbiguousDeploymentError as exc:
        await settle_ambiguous(
            lecture_id=lecture_id,
            lease_token=lease_token,
            error=exc,
            update_publish_schedule_fn=update_publish_schedule_fn,
            update_lecture_fn=update_lecture_fn,
        )
    except Exception as exc:  # noqa: BLE001
        await settle_unexpected_failure(
            lecture_id=lecture_id,
            lease_token=lease_token,
            error=exc,
            attempts=attempts,
            max_attempts=_max_attempts(),
            retry_minutes=_retry_minutes(),
            update_publish_schedule_fn=update_publish_schedule_fn,
            update_lecture_fn=update_lecture_fn,
        )
