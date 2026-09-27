import json
from typing import Any
from uuid import uuid4

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
    initial_status: str = "queued",
) -> int:
    if moodle_deploy_mode not in {
        "create",
        "existing",
    }:
        raise ValueError(
            "moodle_deploy_mode must be "
            "'create' or 'existing'."
        )

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
                moodle_course_id,
                moodle_section_num,
                moodle_deploy_mode,
                moodle_videotracker_cmid,
                upload_to_moodle,
                portrait_path
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

        "pptx_path",
        "narration_path",
        "slides_video_path",
        "avatar_path",
        "final_video_path",

        "moodle_result_json",
    }

    invalid = set(values) - allowed

    if invalid:
        raise ValueError(
            "Invalid lecture update fields: "
            f"{sorted(invalid)}"
        )

    serialized = {}

    for key, value in values.items():
        if (
            key.endswith("_json")
            and value is not None
            and not isinstance(value, str)
        ):
            serialized[key] = json.dumps(
                value,
                ensure_ascii=False,
            )
        else:
            serialized[key] = value

    assignments = ", ".join(
        f"{key} = ?"
        for key in serialized
    )

    params = list(
        serialized.values()
    )
    params.append(lecture_id)
    guard = ""
    if run_token is not None:
        guard = " AND run_token = ?"
        params.append(run_token)

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

        if run_token is not None and cursor.rowcount != 1:
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
    ):
        if item.get(key):
            try:
                item[key] = json.loads(
                    item[key]
                )
            except Exception:
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

        return _deserialize(
            await cursor.fetchone()
        )

    finally:
        await db.close()


async def list_lectures(
    *,
    user_id: int,
    limit: int = 20,
):
    db = await get_connection()

    try:
        cursor = await db.execute(
            """
            SELECT *
            FROM lectures
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (
                user_id,
                limit,
            ),
        )

        return [
            _deserialize(row)
            for row in await cursor.fetchall()
        ]

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


async def create_publish_schedule_config(
    *,
    lecture_id: int,
    user_id: int,
    mode: str,
    weekday: int | None,
    hour: int | None,
    minute: int,
    timezone: str,
    scheduled_at: str,
) -> None:
    """Create or replace the delayed Moodle publish configuration for a lecture."""
    if mode not in {"exact", "weekly", "ai"}:
        raise ValueError("Unsupported publish schedule mode")
    if weekday is not None and not 0 <= int(weekday) <= 6:
        raise ValueError("weekday must be 0..6")
    if hour is not None and not 0 <= int(hour) <= 23:
        raise ValueError("hour must be 0..23")
    if not 0 <= int(minute) <= 59:
        raise ValueError("minute must be 0..59")
    if not str(timezone).strip():
        raise ValueError("timezone is required")
    if not str(scheduled_at).strip():
        raise ValueError("scheduled_at is required")

    db = await get_connection()
    try:
        await db.execute(
            """
            INSERT INTO lecture_publish_schedules (
                lecture_id, user_id, mode, weekday, hour, minute, timezone,
                scheduled_at, status, attempts, last_error, published_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, NULL, NULL, CURRENT_TIMESTAMP)
            ON CONFLICT(lecture_id) DO UPDATE SET
                user_id = excluded.user_id,
                mode = excluded.mode,
                weekday = excluded.weekday,
                hour = excluded.hour,
                minute = excluded.minute,
                timezone = excluded.timezone,
                scheduled_at = excluded.scheduled_at,
                status = 'pending',
                attempts = 0,
                last_error = NULL,
                published_at = NULL,
                lease_token = NULL,
                lease_until = NULL,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                lecture_id, user_id, mode, weekday, hour, minute,
                timezone.strip(), scheduled_at.strip(),
            ),
        )
        await db.commit()
    finally:
        await db.close()


async def get_publish_schedule(lecture_id: int) -> dict | None:
    db = await get_connection()
    try:
        cursor = await db.execute(
            "SELECT * FROM lecture_publish_schedules WHERE lecture_id = ? LIMIT 1",
            (lecture_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def list_due_publish_schedule_ids(limit: int = 10) -> list[int]:
    """Return due pending rows plus abandoned publishing leases."""
    limit = max(1, min(100, int(limit)))
    db = await get_connection()
    try:
        cursor = await db.execute(
            """
            SELECT s.lecture_id
            FROM lecture_publish_schedules AS s
            JOIN lectures AS l ON l.id = s.lecture_id
            WHERE (
                    s.status = 'pending'
                    AND s.scheduled_at <= CURRENT_TIMESTAMP
                    AND (
                        l.final_video_path IS NOT NULL
                        OR l.status = 'failed'
                    )
                  )
               OR (
                    s.status = 'publishing'
                    AND (s.lease_until IS NULL OR s.lease_until <= CURRENT_TIMESTAMP)
                  )
            ORDER BY
                CASE
                    WHEN l.final_video_path IS NOT NULL THEN 0
                    WHEN l.status = 'failed' THEN 1
                    ELSE 2
                END,
                s.scheduled_at ASC,
                s.lecture_id ASC
            LIMIT ?
            """,
            (limit,),
        )
        return [int(row["lecture_id"]) for row in await cursor.fetchall()]
    finally:
        await db.close()


async def claim_publish_schedule(lecture_id: int, *, lease_seconds: int) -> str | None:
    """Claim a due/abandoned publication and return its ownership token."""
    lease_seconds = max(30, int(lease_seconds))
    token = uuid4().hex
    modifier = f"+{lease_seconds} seconds"
    db = await get_connection()
    try:
        await db.execute("BEGIN IMMEDIATE")
        cursor = await db.execute(
            """
            UPDATE lecture_publish_schedules
            SET status = 'publishing',
                lease_token = ?,
                lease_until = datetime('now', ?),
                updated_at = CURRENT_TIMESTAMP
            WHERE lecture_id = ?
              AND (
                    (status = 'pending' AND scheduled_at <= CURRENT_TIMESTAMP)
                 OR (status = 'publishing'
                     AND (lease_until IS NULL OR lease_until <= CURRENT_TIMESTAMP))
                  )
            """,
            (token, modifier, lecture_id),
        )
        await db.commit()
        return token if cursor.rowcount == 1 else None
    except BaseException:
        await db.rollback()
        raise
    finally:
        await db.close()


async def renew_publish_schedule_lease(
    lecture_id: int,
    lease_token: str,
    *,
    lease_seconds: int,
) -> bool:
    lease_seconds = max(30, int(lease_seconds))
    modifier = f"+{lease_seconds} seconds"
    db = await get_connection()
    try:
        cursor = await db.execute(
            """
            UPDATE lecture_publish_schedules
            SET lease_until = datetime('now', ?), updated_at = CURRENT_TIMESTAMP
            WHERE lecture_id = ?
              AND status = 'publishing'
              AND lease_token = ?
              AND lease_until > CURRENT_TIMESTAMP
            """,
            (modifier, lecture_id, lease_token),
        )
        await db.commit()
        return cursor.rowcount == 1
    finally:
        await db.close()


async def settle_source_failed_publish_schedule(
    lecture_id: int,
    *,
    lease_token: str,
    last_error: str,
) -> bool:
    """Atomically settle a source-failure observation against current lecture state.

    The scheduler may observe ``lectures.status == 'failed'`` and then lose the race
    to a user retry before it persists the publish failure.  Hold a SQLite write
    transaction while re-checking the lecture projection and updating the publish
    row so a recovered lecture can never be overwritten with a stale source failure.

    Returns ``True`` when the lecture is still failed and the publish schedule is
    closed as failed.  Returns ``False`` when the lecture has already recovered; in
    that case the schedule is returned to pending with its original scheduled time.
    """
    db = await get_connection()
    try:
        await db.execute("BEGIN IMMEDIATE")
        lecture = await (await db.execute(
            "SELECT status FROM lectures WHERE id = ? LIMIT 1",
            (lecture_id,),
        )).fetchone()
        still_failed = bool(lecture and lecture["status"] == "failed")

        if still_failed:
            cursor = await db.execute(
                """
                UPDATE lecture_publish_schedules
                SET status = 'failed',
                    last_error = ?,
                    lease_token = NULL,
                    lease_until = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE lecture_id = ?
                  AND status = 'publishing'
                  AND lease_token = ?
                """,
                (last_error[:1200], lecture_id, lease_token),
            )
        else:
            cursor = await db.execute(
                """
                UPDATE lecture_publish_schedules
                SET status = 'pending',
                    last_error = NULL,
                    lease_token = NULL,
                    lease_until = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE lecture_id = ?
                  AND status = 'publishing'
                  AND lease_token = ?
                """,
                (lecture_id, lease_token),
            )

        if cursor.rowcount != 1:
            await db.rollback()
            raise LeaseLost("This process no longer owns the publish schedule.")

        await db.commit()
        return still_failed
    except BaseException:
        await db.rollback()
        raise
    finally:
        await db.close()


async def update_publish_schedule(
    lecture_id: int,
    *,
    lease_token: str | None = None,
    clear_lease: bool = False,
    **values: Any,
) -> None:
    if not values and not clear_lease:
        return
    allowed = {
        "status", "scheduled_at", "attempts", "last_error", "published_at",
        "mode", "weekday", "hour", "minute", "timezone",
        "create_state", "create_result_json",
    }
    invalid = set(values) - allowed
    if invalid:
        raise ValueError(f"Invalid publish schedule fields: {sorted(invalid)}")

    assignments = [f"{key} = ?" for key in values]
    params = list(values.values())
    if clear_lease:
        assignments.extend(["lease_token = NULL", "lease_until = NULL"])
    assignments.append("updated_at = CURRENT_TIMESTAMP")

    where = "lecture_id = ?"
    params.append(lecture_id)
    if lease_token is not None:
        where += " AND status = 'publishing' AND lease_token = ?"
        params.append(lease_token)

    db = await get_connection()
    try:
        cursor = await db.execute(
            f"""
            UPDATE lecture_publish_schedules
            SET {', '.join(assignments)}
            WHERE {where}
            """,
            params,
        )
        if cursor.rowcount != 1:
            if lease_token is not None:
                raise LeaseLost("This process no longer owns the publish schedule.")
            raise ValueError("Publish schedule not found")
        await db.commit()
    finally:
        await db.close()

