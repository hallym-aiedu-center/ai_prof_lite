"""SQLite queue state-transition helpers.

These helpers keep the transaction orchestration in ``SQLiteJobQueue`` small
while centralizing the SQL that mutates durable queue state.
"""

from uuid import uuid4

from core.jobs.base import Job


async def rearm_source_failed_publish_schedule(db, lecture_id: int) -> None:
    """Re-activate a delayed publish only after lecture generation recovers."""
    await db.execute(
        """
        UPDATE lecture_publish_schedules
        SET status='pending', last_error=NULL, lease_token=NULL,
            lease_until=NULL, updated_at=CURRENT_TIMESTAMP
        WHERE lecture_id=?
          AND status='failed'
          AND attempts=0
          AND published_at IS NULL
          AND COALESCE(create_state, 'idle')='idle'
          AND create_result_json IS NULL
    """,
        (lecture_id,),
    )


async def acknowledge_completed_running_jobs(db, now: float) -> int:
    rows = await (
        await db.execute(
            """
            SELECT lecture_id
            FROM lecture_jobs
            WHERE status='running'
              AND lecture_id IN (SELECT id FROM lectures WHERE status='completed')
        """
        )
    ).fetchall()
    cursor = await db.execute(
        """
        UPDATE lecture_jobs
        SET status='completed', lease_token=NULL, lease_until=NULL,
            worker_id=NULL, gpu_id=NULL, last_error=NULL, updated_at=?
        WHERE status='running'
          AND lecture_id IN (SELECT id FROM lectures WHERE status='completed')
    """,
        (now,),
    )
    for row in rows:
        await rearm_source_failed_publish_schedule(db, int(row["lecture_id"]))
    return cursor.rowcount


async def requeue_running_jobs_after_restart(db, now: float) -> int:
    rows = await (
        await db.execute(
            """
            SELECT id, lecture_id
            FROM lecture_jobs
            WHERE status='running'
        """
        )
    ).fetchall()

    recovered = 0
    for row in rows:
        await db.execute(
            """
            UPDATE lecture_jobs
            SET status='queued',
                attempts=CASE WHEN attempts > 0 THEN attempts - 1 ELSE 0 END,
                available_at=?, lease_token=NULL, lease_until=NULL,
                worker_id=NULL, gpu_id=NULL,
                last_error='앱 재시작으로 작업을 이어서 실행합니다.', updated_at=?
            WHERE id=? AND status='running'
        """,
            (now, now, row["id"]),
        )
        await db.execute(
            """
            UPDATE lectures
            SET status='queued', run_token=NULL, error_message=NULL,
                status_message='앱 재시작 · 저장된 단계부터 재개 대기 중',
                updated_at=CURRENT_TIMESTAMP
            WHERE id=? AND status!='completed'
        """,
            (row["lecture_id"],),
        )
        recovered += 1
    return recovered


async def align_queued_lecture_projection(db) -> None:
    await db.execute(
        """
        UPDATE lectures
        SET status='queued', run_token=NULL, error_message=NULL,
            status_message=COALESCE(status_message, '작업 대기 중'),
            updated_at=CURRENT_TIMESTAMP
        WHERE status='running'
          AND id IN (SELECT lecture_id FROM lecture_jobs WHERE status='queued')
    """
    )


async def recover_expired_leases(db, now: float) -> None:
    rows = await (
        await db.execute(
            "SELECT * FROM lecture_jobs WHERE status='running' AND lease_until<=?",
            (now,),
        )
    ).fetchall()

    for row in rows:
        lecture = await (
            await db.execute(
                "SELECT status FROM lectures WHERE id=?", (row["lecture_id"],)
            )
        ).fetchone()
        if lecture and lecture["status"] == "completed":
            await db.execute(
                """
                UPDATE lecture_jobs SET status='completed', lease_token=NULL,
                    lease_until=NULL, worker_id=NULL, gpu_id=NULL, updated_at=? WHERE id=?
            """,
                (now, row["id"]),
            )
            await db.execute(
                "UPDATE lectures SET run_token=NULL WHERE id=?",
                (row["lecture_id"],),
            )
            await rearm_source_failed_publish_schedule(db, int(row["lecture_id"]))
            continue

        state = "failed" if row["attempts"] >= row["max_attempts"] else "queued"
        message = (
            "워커 연결이 끊겨 재시도합니다."
            if state == "queued"
            else "워커 중단 후 최대 시도 횟수를 초과했습니다."
        )
        await db.execute(
            """
            UPDATE lecture_jobs SET status=?, lease_token=NULL, lease_until=NULL,
                worker_id=NULL, gpu_id=NULL, available_at=?, last_error=?, updated_at=? WHERE id=?
        """,
            (state, now, message, now, row["id"]),
        )
        await db.execute(
            """
            UPDATE lectures SET status=?, run_token=NULL, status_message=?,
                error_message=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=? AND run_token=? AND status!='completed'
        """,
            (
                state,
                message,
                message if state == "failed" else None,
                row["lecture_id"],
                row["lease_token"],
            ),
        )


async def running_job_count(db) -> int:
    row = await (
        await db.execute("SELECT COUNT(*) FROM lecture_jobs WHERE status='running'")
    ).fetchone()
    return int(row[0])


async def select_next_queued_job(db, now: float, per_user_capacity: int):
    return await (
        await db.execute(
            """
            SELECT queued.*
            FROM lecture_jobs AS queued
            JOIN lectures AS queued_lecture ON queued_lecture.id = queued.lecture_id
            JOIN users AS queued_user ON queued_user.id = queued_lecture.user_id
            WHERE queued.status='queued'
              AND queued.available_at<=?
              AND queued_user.status='active'
              AND (
                  SELECT COUNT(*)
                  FROM lecture_jobs AS running
                  JOIN lectures AS running_lecture ON running_lecture.id = running.lecture_id
                  WHERE running.status='running'
                    AND running_lecture.user_id = queued_lecture.user_id
              ) < ?
            ORDER BY queued.available_at, queued.id
            LIMIT 1
        """,
            (now, per_user_capacity),
        )
    ).fetchone()


async def mark_job_claimed(
    db,
    row,
    *,
    worker_id: str,
    now: float,
    lease_seconds: int,
) -> Job:
    token = uuid4().hex
    await db.execute(
        """
        UPDATE lecture_jobs SET status='running', attempts=attempts+1,
            lease_token=?, lease_until=?, worker_id=?, gpu_id=NULL, updated_at=? WHERE id=?
    """,
        (token, now + lease_seconds, worker_id, now, row["id"]),
    )
    await db.execute(
        """
        UPDATE lectures SET run_token=?,
            status=CASE WHEN status='completed' THEN status ELSE 'running' END,
            error_message=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=?
    """,
        (token, row["lecture_id"]),
    )
    return Job(row["id"], row["lecture_id"], token, row["attempts"] + 1)
