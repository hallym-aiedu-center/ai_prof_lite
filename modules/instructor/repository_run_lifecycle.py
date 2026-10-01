from core.database.client import get_connection
from core.jobs.base import LeaseLost
from modules.instructor.storage_cleanup import remove_planning_lecture_storage


async def finalize_instructor_run(
    *,
    run_id: int,
    planning_token: str,
    lecture_id: int,
) -> None:
    """Atomically expose the prepared lecture to workers and finalize the run."""
    db = await get_connection()
    try:
        await db.execute("BEGIN IMMEDIATE")
        owner = await (
            await db.execute(
                """
            SELECT 1 FROM ai_instructor_runs AS r
            JOIN users AS u ON u.id = r.user_id
            WHERE r.id = ? AND r.status = 'planning' AND r.planning_token = ?
              AND r.planning_lease_until > CURRENT_TIMESTAMP
              AND u.status = 'active'
            """,
                (run_id, planning_token),
            )
        ).fetchone()
        if owner is None:
            raise LeaseLost("This process no longer owns the instructor planning run.")

        lecture = await db.execute(
            """
            UPDATE lectures
            SET status = 'queued', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND status = 'planning'
              AND portrait_path IS NOT NULL
              AND id = (
                    SELECT lecture_id FROM ai_instructor_runs
                    WHERE id = ? AND status = 'planning' AND planning_token = ?
                      AND planning_lease_until > CURRENT_TIMESTAMP
              )
            """,
            (lecture_id, run_id, planning_token),
        )
        if lecture.rowcount != 1:
            raise RuntimeError(
                "Prepared instructor lecture is incomplete or already finalized."
            )

        run = await db.execute(
            """
            UPDATE ai_instructor_runs
            SET status = 'queued',
                planning_token = NULL,
                planning_lease_until = NULL,
                last_error = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status = 'planning' AND planning_token = ?
              AND planning_lease_until > CURRENT_TIMESTAMP
            """,
            (run_id, planning_token),
        )
        if run.rowcount != 1:
            raise LeaseLost("This process no longer owns the instructor planning run.")
        await db.commit()
    except BaseException:
        await db.rollback()
        raise
    finally:
        await db.close()


async def fail_instructor_run(
    *,
    run_id: int,
    planning_token: str,
    error: str,
    retryable: bool = True,
    max_attempts: int | None = None,
) -> bool:
    """Fail an owned planning attempt and remove its unqueued DB/filesystem state."""
    terminal_attempts = max(1, int(max_attempts or 1))
    deleted_lecture_id: int | None = None
    db = await get_connection()
    try:
        await db.execute("BEGIN IMMEDIATE")
        row = await (
            await db.execute(
                """
            SELECT lecture_id
            FROM ai_instructor_runs
            WHERE id = ? AND status = 'planning' AND planning_token = ?
              AND planning_lease_until > CURRENT_TIMESTAMP
            """,
                (run_id, planning_token),
            )
        ).fetchone()
        if row is None:
            await db.commit()
            return False

        lecture_id = row["lecture_id"]
        if lecture_id is not None:
            cursor = await db.execute(
                "DELETE FROM lectures WHERE id = ? AND status = 'planning'",
                (int(lecture_id),),
            )
            if cursor.rowcount == 1:
                deleted_lecture_id = int(lecture_id)

        cursor = await db.execute(
            """
            UPDATE ai_instructor_runs
            SET status = 'failed',
                lecture_id = NULL,
                planning_token = NULL,
                planning_lease_until = NULL,
                planning_attempts = CASE
                    WHEN ? THEN planning_attempts
                    ELSE MAX(planning_attempts, ?)
                END,
                last_error = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status = 'planning' AND planning_token = ?
              AND planning_lease_until > CURRENT_TIMESTAMP
            """,
            (retryable, terminal_attempts, error[:1200], run_id, planning_token),
        )
        if cursor.rowcount != 1:
            await db.rollback()
            return False
        await db.commit()
    except BaseException:
        await db.rollback()
        raise
    finally:
        await db.close()

    await remove_planning_lecture_storage(deleted_lecture_id)
    return True


async def recover_stale_instructor_runs() -> list[int]:
    """Recover planning rows left behind by a crashed web process.

    A fully finalized/queued lecture is preserved and returned so the caller can
    enqueue it. Partially prepared lectures are deleted and the run becomes a
    retryable failed reservation.
    """
    recovered_lecture_ids: list[int] = []
    deleted_lecture_ids: set[int] = set()
    db = await get_connection()
    try:
        await db.execute("BEGIN IMMEDIATE")
        rows = await (
            await db.execute(
                """
            SELECT r.id, r.lecture_id, l.status AS lecture_status,
                   u.status AS user_status
            FROM ai_instructor_runs AS r
            JOIN users AS u ON u.id = r.user_id
            LEFT JOIN lectures AS l ON l.id = r.lecture_id
            WHERE r.status = 'planning'
              AND (r.planning_lease_until IS NULL
                   OR r.planning_lease_until <= CURRENT_TIMESTAMP)
            ORDER BY r.id ASC
            """
            )
        ).fetchall()

        for row in rows:
            run_id = int(row["id"])
            lecture_id = row["lecture_id"]
            lecture_status = str(row["lecture_status"] or "")
            user_status = str(row["user_status"] or "")

            if user_status != "active":
                if lecture_id is not None and lecture_status == "planning":
                    cursor = await db.execute(
                        "DELETE FROM lectures WHERE id = ? AND status = 'planning'",
                        (int(lecture_id),),
                    )
                    if cursor.rowcount == 1:
                        deleted_lecture_ids.add(int(lecture_id))
                await db.execute(
                    """
                    UPDATE ai_instructor_runs
                    SET status = 'cancelled', planning_token = NULL,
                        planning_lease_until = NULL,
                        last_error = 'account inactive',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND status = 'planning'
                    """,
                    (run_id,),
                )
                continue

            if lecture_id is not None and lecture_status in {
                "queued",
                "running",
                "completed",
            }:
                await db.execute(
                    """
                    UPDATE ai_instructor_runs
                    SET status = 'queued', planning_token = NULL,
                        planning_lease_until = NULL, last_error = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND status = 'planning'
                    """,
                    (run_id,),
                )
                if lecture_status == "queued":
                    recovered_lecture_ids.append(int(lecture_id))
                continue

            if lecture_id is not None and lecture_status == "planning":
                cursor = await db.execute(
                    "DELETE FROM lectures WHERE id = ? AND status = 'planning'",
                    (int(lecture_id),),
                )
                if cursor.rowcount == 1:
                    deleted_lecture_ids.add(int(lecture_id))

            await db.execute(
                """
                UPDATE ai_instructor_runs
                SET status = 'failed', lecture_id = NULL, planning_token = NULL,
                    planning_lease_until = NULL,
                    last_error = 'planning lease expired; safe retry allowed',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = 'planning'
                """,
                (run_id,),
            )

        # Clean up the tiny create/link crash window. Only AI Instructor uses
        # the temporary lecture status='planning'; keep a grace period so a live
        # planner has time to attach the new lecture_id to its run.
        orphan_rows = await (
            await db.execute(
                """
                SELECT id FROM lectures
                WHERE status = 'planning'
                  AND created_at <= datetime('now', '-10 minutes')
                  AND id NOT IN (
                        SELECT lecture_id FROM ai_instructor_runs
                        WHERE lecture_id IS NOT NULL
                  )
                """
            )
        ).fetchall()
        for orphan in orphan_rows:
            orphan_id = int(orphan["id"])
            cursor = await db.execute(
                "DELETE FROM lectures WHERE id = ? AND status = 'planning'",
                (orphan_id,),
            )
            if cursor.rowcount == 1:
                deleted_lecture_ids.add(orphan_id)

        await db.commit()
    except BaseException:
        await db.rollback()
        raise
    finally:
        await db.close()

    for lecture_id in deleted_lecture_ids:
        await remove_planning_lecture_storage(lecture_id)
    return recovered_lecture_ids
