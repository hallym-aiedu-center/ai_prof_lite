from typing import Any
from uuid import uuid4

from core.database.client import get_connection
from core.jobs.base import LeaseLost

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

