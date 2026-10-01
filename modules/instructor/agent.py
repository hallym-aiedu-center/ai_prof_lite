from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

from core.config import data_dir
from core.jobs.factory import get_queue
from modules.credentials.required import require_user_openai_api_key
from modules.instructor.repository import (
    finalize_instructor_run,
    list_recent_agent_lecture_titles,
    update_instructor_run,
)
from modules.instructor.selection import _choose_course, _choose_lesson, _course_label
from modules.lecture.repository import (
    create_lecture,
    create_publish_schedule_config,
    update_lecture,
)
from modules.moodle.courses.service import get_course_sections, get_my_courses
from modules.moodle.service import get_user_moodle_client


async def _resolve_openai_key(user_id: int) -> str:
    return await require_user_openai_api_key(user_id)


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
        courses = [
            course for course in courses if int(course.get("id", -1)) in selected_ids
        ]
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
        user_id=user_id,
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
        user_id=user_id,
    )
    section_num = int(lesson["section"])
    section_name = next(
        (
            str(item.get("name") or "")
            for item in sections
            if int(item.get("section", -1)) == section_num
        ),
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
                "target_duration_minutes": int(
                    profile.get("target_duration_minutes") or 40
                ),
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
