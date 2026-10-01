import json
from typing import Any

from core.database.client import get_connection
from core.jobs.base import LeaseLost


async def create_lecture(
    *,
    user_id: int,
    title: str,
    topic: str,
    text_model: str,
    image_model: str,
    tts_model: str,
    tts_voice: str,
    generate_images: bool,
    moodle_course_id: int | None,
    moodle_section_num: int | None,
    moodle_deploy_mode: str,
    moodle_videotracker_cmid: int | None,
    upload_to_moodle: bool,
    portrait_path: str | None = None,
    target_duration_minutes: int = 40,
    target_slide_count: int = 10,
    review_before_video: bool = False,
    source_files: list[dict] | None = None,
    reference_mode: str = "rag",
    initial_status: str = "queued",
) -> int:
    if reference_mode not in {"rag", "full"}:
        raise ValueError("reference_mode must be 'rag' or 'full'.")

    if moodle_deploy_mode not in {
        "create",
        "existing",
    }:
        raise ValueError("moodle_deploy_mode must be 'create' or 'existing'.")

    db = await get_connection()

    try:
        cursor = await db.execute(
            """
            INSERT INTO lectures (
                user_id,
                title,
                topic,
                status,
                text_model,
                image_model,
                tts_model,
                tts_voice,
                generate_images,
                target_duration_minutes,
                target_slide_count,
                review_before_video,
                review_status,
                source_files_json,
                reference_mode,
                moodle_course_id,
                moodle_section_num,
                moodle_deploy_mode,
                moodle_videotracker_cmid,
                upload_to_moodle,
                portrait_path
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                title.strip(),
                topic.strip(),
                initial_status.strip(),
                text_model.strip(),
                image_model.strip(),
                tts_model.strip(),
                tts_voice.strip(),
                1 if generate_images else 0,
                int(target_duration_minutes),
                int(target_slide_count),
                1 if review_before_video else 0,
                "pending" if review_before_video else "not_required",
                json.dumps(source_files or [], ensure_ascii=False),
                reference_mode,
                moodle_course_id,
                moodle_section_num,
                moodle_deploy_mode,
                moodle_videotracker_cmid,
                1 if upload_to_moodle else 0,
                portrait_path,
            ),
        )

        await db.commit()
        return int(cursor.lastrowid)

    finally:
        await db.close()


async def update_lecture(
    lecture_id: int,
    *,
    run_token: str | None = None,
    publish_lease_token: str | None = None,
    **values: Any,
) -> None:
    if not values:
        return

    allowed = {
        "status",
        "progress",
        "status_message",
        "error_message",
        "moodle_course_id",
        "moodle_section_num",
        "moodle_deploy_mode",
        "moodle_videotracker_cmid",
        "portrait_path",
        "plan_json",
        "quiz_json",
        "review_status",
        "review_before_video",
        "source_files_json",
        "reference_mode",
        "pptx_path",
        "narration_path",
        "slides_video_path",
        "avatar_path",
        "final_video_path",
        "moodle_result_json",
    }

    invalid = set(values) - allowed

    if invalid:
        raise ValueError(f"Invalid lecture update fields: {sorted(invalid)}")

    serialized = {}

    for key, value in values.items():
        if key.endswith("_json") and value is not None and not isinstance(value, str):
            serialized[key] = json.dumps(
                value,
                ensure_ascii=False,
            )
        else:
            serialized[key] = value

    assignments = ", ".join(f"{key} = ?" for key in serialized)

    if run_token is not None and publish_lease_token is not None:
        raise ValueError("run_token and publish_lease_token are mutually exclusive")

    params = list(serialized.values())
    params.append(lecture_id)
    guard = ""
    if run_token is not None:
        guard = " AND run_token = ?"
        params.append(run_token)
    elif publish_lease_token is not None:
        guard = """
            AND EXISTS (
                SELECT 1
                FROM lecture_publish_schedules AS s
                JOIN users AS u ON u.id = s.user_id
                WHERE s.lecture_id = lectures.id
                  AND s.status = 'publishing'
                  AND s.lease_token = ?
                  AND s.lease_until > CURRENT_TIMESTAMP
                  AND u.status = 'active'
            )
        """
        params.append(publish_lease_token)

    db = await get_connection()

    try:
        cursor = await db.execute(
            f"""
            UPDATE lectures
            SET {assignments},
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ? {guard}
            """,
            params,
        )

        if (run_token is not None or publish_lease_token is not None) and cursor.rowcount != 1:
            raise LeaseLost("This worker no longer owns the lecture.")

        await db.commit()

    finally:
        await db.close()


def _deserialize(row):
    if row is None:
        return None

    item = dict(row)

    for key in (
        "plan_json",
        "quiz_json",
        "moodle_result_json",
        "source_files_json",
    ):
        if item.get(key):
            try:
                item[key] = json.loads(item[key])
            except (json.JSONDecodeError, TypeError):
                pass

    return item


async def get_lecture(
    lecture_id: int,
    *,
    user_id: int | None = None,
):
    db = await get_connection()

    try:
        if user_id is None:
            cursor = await db.execute(
                """
                SELECT *
                FROM lectures
                WHERE id = ?
                LIMIT 1
                """,
                (lecture_id,),
            )
        else:
            cursor = await db.execute(
                """
                SELECT *
                FROM lectures
                WHERE id = ?
                  AND user_id = ?
                LIMIT 1
                """,
                (
                    lecture_id,
                    user_id,
                ),
            )

        return _deserialize(await cursor.fetchone())

    finally:
        await db.close()


async def list_lectures(
    *,
    user_id: int,
    limit: int = 20,
    offset: int = 0,
):
    db = await get_connection()

    try:
        cursor = await db.execute(
            """
            SELECT *
            FROM lectures
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT ? OFFSET ?
            """,
            (
                user_id,
                limit,
                max(0, offset),
            ),
        )

        return [_deserialize(row) for row in await cursor.fetchall()]

    finally:
        await db.close()


async def list_lecture_queue_status(
    *,
    user_id: int,
    limit: int = 20,
):
    """Return recent lectures with durable queue/runtime metadata."""
    db = await get_connection()
    try:
        cursor = await db.execute(
            """
            SELECT
                l.id,
                l.title,
                l.status,
                l.progress,
                l.status_message,
                l.error_message,
                l.created_at,
                l.updated_at,
                j.status AS job_status,
                j.attempts,
                j.max_attempts,
                j.gpu_id,
                j.worker_id
            FROM lectures AS l
            LEFT JOIN lecture_jobs AS j
              ON j.lecture_id = l.id
            WHERE l.user_id = ?
            ORDER BY l.id DESC
            LIMIT ?
            """,
            (user_id, limit),
        )
        return [dict(row) for row in await cursor.fetchall()]
    finally:
        await db.close()
