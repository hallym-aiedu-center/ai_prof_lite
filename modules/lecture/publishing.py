from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from core.jobs.errors import AmbiguousDeploymentError, PublishNotReadyError
from core.openai.client import get_client
from modules.lecture.repository import (
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


WEEKDAY_KO = ["월", "화", "수", "목", "금", "토", "일"]


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
    return dt.astimezone(timezone.utc).replace(tzinfo=None).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def from_utc_sql(value: str, timezone_name: str) -> datetime:
    parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(
        tzinfo=timezone.utc
    )
    return parsed.astimezone(ZoneInfo(timezone_name))


async def choose_ai_publish_plan(
    *,
    api_key: str,
    title: str,
    topic: str,
    model: str,
    timezone_name: str,
    weekday_load: dict[int, int] | None = None,
) -> dict:
    zone = ZoneInfo(timezone_name)
    now_local = datetime.now(zone)
    client = get_client(api_key=api_key)
    weekday_load = weekday_load or {}
    load_text = ", ".join(
        f"{WEEKDAY_KO[i]}:{int(weekday_load.get(i, 0))}" for i in range(7)
    )

    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["weekday", "hour", "minute", "rationale"],
        "properties": {
            "weekday": {
                "type": "integer",
                "minimum": 0,
                "maximum": 6,
                "description": "0=Monday ... 6=Sunday",
            },
            "hour": {
                "type": "integer",
                "minimum": 8,
                "maximum": 21,
            },
            "minute": {
                "type": "integer",
                "enum": [0, 30],
            },
            "rationale": {
                "type": "string",
                "minLength": 1,
                "maxLength": 240,
            },
        },
    }

    prompt = f"""
당신은 온라인 강의 게시 스케줄러입니다.
현재 로컬 날짜/시각과 강의 주제를 보고, 이 강의를 Moodle에 올릴 다음 게시 요일과 시각을 정하세요.

현재 시각: {now_local.isoformat()}
타임존: {timezone_name}
강의 제목: {title}
강의 주제: {topic[:3000]}
현재 다른 강의 예약 건수(월~일): {load_text}

규칙:
- 월요일=0, 화요일=1, 수요일=2, 목요일=3, 금요일=4, 토요일=5, 일요일=6.
- 시각은 08:00~21:30 사이에서 고르세요.
- minute은 0 또는 30만 사용하세요.
- 외부 통계나 존재하지 않는 수강생 행동 데이터를 지어내지 마세요.
- 현재 날짜와 강의 성격을 우선 고려하되, 이미 예약이 몰린 요일은 가능하면 피해서 업로드를 분산하세요.
- 같은 요일/시각이 이미 지났다면 시스템이 자동으로 다음 주 해당 시점으로 보냅니다.
- rationale은 짧은 한국어 한 문장으로 작성하세요.
""".strip()

    try:
        response = await client.responses.create(
            model=model,
            input=prompt,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "lecture_publish_plan",
                    "strict": True,
                    "schema": schema,
                }
            },
        )
        payload = json.loads(response.output_text)
    except Exception:
        # Scheduling must never make an otherwise completed lecture fail just
        # because structured output is unavailable. Use a deterministic fallback.
        weekday = (now_local.weekday() + 1) % 7
        payload = {
            "weekday": weekday,
            "hour": 18,
            "minute": 0,
            "rationale": "자동 스케줄 응답을 얻지 못해 다음 가능한 저녁 시간으로 예약했습니다.",
        }

    weekday = int(payload["weekday"])
    hour = int(payload["hour"])
    minute = int(payload["minute"])
    if not 0 <= weekday <= 6:
        raise ValueError("AI publish weekday must be 0..6")
    if not 8 <= hour <= 21:
        raise ValueError("AI publish hour must be 8..21")
    if minute not in {0, 30}:
        raise ValueError("AI publish minute must be 0 or 30")

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

    final_video_path = lecture.get("final_video_path")
    if not final_video_path:
        raise PublishNotReadyError("최종 강의 영상 생성이 아직 완료되지 않았습니다.")
    return lecture


async def deploy_lecture_to_moodle(
    lecture_id: int,
    *,
    publish_lease_token: str | None = None,
) -> dict:
    """Deploy a completed lecture without blindly repeating Moodle activity creation.

    Delayed publications persist a create marker before the non-idempotent Moodle
    request.  If the process dies after Moodle creates the activity but before the
    response is durably recorded, the next attempt stops as ambiguous instead of
    creating a duplicate activity.
    """
    lecture = await ensure_lecture_ready_for_publish(lecture_id)
    final_video_path = lecture["final_video_path"]
    final_video = Path(final_video_path)
    if not final_video.is_file() or final_video.stat().st_size <= 0:
        raise RuntimeError(f"최종 강의 영상 파일을 확인할 수 없습니다: {final_video}")

    user_id = int(lecture["user_id"])
    moodle = await get_user_moodle_client(user_id)
    deploy_mode = lecture.get("moodle_deploy_mode") or "create"
    cmid = lecture.get("moodle_videotracker_cmid")
    activity_result = None

    if deploy_mode == "create":
        if not cmid:
            course_id = lecture.get("moodle_course_id")
            section_num = lecture.get("moodle_section_num")
            if course_id is None or section_num is None:
                raise RuntimeError("Moodle 강좌/섹션 정보가 없습니다.")

            schedule = await get_publish_schedule(lecture_id)
            if schedule is not None:
                if not publish_lease_token:
                    raise RuntimeError("예약 게시 작업의 lease token이 없습니다.")

                create_state = str(schedule.get("create_state") or "idle")
                if create_state == "completed":
                    try:
                        activity_result = json.loads(schedule.get("create_result_json") or "{}")
                        cmid = int(activity_result["cmid"])
                    except Exception as exc:
                        raise AmbiguousDeploymentError(
                            "저장된 Moodle 활동 생성 결과가 손상되었습니다. "
                            "Moodle에서 활동을 확인한 뒤 CMID를 수동으로 등록하세요."
                        ) from exc
                elif create_state == "running":
                    raise AmbiguousDeploymentError(
                        "이전 Moodle 활동 생성 요청의 결과가 불확실합니다. "
                        "Moodle에서 활동 존재 여부를 확인한 뒤 CMID를 등록하세요. "
                        "중복 생성을 막기 위해 자동 재생성은 중단했습니다."
                    )
                else:
                    await update_publish_schedule(
                        lecture_id,
                        lease_token=publish_lease_token,
                        create_state="running",
                        create_result_json=None,
                    )
                    try:
                        activity_result = await create_activity(
                            client=moodle,
                            course_id=int(course_id),
                            section_num=int(section_num),
                            name=lecture["title"],
                            intro="AI Professor Lite에서 자동 생성한 강의 영상입니다.",
                        )
                    except Exception as exc:
                        # Keep create_state='running'.  The remote side may have
                        # committed even when the response never reached us.
                        raise AmbiguousDeploymentError(
                            "Moodle 활동 생성 응답을 확인하지 못했습니다. "
                            "Moodle에서 생성 여부를 확인하세요."
                        ) from exc

                    cmid = int(activity_result["cmid"])
                    await update_publish_schedule(
                        lecture_id,
                        lease_token=publish_lease_token,
                        create_state="completed",
                        create_result_json=json.dumps(activity_result, ensure_ascii=False),
                    )
            else:
                # Backward-compatible direct use outside delayed publishing.
                activity_result = await create_activity(
                    client=moodle,
                    course_id=int(course_id),
                    section_num=int(section_num),
                    name=lecture["title"],
                    intro="AI Professor Lite에서 자동 생성한 강의 영상입니다.",
                )
                cmid = int(activity_result["cmid"])

            await update_lecture(
                lecture_id,
                moodle_videotracker_cmid=int(cmid),
            )
    elif deploy_mode == "existing":
        if not cmid:
            raise RuntimeError("기존 VideoTracker CMID가 선택되지 않았습니다.")
    else:
        raise RuntimeError(f"지원하지 않는 Moodle 배포 방식: {deploy_mode}")

    video_result = await set_video_from_file(
        client=moodle,
        cmid=int(cmid),
        path=final_video_path,
    )
    if isinstance(video_result, dict) and video_result.get("success") is False:
        raise RuntimeError("Moodle 영상 연결에 실패했습니다.")

    result = {
        "mode": deploy_mode,
        "cmid": int(cmid),
        "activity": activity_result,
        "video": video_result,
    }
    await update_lecture(
        lecture_id,
        moodle_result_json=result,
        status_message="Moodle 자동 업로드가 완료되었습니다.",
    )
    return result

