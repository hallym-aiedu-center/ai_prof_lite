from __future__ import annotations

import asyncio
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from core.config import PROJECT_ROOT, data_dir
from modules.auth.session import (
    current_user_id,
    get_csrf_token,
    login_redirect,
    verify_csrf,
)
from modules.credentials.required import (
    MissingCredentialError,
    require_user_openai_api_key,
)
from modules.lecture.uploads import normalize_uploaded_portrait
from modules.instructor.repository import (
    get_instructor_profile,
    list_instructor_runs,
    set_instructor_avatar,
    upsert_instructor_profile,
)
from modules.moodle.courses.service import get_my_courses
from modules.moodle.service import get_user_moodle_client
from modules.users.service import get_user

router = APIRouter(prefix="/instructor")
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "templates"))
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,79}$")
WEEKDAYS = [
    (0, "월"), (1, "화"), (2, "수"), (3, "목"), (4, "금"), (5, "토"), (6, "일"),
]


def _env_options(name: str, defaults: list[str], selected: str) -> list[str]:
    raw = os.getenv(name, "")
    values = [item.strip() for item in raw.split(",") if item.strip()] or defaults
    if selected and selected not in values:
        values.insert(0, selected)
    return list(dict.fromkeys(values))


def _validate_model(value: str, field: str) -> str:
    value = value.strip()
    if not _MODEL_RE.fullmatch(value):
        raise HTTPException(status_code=400, detail=f"잘못된 {field} 값입니다.")
    return value


def _default_semester_start(timezone_name: str) -> str:
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        zone = ZoneInfo("Asia/Seoul")
    today = datetime.now(zone).date()
    monday = today - timedelta(days=today.weekday())
    return monday.isoformat()


def _default_profile(user_id: int) -> dict:
    timezone_name = os.getenv("LECTURE_PUBLISH_TIMEZONE", "Asia/Seoul")
    return {
        "user_id": user_id,
        "enabled": False,
        "timezone": timezone_name,
        "weekdays_json": [0],
        "publish_hour": 18,
        "publish_minute": 0,
        "lead_hours": 24,
        "weekly_limit": 1,
        "semester_start_date": _default_semester_start(timezone_name),
        "semester_weeks": 15,
        "course_scope": "all",
        "selected_course_ids_json": [],
        "instructions": "",
        "avatar_path": None,
        "text_model": os.getenv("LECTURE_TEXT_MODEL", "gpt-5.1"),
        "image_model": os.getenv("LECTURE_IMAGE_MODEL", "gpt-image-2"),
        "tts_model": os.getenv("LECTURE_TTS_MODEL", "gpt-4o-mini-tts"),
        "tts_voice": os.getenv("LECTURE_TTS_VOICE", "alloy"),
        "generate_images": True,
        "target_duration_minutes": int(os.getenv("LECTURE_TARGET_DURATION_MINUTES", "40")),
        "target_slide_count": int(os.getenv("LECTURE_TARGET_SLIDE_COUNT", "10")),
    }


def _decorate_runs(runs: list[dict]) -> list[dict]:
    for item in runs:
        try:
            zone = ZoneInfo(item.get("timezone") or "Asia/Seoul")
            dt = datetime.strptime(item["scheduled_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            item["scheduled_local"] = dt.astimezone(zone).strftime("%m/%d %H:%M")
        except (ValueError, TypeError, ZoneInfoNotFoundError):
            item["scheduled_local"] = item.get("scheduled_at")
    return runs


def _semester_dates(profile: dict) -> tuple[date, date, int]:
    raw = str(profile.get("semester_start_date") or "").strip()
    try:
        start = date.fromisoformat(raw) if raw else date.fromisoformat(_default_semester_start(profile.get("timezone") or "Asia/Seoul"))
    except ValueError:
        start = date.fromisoformat(_default_semester_start(profile.get("timezone") or "Asia/Seoul"))
    weeks = max(1, min(30, int(profile.get("semester_weeks") or 15)))
    end = start + timedelta(days=weeks * 7 - 1)
    return start, end, weeks


def _next_slots(profile: dict, count: int = 6) -> list[dict]:
    try:
        zone = ZoneInfo(profile.get("timezone") or "Asia/Seoul")
    except ZoneInfoNotFoundError:
        zone = ZoneInfo("Asia/Seoul")
    now = datetime.now(zone)
    weekdays = {int(v) for v in profile.get("weekdays_json") or [] if 0 <= int(v) <= 6}
    hour_value = profile.get("publish_hour")
    hour = int(18 if hour_value is None else hour_value)
    minute = int(profile.get("publish_minute") or 0)
    start, end, total_weeks = _semester_dates(profile)
    results: list[dict] = []
    day = max(now.date(), start)
    while day <= end:
        candidate = datetime(day.year, day.month, day.day, hour, minute, tzinfo=zone)
        if candidate.weekday() in weekdays and candidate > now:
            week_number = ((day - start).days // 7) + 1
            results.append({
                "week": week_number,
                "total_weeks": total_weeks,
                "label": candidate.strftime("%m/%d %H:%M"),
                "weekday": WEEKDAYS[candidate.weekday()][1],
            })
            if len(results) >= count:
                break
        day += timedelta(days=1)
    return results


async def _load_courses(user_id: int) -> tuple[list[dict], str | None]:
    try:
        moodle = await get_user_moodle_client(user_id)
        courses = await get_my_courses(moodle)
        normalized = [
            {
                "id": int(course["id"]),
                "name": course.get("displayname") or course.get("fullname") or course.get("shortname") or f"Course {course['id']}",
                "shortname": course.get("shortname") or "",
            }
            for course in courses
            if course.get("id") is not None
        ]
        return normalized, None
    except Exception as exc:  # noqa: BLE001
        return [], str(exc)


async def _save_avatar_file(user_id: int, avatar: UploadFile) -> str:
    normalized = await normalize_uploaded_portrait(avatar)
    avatar_dir = data_dir() / "instructor" / str(user_id)
    avatar_dir.mkdir(parents=True, exist_ok=True)
    target = avatar_dir / "avatar.png"
    temporary = avatar_dir / "avatar.tmp"
    try:
        await asyncio.to_thread(temporary.write_bytes, normalized)
        await asyncio.to_thread(temporary.replace, target)
    finally:
        temporary.unlink(missing_ok=True)
    return str(target)


@router.get("")
async def instructor_home(request: Request):
    user_id = current_user_id(request)
    if user_id is None:
        return login_redirect()

    profile = await get_instructor_profile(user_id) or _default_profile(user_id)
    if not str(profile.get("semester_start_date") or "").strip():
        profile["semester_start_date"] = _default_semester_start(profile.get("timezone") or "Asia/Seoul")
    profile["semester_weeks"] = max(1, min(30, int(profile.get("semester_weeks") or 15)))
    courses, course_error = await _load_courses(user_id)
    models = {
        "text": _env_options("LECTURE_TEXT_MODEL_OPTIONS", ["gpt-5.1", "gpt-5", "gpt-4.1"], profile["text_model"]),
        "image": _env_options("LECTURE_IMAGE_MODEL_OPTIONS", ["gpt-image-2", "gpt-image-1"], profile["image_model"]),
        "tts": _env_options("LECTURE_TTS_MODEL_OPTIONS", ["gpt-4o-mini-tts", "tts-1", "tts-1-hd"], profile["tts_model"]),
        "voice": _env_options("LECTURE_TTS_VOICE_OPTIONS", ["alloy", "ash", "coral", "echo", "nova", "onyx", "sage", "shimmer", "verse"], profile["tts_voice"]),
    }
    return templates.TemplateResponse(
        request=request,
        name="instructor/index.html",
        context={
            "user": await get_user(user_id),
            "active_page": "instructor",
            "csrf_token": get_csrf_token(request),
            "profile": profile,
            "courses": courses,
            "course_error": course_error,
            "weekdays": WEEKDAYS,
            "models": models,
            "next_slots": _next_slots(profile),
            "semester_start": _semester_dates(profile)[0].isoformat(),
            "semester_end": _semester_dates(profile)[1].isoformat(),
        },
    )


@router.get("/activity")
async def instructor_activity(request: Request):
    user_id = current_user_id(request)
    if user_id is None:
        return login_redirect()

    runs = _decorate_runs(await list_instructor_runs(user_id, limit=100))
    return templates.TemplateResponse(
        request=request,
        name="instructor/activity.html",
        context={
            "user": await get_user(user_id),
            "active_page": "instructor_activity",
            "csrf_token": get_csrf_token(request),
            "runs": runs,
        },
    )


@router.post("")
async def save_instructor(
    request: Request,
    csrf_token: str = Form(...),
    enabled: str | None = Form(None),
    timezone_name: str = Form("Asia/Seoul"),
    weekdays: list[str] = Form(default=[]),
    publish_hour: int = Form(18),
    publish_minute: int = Form(0),
    lead_hours: int = Form(24),
    weekly_limit: int = Form(1),
    semester_start_date: str = Form(""),
    semester_weeks: int = Form(15),
    course_scope: str = Form("all"),
    selected_course_ids: list[str] = Form(default=[]),
    instructions: str = Form(""),
    text_model: str = Form("gpt-5.1"),
    image_model: str = Form("gpt-image-2"),
    tts_model: str = Form("gpt-4o-mini-tts"),
    tts_voice: str = Form("alloy"),
    target_duration_minutes: int = Form(40),
    target_slide_count: int = Form(10),
    generate_images: str | None = Form(None),
    avatar: UploadFile | None = File(None),
):
    user_id = current_user_id(request)
    if user_id is None:
        return login_redirect()
    verify_csrf(request, csrf_token)

    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(status_code=400, detail="유효하지 않은 타임존입니다.") from exc

    try:
        semester_start = date.fromisoformat(semester_start_date.strip())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="1주차 시작일을 올바른 날짜로 입력하세요.") from exc
    semester_weeks = max(1, min(30, int(semester_weeks)))

    weekday_values = sorted({int(value) for value in weekdays if value.isdigit() and 0 <= int(value) <= 6})
    if enabled is not None and not weekday_values:
        raise HTTPException(status_code=400, detail="AI 강사를 켜려면 게시 요일을 하나 이상 선택하세요.")
    if not 0 <= publish_hour <= 23 or publish_minute not in {0, 10, 20, 30, 40, 50}:
        raise HTTPException(status_code=400, detail="게시 시간이 올바르지 않습니다.")
    lead_hours = max(1, min(168, int(lead_hours)))
    weekly_limit = max(1, min(max(1, len(weekday_values)), int(weekly_limit)))
    target_duration_minutes = max(20, min(90, int(target_duration_minutes)))
    target_slide_count = max(8, min(12, int(target_slide_count)))
    if enabled is not None:
        zone = ZoneInfo(timezone_name)
        term_end = semester_start + timedelta(days=semester_weeks * 7)
        if datetime.now(zone).date() >= term_end:
            raise HTTPException(status_code=400, detail="이미 종료된 학기 일정입니다. 1주차 시작일이나 총 주차를 조정하세요.")
    if course_scope not in {"all", "selected"}:
        raise HTTPException(status_code=400, detail="잘못된 강좌 위임 범위입니다.")

    courses, course_load_error = await _load_courses(user_id)
    if enabled is not None and (course_load_error or not courses):
        raise HTTPException(
            status_code=400,
            detail=("AI 강사를 켜려면 Moodle 연결과 접근 가능한 강좌가 필요합니다. " + (course_load_error or "")),
        )

    if enabled is not None:
        try:
            await require_user_openai_api_key(user_id)
        except MissingCredentialError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    valid_course_ids = {int(course["id"]) for course in courses}
    selected_ids = sorted({int(v) for v in selected_course_ids if v.isdigit() and int(v) in valid_course_ids})
    if enabled is not None and course_scope == "selected" and not selected_ids:
        raise HTTPException(status_code=400, detail="선택 강좌 모드에서는 강좌를 하나 이상 지정하세요.")

    old = await get_instructor_profile(user_id) or _default_profile(user_id)
    avatar_path: str | None = None
    if avatar is not None and getattr(avatar, "filename", ""):
        avatar_path = await _save_avatar_file(user_id, avatar)
    if enabled is not None and not (avatar_path or old.get("avatar_path")):
        raise HTTPException(status_code=400, detail="AI 강사를 켜려면 기본 아바타 이미지를 등록하세요.")

    await upsert_instructor_profile(
        user_id=user_id,
        enabled=(enabled is not None),
        timezone=timezone_name,
        weekdays=weekday_values,
        publish_hour=publish_hour,
        publish_minute=publish_minute,
        lead_hours=lead_hours,
        weekly_limit=weekly_limit,
        semester_start_date=semester_start.isoformat(),
        semester_weeks=semester_weeks,
        course_scope=course_scope,
        selected_course_ids=selected_ids,
        instructions=instructions[:5000],
        avatar_path=avatar_path,
        text_model=_validate_model(text_model, "강의 설계 모델"),
        image_model=_validate_model(image_model, "이미지 모델"),
        tts_model=_validate_model(tts_model, "TTS 모델"),
        tts_voice=_validate_model(tts_voice, "TTS Voice"),
        generate_images=(generate_images is not None),
        target_duration_minutes=target_duration_minutes,
        target_slide_count=target_slide_count,
    )
    return RedirectResponse(url="/instructor?saved=1", status_code=303)


@router.post("/avatar")
async def upload_instructor_avatar(
    request: Request,
    csrf_token: str = Form(...),
    avatar: UploadFile = File(...),
):
    user_id = current_user_id(request)
    if user_id is None:
        return JSONResponse({"detail": "로그인이 필요합니다."}, status_code=401)
    verify_csrf(request, csrf_token)
    avatar_path = await _save_avatar_file(user_id, avatar)
    await set_instructor_avatar(user_id, avatar_path)
    return JSONResponse({"ok": True, "avatar_url": "/instructor/avatar"})


@router.get("/avatar")
async def instructor_avatar(request: Request):
    user_id = current_user_id(request)
    if user_id is None:
        return login_redirect()
    profile = await get_instructor_profile(user_id)
    path = Path(str((profile or {}).get("avatar_path") or ""))
    expected_root = (data_dir() / "instructor" / str(user_id)).resolve()
    try:
        resolved = path.resolve()
    except (OSError, RuntimeError):
        raise HTTPException(status_code=404)
    if not resolved.is_file() or expected_root not in resolved.parents:
        raise HTTPException(status_code=404)
    return FileResponse(resolved, media_type="image/png")
