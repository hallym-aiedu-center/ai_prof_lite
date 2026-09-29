from typing import Any
from uuid import uuid4

from core.database.client import get_connection
from core.jobs.base import LeaseLost


async def reserve_instructor_run(
    *,
    user_id: int,
    scheduled_at: str,
    timezone: str,
    week_number: int,
    lease_seconds: int,
    max_attempts: int,
    retry_minutes: int,
) -> tuple[int, str] | None:
    """Reserve a planning slot with a renewable lease.

    Failed planning attempts can be retried after a small backoff, while the
    UNIQUE(user_id, scheduled_at) key continues to prevent duplicate slots.
    """
    lease_seconds = max(60, int(lease_seconds))
    max_attempts = max(1, int(max_attempts))
    retry_minutes = max(1, int(retry_minutes))
    token = uuid4().hex
    lease_modifier = f"+{lease_seconds} seconds"
    retry_modifier = f"-{retry_minutes} minutes"

    db = await get_connection()
    try:
        await db.execute("BEGIN IMMEDIATE")
        active = await (
            await db.execute(
                "SELECT 1 FROM users WHERE id = ? AND status = 'active' LIMIT 1",
                (user_id,),
            )
        ).fetchone()
        if active is None:
            await db.commit()
            return None

        row = await (
            await db.execute(
                """
            SELECT id, status, planning_attempts, lecture_id, updated_at
            FROM ai_instructor_runs
            WHERE user_id = ? AND scheduled_at = ?
            LIMIT 1
            """,
                (user_id, scheduled_at),
            )
        ).fetchone()

        if row is None:
            cursor = await db.execute(
                """
                INSERT INTO ai_instructor_runs (
                    user_id, scheduled_at, timezone, week_number, status,
                    planning_token, planning_lease_until, planning_attempts
                ) VALUES (?, ?, ?, ?, 'planning', ?, datetime('now', ?), 1)
                """,
                (user_id, scheduled_at, timezone, week_number, token, lease_modifier),
            )
            run_id = int(cursor.lastrowid)
            await db.commit()
            return run_id, token

        attempts = int(row["planning_attempts"] or 0)
        if str(row["status"]) != "failed" or row["lecture_id"] is not None:
            await db.commit()
            return None
        if attempts >= max_attempts:
            await db.commit()
            return None

        retryable = await (
            await db.execute(
                """
            SELECT 1
            FROM ai_instructor_runs
            WHERE id = ?
              AND updated_at <= datetime('now', ?)
            """,
                (int(row["id"]), retry_modifier),
            )
        ).fetchone()
        if retryable is None:
            await db.commit()
            return None

        cursor = await db.execute(
            """
            UPDATE ai_instructor_runs
            SET status = 'planning',
                timezone = ?,
                week_number = ?,
                planning_token = ?,
                planning_lease_until = datetime('now', ?),
                planning_attempts = planning_attempts + 1,
                lecture_id = NULL,
                course_id = NULL,
                course_name = NULL,
                section_num = NULL,
                section_name = NULL,
                title = NULL,
                topic = NULL,
                rationale = NULL,
                last_error = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status = 'failed' AND lecture_id IS NULL
            """,
            (timezone, week_number, token, lease_modifier, int(row["id"])),
        )
        await db.commit()
        if cursor.rowcount != 1:
            return None
        return int(row["id"]), token
    except BaseException:
        await db.rollback()
        raise
    finally:
        await db.close()


async def renew_instructor_run_lease(
    run_id: int,
    planning_token: str,
    *,
    lease_seconds: int,
) -> bool:
    modifier = f"+{max(60, int(lease_seconds))} seconds"
    db = await get_connection()
    try:
        cursor = await db.execute(
            """
            UPDATE ai_instructor_runs
            SET planning_lease_until = datetime('now', ?),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND status = 'planning'
              AND planning_token = ?
              AND planning_lease_until > CURRENT_TIMESTAMP
              AND EXISTS (
                    SELECT 1
                    FROM users AS u
                    WHERE u.id = ai_instructor_runs.user_id
                      AND u.status = 'active'
              )
            """,
            (modifier, run_id, planning_token),
        )
        await db.commit()
        return cursor.rowcount == 1
    finally:
        await db.close()


async def update_instructor_run(
    run_id: int,
    *,
    planning_token: str | None = None,
    **values: Any,
) -> None:
    if not values:
        return
    allowed = {
        "status",
        "lecture_id",
        "course_id",
        "course_name",
        "section_num",
        "section_name",
        "title",
        "topic",
        "rationale",
        "last_error",
        "week_number",
    }
    invalid = set(values) - allowed
    if invalid:
        raise ValueError(f"Invalid instructor run fields: {sorted(invalid)}")

    assignments = [f"{key} = ?" for key in values]
    params = list(values.values())
    where = "id = ?"
    params.append(run_id)
    if planning_token is not None:
        where += (
            " AND status = 'planning' AND planning_token = ?"
            " AND EXISTS (SELECT 1 FROM users AS u"
            " WHERE u.id = ai_instructor_runs.user_id AND u.status = 'active')"
        )
        params.append(planning_token)

    db = await get_connection()
    try:
        cursor = await db.execute(
            f"""
            UPDATE ai_instructor_runs
            SET {", ".join(assignments)}, updated_at = CURRENT_TIMESTAMP
            WHERE {where}
            """,
            params,
        )
        if planning_token is not None and cursor.rowcount != 1:
            raise LeaseLost("This process no longer owns the instructor planning run.")
        await db.commit()
    finally:
        await db.close()
