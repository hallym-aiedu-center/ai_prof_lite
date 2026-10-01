from __future__ import annotations

import contextlib
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from core.jobs.errors import (
    AmbiguousDeploymentError,
    PublishNotReadyError,
    PublishSourceFailedError,
)
from core.openai.client import get_client
from core.openai.usage import responses_create
from modules.lecture.composer import media_duration
from modules.lecture.moodle_deployment import (
    MoodleCreateState,
    MoodleDeploymentSpec,
    MoodleVideoState,
    deploy_moodle_video,
)
from modules.lecture.publish_planning import (
    WEEKDAY_KO,
    build_publish_prompt,
    fallback_publish_payload,
    publish_plan_schema,
    validate_publish_payload,
)
from modules.lecture.repository import (
    assert_publish_schedule_lease,
    get_lecture,
    get_publish_schedule,
    update_lecture,
    update_publish_schedule,
)
from modules.moodle.service import get_user_moodle_client
from modules.moodle.videotracker.service import (
    create_activity,
    set_video_from_file,
)

logger = logging.getLogger(__name__)


def weekday_name_ko(value: int | None) -> str:
    if value is None or not 0 <= int(value) <= 6:
        return "-"
    return WEEKDAY_KO[int(value)]


def next_weekday_datetime(
    *,
    weekday: int,
    hour: int,
    minute: int,
    timezone_name: str,
    now: datetime | None = None,
) -> datetime:
    zone = ZoneInfo(timezone_name)
    now_local = now.astimezone(zone) if now else datetime.now(zone)
    days_ahead = (weekday - now_local.weekday()) % 7
    candidate = (now_local + timedelta(days=days_ahead)).replace(
        hour=hour,
        minute=minute,
        second=0,
        microsecond=0,
    )
    # Do not create schedules that are effectively already due while the job
    # is still finishing. Same-day times inside the next 15 minutes move to
    # the next week.
    if candidate <= now_local + timedelta(minutes=15):
        candidate += timedelta(days=7)
    return candidate


def to_utc_sql(dt: datetime) -> str:
    return (
        dt.astimezone(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")
    )


def from_utc_sql(value: str, timezone_name: str) -> datetime:
    parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    return parsed.astimezone(ZoneInfo(timezone_name))


async def choose_ai_publish_plan(
    *,
    api_key: str,
    title: str,
    topic: str,
    model: str,
    timezone_name: str,
    weekday_load: dict[int, int] | None = None,
    user_id: int | None = None,
    lecture_id: int | None = None,
) -> dict:
    zone = ZoneInfo(timezone_name)
    now_local = datetime.now(zone)
    client = get_client(api_key=api_key)
    prompt = build_publish_prompt(
        now_local=now_local,
        timezone_name=timezone_name,
        title=title,
        topic=topic,
        weekday_load=weekday_load,
    )

    try:
        if user_id is None:
            raise ValueError("Tracked OpenAI Responses calls require user_id.")
        response = await responses_create(
            client,
            user_id=user_id,
            lecture_id=lecture_id,
            model=model,
            input=prompt,
            max_output_tokens=1200,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "lecture_publish_plan",
                    "strict": True,
                    "schema": publish_plan_schema(),
                }
            },
            usage_context={
                "operation": "lecture_publish_plan",
                "stage": "publishing.schedule",
            },
        )
        payload = json.loads(response.output_text)
    except Exception:
        logger.warning(
            "AI publish-plan generation failed; using deterministic fallback",
            exc_info=True,
        )
        payload = fallback_publish_payload(now_local)
    finally:
        close = getattr(client, "close", None)
        if close is not None:
            with contextlib.suppress(Exception):
                await close()

    weekday, hour, minute = validate_publish_payload(payload)
    scheduled_local = next_weekday_datetime(
        weekday=weekday,
        hour=hour,
        minute=minute,
        timezone_name=timezone_name,
        now=now_local,
    )
    return {
        "weekday": weekday,
        "hour": hour,
        "minute": minute,
        "timezone": timezone_name,
        "scheduled_local": scheduled_local,
        "scheduled_at": to_utc_sql(scheduled_local),
        "rationale": str(payload.get("rationale") or "AI 자동 예약"),
    }


async def ensure_lecture_ready_for_publish(lecture_id: int) -> dict:
    """Return the lecture once final media exists, without consuming a publish attempt.

    A scheduled publication can become due while the lecture worker is still rendering.
    That is a normal waiting state, not an upload failure.  A path that has already been
    recorded but points to a missing/empty file is treated as a real failure instead.
    """
    lecture = await get_lecture(lecture_id)
    if not lecture:
        raise RuntimeError("강의를 찾을 수 없습니다.")
    if not lecture.get("upload_to_moodle"):
        raise RuntimeError("이 강의는 Moodle 자동 업로드 대상이 아닙니다.")

    if lecture.get("status") == "failed":
        raise PublishSourceFailedError(
            "강의 생성이 실패하여 예약 게시를 진행할 수 없습니다."
        )

    final_video_path = lecture.get("final_video_path")
    if not final_video_path:
        raise PublishNotReadyError("최종 강의 영상 생성이 아직 완료되지 않았습니다.")
    return lecture


class _DirectCreateMarker:
    async def load(self) -> MoodleCreateState:
        return MoodleCreateState()

    async def mark_running(self) -> None:
        pass

    async def mark_completed(self, activity: dict) -> None:
        pass

    async def load_video(self) -> MoodleVideoState:
        return MoodleVideoState()

    async def mark_video_running(self) -> None:
        pass

    async def mark_video_completed(self, result) -> None:
        pass


class _PublishScheduleCreateMarker:
    def __init__(self, lecture_id: int, lease_token: str | None):
        self.lecture_id = lecture_id
        self.lease_token = lease_token

    def _require_lease_token(self) -> str:
        if not self.lease_token:
            raise RuntimeError("예약 게시 작업의 lease token이 없습니다.")
        return self.lease_token

    async def load(self) -> MoodleCreateState:
        lease_token = self._require_lease_token()
        await assert_publish_schedule_lease(self.lecture_id, lease_token)
        schedule = await get_publish_schedule(self.lecture_id)
        if schedule is None:
            raise RuntimeError("예약 게시 정보를 찾을 수 없습니다.")
        state = str(schedule.get("create_state") or "idle")
        if state != "completed":
            return MoodleCreateState(status=state)
        try:
            activity = json.loads(schedule.get("create_result_json") or "{}")
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AmbiguousDeploymentError(
                "저장된 Moodle 활동 생성 결과가 손상되었습니다. "
                "Moodle에서 활동을 확인한 뒤 CMID를 수동으로 등록하세요."
            ) from exc
        return MoodleCreateState(status="completed", activity=activity)

    async def mark_running(self) -> None:
        lease_token = self._require_lease_token()
        await update_publish_schedule(
            self.lecture_id,
            lease_token=lease_token,
            create_state="running",
            create_result_json=None,
        )

    async def mark_completed(self, activity: dict) -> None:
        lease_token = self._require_lease_token()
        await update_publish_schedule(
            self.lecture_id,
            lease_token=lease_token,
            create_state="completed",
            create_result_json=json.dumps(activity, ensure_ascii=False),
        )

    async def load_video(self) -> MoodleVideoState:
        lease_token = self._require_lease_token()
        await assert_publish_schedule_lease(self.lecture_id, lease_token)
        schedule = await get_publish_schedule(self.lecture_id)
        if schedule is None:
            raise RuntimeError("예약 게시 정보를 찾을 수 없습니다.")
        state = str(schedule.get("video_state") or "idle")
        if state != "completed":
            return MoodleVideoState(status=state)
        try:
            result = json.loads(schedule.get("video_result_json") or "null")
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AmbiguousDeploymentError(
                "저장된 Moodle 영상 연결 결과가 손상되었습니다. "
                "Moodle에서 실제 영상 연결 상태를 확인하세요."
            ) from exc
        return MoodleVideoState(status="completed", result=result)

    async def mark_video_running(self) -> None:
        lease_token = self._require_lease_token()
        await update_publish_schedule(
            self.lecture_id,
            lease_token=lease_token,
            video_state="running",
            video_result_json=None,
        )

    async def mark_video_completed(self, result) -> None:
        lease_token = self._require_lease_token()
        await update_publish_schedule(
            self.lecture_id,
            lease_token=lease_token,
            video_state="completed",
            video_result_json=json.dumps(result, ensure_ascii=False, default=str),
        )


async def deploy_lecture_to_moodle(
    lecture_id: int,
    *,
    publish_lease_token: str | None = None,
) -> dict:
    """Deploy a completed lecture through the shared Moodle coordinator."""
    lecture = await ensure_lecture_ready_for_publish(lecture_id)
    final_video_path = str(lecture["final_video_path"])
    final_video = Path(final_video_path)
    if not final_video.is_file() or final_video.stat().st_size <= 0:
        raise RuntimeError(f"최종 강의 영상 파일을 확인할 수 없습니다: {final_video}")
    duration = await media_duration(final_video)
    spec = MoodleDeploymentSpec.from_lecture(
        lecture,
        video_path=final_video_path,
        duration=duration,
    )
    # Every scheduled deployment uses the durable marker, even when an existing
    # CMID is selected.  Activity creation may be skipped, but video upload/attach
    # is still non-idempotent and must remain fenced across retries.
    schedule = await get_publish_schedule(lecture_id)
    if schedule is None:
        marker = _DirectCreateMarker()
    else:
        marker = _PublishScheduleCreateMarker(lecture_id, publish_lease_token)

    result = await deploy_moodle_video(
        spec,
        marker=marker,
        get_client=get_user_moodle_client,
        create_activity=create_activity,
        set_video_from_file=set_video_from_file,
    )

    payload = result.as_dict()
    if schedule is None:
        # Direct/manual uploads do not have a publish-schedule lease.
        if result.cmid != lecture.get("moodle_videotracker_cmid"):
            await update_lecture(lecture_id, moodle_videotracker_cmid=result.cmid)
        await update_lecture(
            lecture_id,
            moodle_result_json=payload,
            status_message="Moodle 자동 업로드가 완료되었습니다.",
        )
    else:
        lease_token = str(publish_lease_token or "")
        values = {
            "moodle_result_json": payload,
            "status_message": "Moodle 자동 업로드가 완료되었습니다.",
        }
        if result.cmid != lecture.get("moodle_videotracker_cmid"):
            values["moodle_videotracker_cmid"] = result.cmid
        await update_lecture(
            lecture_id,
            publish_lease_token=lease_token,
            **values,
        )
    return payload
