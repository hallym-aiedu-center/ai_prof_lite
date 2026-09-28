import json

from core.database.client import get_connection


def _decode_profile(row) -> dict | None:
    if not row:
        return None
    item = dict(row)
    for key in ("weekdays_json", "selected_course_ids_json"):
        try:
            item[key] = json.loads(item.get(key) or "[]")
        except (json.JSONDecodeError, TypeError):
            item[key] = []
    item["enabled"] = bool(item.get("enabled"))
    item["generate_images"] = bool(item.get("generate_images"))
    item["semester_weeks"] = int(item.get("semester_weeks") or 15)
    item["target_duration_minutes"] = int(item.get("target_duration_minutes") or 40)
    item["target_slide_count"] = int(item.get("target_slide_count") or 10)
    return item


async def get_instructor_profile(user_id: int) -> dict | None:
    db = await get_connection()
    try:
        cursor = await db.execute(
            "SELECT * FROM ai_instructor_profiles WHERE user_id = ? LIMIT 1",
            (user_id,),
        )
        return _decode_profile(await cursor.fetchone())
    finally:
        await db.close()


async def upsert_instructor_profile(
    *,
    user_id: int,
    enabled: bool,
    timezone: str,
    weekdays: list[int],
    publish_hour: int,
    publish_minute: int,
    lead_hours: int,
    weekly_limit: int,
    semester_start_date: str,
    semester_weeks: int,
    course_scope: str,
    selected_course_ids: list[int],
    instructions: str,
    avatar_path: str | None,
    text_model: str,
    image_model: str,
    tts_model: str,
    tts_voice: str,
    generate_images: bool,
    target_duration_minutes: int,
    target_slide_count: int,
) -> None:
    db = await get_connection()
    try:
        await db.execute(
            """
            INSERT INTO ai_instructor_profiles (
                user_id, enabled, timezone, weekdays_json, publish_hour,
                publish_minute, lead_hours, weekly_limit, semester_start_date,
                semester_weeks, course_scope, selected_course_ids_json,
                instructions, avatar_path, text_model, image_model, tts_model,
                tts_voice, generate_images, target_duration_minutes, target_slide_count, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                enabled = excluded.enabled,
                timezone = excluded.timezone,
                weekdays_json = excluded.weekdays_json,
                publish_hour = excluded.publish_hour,
                publish_minute = excluded.publish_minute,
                lead_hours = excluded.lead_hours,
                weekly_limit = excluded.weekly_limit,
                semester_start_date = excluded.semester_start_date,
                semester_weeks = excluded.semester_weeks,
                course_scope = excluded.course_scope,
                selected_course_ids_json = excluded.selected_course_ids_json,
                instructions = excluded.instructions,
                avatar_path = COALESCE(excluded.avatar_path, ai_instructor_profiles.avatar_path),
                text_model = excluded.text_model,
                image_model = excluded.image_model,
                tts_model = excluded.tts_model,
                tts_voice = excluded.tts_voice,
                generate_images = excluded.generate_images,
                target_duration_minutes = excluded.target_duration_minutes,
                target_slide_count = excluded.target_slide_count,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                user_id,
                1 if enabled else 0,
                timezone,
                json.dumps(sorted(set(weekdays))),
                publish_hour,
                publish_minute,
                lead_hours,
                weekly_limit,
                semester_start_date,
                semester_weeks,
                course_scope,
                json.dumps(sorted(set(selected_course_ids))),
                instructions.strip(),
                avatar_path,
                text_model,
                image_model,
                tts_model,
                tts_voice,
                1 if generate_images else 0,
                target_duration_minutes,
                target_slide_count,
            ),
        )
        await db.commit()
    finally:
        await db.close()


async def list_enabled_profiles() -> list[dict]:
    db = await get_connection()
    try:
        cursor = await db.execute(
            "SELECT * FROM ai_instructor_profiles WHERE enabled = 1 ORDER BY user_id ASC"
        )
        return [_decode_profile(row) for row in await cursor.fetchall()]
    finally:
        await db.close()
