from __future__ import annotations

import asyncio
import json
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from core.config import data_dir
from core.openai.client import get_client
from modules.credentials.required import require_user_openai_api_key
from modules.instructor.repository import (
    finalize_instructor_run,
    list_recent_agent_lecture_titles,
    update_instructor_run,
)
from core.jobs.factory import get_queue
from modules.lecture.repository import (
    create_lecture,
    create_publish_schedule_config,
    update_lecture,
)
from modules.moodle.courses.service import get_course_sections, get_my_courses
from modules.moodle.service import get_user_moodle_client


async def _resolve_openai_key(user_id: int) -> str:
    return await require_user_openai_api_key(user_id)


def _course_label(course: dict) -> str:
    return str(
        course.get("displayname")
        or course.get("fullname")
        or course.get("shortname")
        or f"Course {course.get('id')}"
    )


async def _choose_course(
    *,
    api_key: str,
    model: str,
    courses: list[dict],
    instructions: str,
    recent_titles: list[str],
    week_number: int,
    total_weeks: int,
) -> tuple[dict, str]:
    if not courses:
        raise RuntimeError("AI 강사가 선택할 수 있는 Moodle 강좌가 없습니다.")

    client = get_client(api_key=api_key)
    course_items = [
        {
            "id": int(course["id"]),
            "name": _course_label(course),
            "shortname": str(course.get("shortname") or ""),
            "summary": str(course.get("summary") or "")[:500],
        }
        for course in courses[:30]
        if course.get("id") is not None
    ]
    allowed = {item["id"] for item in course_items}
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["course_id", "rationale"],
        "properties": {
            "course_id": {"type": "integer"},
            "rationale": {"type": "string", "minLength": 1, "maxLength": 300},
        },
    }
    prompt = f"""
당신은 Moodle에서 실제 강의를 운영하는 AI 강사입니다.
다음 강좌들 중 이번 자동 강의를 게시할 강좌 하나를 선택하세요.
이번 수업은 학기 {week_number}주차 / 총 {total_weeks}주차입니다.
가능하면 한 학기 흐름이 자연스럽게 이어지도록 최근 강의 기록을 참고하세요.

사용자 운영 지침:
{instructions or '강좌의 흐름에 맞게 유용한 강의를 지속적으로 제작한다.'}

최근 자동 강의 제목(중복 회피):
{json.dumps(recent_titles, ensure_ascii=False)}

접근 가능한 강좌:
{json.dumps(course_items, ensure_ascii=False)}

규칙:
- 반드시 제공된 course_id 중 하나만 선택하세요.
- 최근 강의와 같은 내용을 반복하지 마세요.
- 강좌 이름과 설명에 가장 자연스럽게 이어질 강좌를 선택하세요.
- 수강생 행동, 성적, 접속 통계 등 제공되지 않은 데이터를 상상하지 마세요.
- rationale은 한두 문장으로 짧게 설명하세요.
""".strip()

    try:
        response = await client.responses.create(
            model=model,
            input=prompt,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "ai_instructor_course_choice",
                    "strict": True,
                    "schema": schema,
                }
            },
        )
        payload = json.loads(response.output_text)
        course_id = int(payload["course_id"])
        if course_id not in allowed:
            raise ValueError("AI가 허용되지 않은 강좌를 선택했습니다.")
        selected = next(item for item in courses if int(item.get("id", -1)) == course_id)
        return selected, str(payload.get("rationale") or "AI 강좌 선택")
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        # A syntactically invalid structured answer can fall back deterministically.
        # Transport/auth/rate-limit/server failures must propagate so the planner can retry
        # instead of silently creating a lecture for an arbitrary course.
        return courses[0], "AI 선택 응답 형식을 사용할 수 없어 첫 번째 허용 강좌를 선택했습니다."


async def _choose_lesson(
    *,
    api_key: str,
    model: str,
    course: dict,
    sections: list[dict],
    instructions: str,
    recent_titles: list[str],
    week_number: int,
    total_weeks: int,
) -> dict:
    usable_sections = [
        {
            "section": int(section.get("section") or 0),
            "name": str(section.get("name") or f"Section {section.get('section')}"),
            "visible": int(section.get("visible", 1)),
        }
        for section in sections
        if section.get("section") is not None and int(section.get("visible", 1)) != 0
    ]
    if not usable_sections:
        raise RuntimeError("선택한 Moodle 강좌에 게시 가능한 섹션이 없습니다.")

    client = get_client(api_key=api_key)
    allowed_sections = {item["section"] for item in usable_sections}
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["section", "title", "topic", "rationale"],
        "properties": {
            "section": {"type": "integer"},
            "title": {"type": "string", "minLength": 1, "maxLength": 120},
            "topic": {"type": "string", "minLength": 30, "maxLength": 3000},
            "rationale": {"type": "string", "minLength": 1, "maxLength": 400},
        },
    }
    prompt = f"""
당신은 Moodle 강좌를 맡은 자율 AI 강사입니다.
이번 게시 슬롯에 맞춰 강의 섹션과 새 강의 주제를 스스로 결정하세요.
현재는 학기 {week_number}주차 / 총 {total_weeks}주차입니다.
초반 주차는 기초와 개념 형성, 중반은 적용/심화, 후반은 통합/정리 흐름이 되도록 주차 맥락을 반영하세요.

강좌:
- id: {course.get('id')}
- name: {_course_label(course)}
- summary: {str(course.get('summary') or '')[:1200]}

강좌 섹션:
{json.dumps(usable_sections, ensure_ascii=False)}

사용자 운영 지침:
{instructions or '강좌의 교육 흐름에 맞고 실무적으로 유용한 강의를 만든다.'}

최근 자동 강의 제목:
{json.dumps(recent_titles, ensure_ascii=False)}

규칙:
- section은 반드시 제공된 section 번호 중 하나만 고르세요.
- 최근 강의와 중복되지 않는 주제를 고르세요.
- title은 실제 강의 제목처럼 자연스러운 한국어로 작성하세요.
- topic에는 학습대상, 핵심 학습목표, 반드시 다룰 내용을 구체적으로 적으세요.
- 제공되지 않은 학습자 성적/행동 데이터를 지어내지 마세요.
- Moodle에 바로 올릴 수 있는 독립적인 1회 강의로 계획하세요.
- 이번 {week_number}주차가 전체 {total_weeks}주차 중 어디에 위치하는지 고려해 난이도와 내용을 정하세요.
- 제목 앞에 주차 번호를 억지로 붙이지 말고, 내용 자체가 주차 흐름에 맞도록 하세요.
""".strip()

    try:
        response = await client.responses.create(
            model=model,
            input=prompt,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "ai_instructor_lesson_choice",
                    "strict": True,
                    "schema": schema,
                }
            },
        )
        payload = json.loads(response.output_text)
        section_num = int(payload["section"])
        if section_num not in allowed_sections:
            raise ValueError("AI가 허용되지 않은 섹션을 선택했습니다.")
        return {
            "section": section_num,
            "title": str(payload["title"]).strip(),
            "topic": str(payload["topic"]).strip(),
            "rationale": str(payload.get("rationale") or "AI 강의 주제 선택"),
        }
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        section = usable_sections[0]
        course_name = _course_label(course)
        section_name = section["name"]
        return {
            "section": section["section"],
            "title": f"{course_name} · {section_name} 핵심 이해",
            "topic": (
                f"{course_name}의 {section_name}에 해당하는 핵심 개념을 설명하고, "
                "개념의 의미와 실제 적용 예시, 주의점을 단계적으로 학습할 수 있도록 구성하세요. "
                "최근 강의와 겹치지 않도록 해당 섹션에서 중요한 하나의 주제에 집중하세요."
            ),
            "rationale": "AI 응답을 사용할 수 없어 강좌의 첫 번째 게시 가능 섹션을 기준으로 구성했습니다.",
        }


async def create_delegated_lecture(
    *,
    run_id: int,
    planning_token: str,
    profile: dict,
    scheduled_at_utc: str,
    week_number: int,
    total_weeks: int,
) -> int:
    user_id = int(profile["user_id"])
    avatar_path = str(profile.get("avatar_path") or "").strip()
    if not avatar_path or not Path(avatar_path).is_file():
        raise RuntimeError("AI 강사 프로필에 사용할 아바타 이미지를 먼저 등록하세요.")

    api_key = await _resolve_openai_key(user_id)
    moodle = await get_user_moodle_client(user_id)
    courses = await get_my_courses(moodle)

    selected_ids = {int(v) for v in profile.get("selected_course_ids_json") or []}
    if profile.get("course_scope") == "selected":
        courses = [course for course in courses if int(course.get("id", -1)) in selected_ids]
    if not courses:
        raise RuntimeError("AI 강사에게 위임된 Moodle 강좌가 없습니다.")

    recent_titles = await list_recent_agent_lecture_titles(user_id)
    course, course_reason = await _choose_course(
        api_key=api_key,
        model=profile["text_model"],
        courses=courses,
        instructions=profile.get("instructions") or "",
        recent_titles=recent_titles,
        week_number=week_number,
        total_weeks=total_weeks,
    )
    sections = await get_course_sections(moodle, int(course["id"]))
    lesson = await _choose_lesson(
        api_key=api_key,
        model=profile["text_model"],
        course=course,
        sections=sections,
        instructions=profile.get("instructions") or "",
        recent_titles=recent_titles,
        week_number=week_number,
        total_weeks=total_weeks,
    )
    section_num = int(lesson["section"])
    section_name = next(
        (str(item.get("name") or "") for item in sections if int(item.get("section", -1)) == section_num),
        f"Section {section_num}",
    )

    # Persist the expensive planning result while we still own the lease.
    await update_instructor_run(
        run_id,
        planning_token=planning_token,
        course_id=int(course["id"]),
        course_name=_course_label(course),
        section_num=section_num,
        section_name=section_name,
        title=lesson["title"],
        topic=lesson["topic"],
        week_number=week_number,
        rationale=f"{week_number}주차/{total_weeks}주 · {course_reason} / {lesson['rationale']}",
        last_error=None,
    )

    # Keep the lecture invisible to the worker queue until every source file and
    # delayed-publish row is durable. finalize_instructor_run() flips both the
    # lecture and instructor run to queued in one SQLite transaction.
    lecture_id = await create_lecture(
        user_id=user_id,
        title=lesson["title"],
        topic=lesson["topic"],
        text_model=profile["text_model"],
        image_model=profile["image_model"],
        tts_model=profile["tts_model"],
        tts_voice=profile["tts_voice"],
        generate_images=bool(profile.get("generate_images", True)),
        target_duration_minutes=int(profile.get("target_duration_minutes") or 40),
        target_slide_count=int(profile.get("target_slide_count") or 10),
        moodle_course_id=int(course["id"]),
        moodle_section_num=section_num,
        moodle_deploy_mode="create",
        moodle_videotracker_cmid=None,
        upload_to_moodle=True,
        initial_status="planning",
    )
    await update_instructor_run(
        run_id,
        planning_token=planning_token,
        lecture_id=lecture_id,
    )

    await create_publish_schedule_config(
        lecture_id=lecture_id,
        user_id=user_id,
        mode="exact",
        weekday=None,
        hour=None,
        minute=0,
        timezone=profile.get("timezone") or "Asia/Seoul",
        scheduled_at=scheduled_at_utc,
    )

    source_dir = data_dir() / "lectures" / str(lecture_id) / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "lecture_settings.json").write_text(
        json.dumps(
            {
                "target_duration_minutes": int(profile.get("target_duration_minutes") or 40),
                "target_slide_count": int(profile.get("target_slide_count") or 10),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    lecture_portrait = source_dir / "portrait.png"
    await asyncio.to_thread(shutil.copyfile, avatar_path, lecture_portrait)

    await update_lecture(
        lecture_id,
        portrait_path=str(lecture_portrait),
        progress=1,
        status_message=f"AI 강사 {week_number}주차 강의 · 제작 대기 중",
    )
    await finalize_instructor_run(
        run_id=run_id,
        planning_token=planning_token,
        lecture_id=lecture_id,
    )

    # If the process dies after the atomic finalize but before this enqueue, the
    # durable worker reconcile loop will discover the queued lecture later.
    await get_queue().enqueue(lecture_id)
    return lecture_id

