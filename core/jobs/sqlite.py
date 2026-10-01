"""Single-host SQLite queue; transactions serialize claims across worker processes."""

import time

from core.config import positive_int
from core.database.client import get_connection
from core.jobs.base import Job
from core.jobs.sqlite_state import (
    acknowledge_completed_running_jobs,
    align_queued_lecture_projection,
    mark_job_claimed,
    rearm_source_failed_publish_schedule,
    recover_expired_leases,
    requeue_running_jobs_after_restart,
    running_job_count,
    select_next_queued_job,
)


class SQLiteJobQueue:
    def __init__(self):
        self.lease_seconds = positive_int("JOB_LEASE_SECONDS", 60)
        self.max_attempts = positive_int("JOB_MAX_ATTEMPTS", 3)
        self.capacity = positive_int("JOB_CONCURRENCY", 4)
        self.per_user_capacity = positive_int("MAX_RUNNING_JOBS_PER_USER", 1)
        self.retry_seconds = positive_int("JOB_RETRY_SECONDS", 10)

    async def enqueue(self, lecture_id: int) -> None:
        db = await get_connection()
        try:
            now = time.time()
            await db.execute(
                """
                INSERT OR IGNORE INTO lecture_jobs
                    (lecture_id, max_attempts, available_at, updated_at)
                SELECT l.id, ?, ?, ?
                FROM lectures AS l
                JOIN users AS u ON u.id = l.user_id
                WHERE l.id=? AND l.status='queued' AND u.status='active'
            """,
                (self.max_attempts, now, now, lecture_id),
            )
            await db.commit()
        finally:
            await db.close()

    async def reconcile(self) -> None:
        """Repair the commit/enqueue crash window, including pre-worker legacy jobs."""
        db = await get_connection()
        try:
            now = time.time()
            await db.execute(
                """
                INSERT OR IGNORE INTO lecture_jobs
                    (lecture_id, max_attempts, available_at, updated_at)
                SELECT l.id, ?, ?, ?
                FROM lectures AS l
                JOIN users AS u ON u.id = l.user_id
                WHERE l.status IN ('queued', 'running')
                  AND l.portrait_path IS NOT NULL
                  AND u.status='active'
            """,
                (self.max_attempts, now, now),
            )
            await db.commit()
        finally:
            await db.close()

    async def recover_after_supervisor_restart(self) -> dict[str, int]:
        """Recover durable jobs immediately after the local supervisor starts."""
        db = await get_connection()
        try:
            await db.execute("BEGIN IMMEDIATE")
            now = time.time()
            completed_count = await acknowledge_completed_running_jobs(db, now)
            recovered = await requeue_running_jobs_after_restart(db, now)
            await align_queued_lecture_projection(db)
            await db.commit()
            return {
                "recovered": recovered,
                "completed_acknowledged": completed_count,
            }
        except BaseException:
            await db.rollback()
            raise
        finally:
            await db.close()

    async def claim(self, worker_id: str) -> Job | None:
        db = await get_connection()
        try:
            await db.execute("BEGIN IMMEDIATE")
            now = time.time()
            await recover_expired_leases(db, now)

            if await running_job_count(db) >= self.capacity:
                await db.commit()
                return None

            row = await select_next_queued_job(db, now, self.per_user_capacity)
            if row is None:
                await db.commit()
                return None

            job = await mark_job_claimed(
                db,
                row,
                worker_id=worker_id,
                now=now,
                lease_seconds=self.lease_seconds,
            )
            await db.commit()
            return job
        except BaseException:
            await db.rollback()
            raise
        finally:
            await db.close()

    async def owns(self, job: Job) -> bool:
        db = await get_connection()
        try:
            row = await (
                await db.execute(
                    """
                SELECT 1
                FROM lecture_jobs AS j
                JOIN lectures AS l ON l.id = j.lecture_id
                JOIN users AS u ON u.id = l.user_id
                WHERE j.id=? AND j.status='running'
                  AND j.lease_token=? AND j.lease_until>?
                  AND u.status='active'
            """,
                    (job.id, job.token, time.time()),
                )
            ).fetchone()
            return row is not None
        finally:
            await db.close()

    async def heartbeat(self, job: Job) -> bool:
        db = await get_connection()
        try:
            now = time.time()
            cursor = await db.execute(
                """
                UPDATE lecture_jobs
                SET lease_until=?, updated_at=?
                WHERE id=? AND status='running' AND lease_token=? AND lease_until>?
                  AND EXISTS (
                        SELECT 1
                        FROM lectures AS l
                        JOIN users AS u ON u.id = l.user_id
                        WHERE l.id = lecture_jobs.lecture_id
                          AND u.status='active'
                  )
            """,
                (now + self.lease_seconds, now, job.id, job.token, now),
            )
            await db.commit()
            return cursor.rowcount == 1
        finally:
            await db.close()

    async def assign_gpu(self, job: Job, gpu_id: str) -> bool:
        db = await get_connection()
        try:
            now = time.time()
            cursor = await db.execute(
                """
                UPDATE lecture_jobs
                SET gpu_id=?, updated_at=?
                WHERE id=? AND status='running' AND lease_token=? AND lease_until>?
                  AND EXISTS (
                        SELECT 1
                        FROM lectures AS l
                        JOIN users AS u ON u.id = l.user_id
                        WHERE l.id = lecture_jobs.lecture_id
                          AND u.status='active'
                  )
            """,
                (gpu_id, now, job.id, job.token, now),
            )
            await db.commit()
            return cursor.rowcount == 1
        finally:
            await db.close()

    async def _settle(self, job, state, error=None, *, refund=False, delay=0) -> bool:
        db = await get_connection()
        try:
            await db.execute("BEGIN IMMEDIATE")
            now = time.time()
            cursor = await db.execute(
                """
                UPDATE lecture_jobs SET status=?, available_at=?, lease_token=NULL,
                    lease_until=NULL, worker_id=NULL, gpu_id=NULL, last_error=?, updated_at=?,
                    attempts=attempts-? WHERE id=? AND status='running'
                    AND lease_token=? AND lease_until>?
            """,
                (state, now + delay, error, now, int(refund), job.id, job.token, now),
            )
            if cursor.rowcount != 1:
                await db.rollback()
                return False
            message = {
                "queued": "작업 대기 중 · 저장된 단계부터 재개합니다.",
                "failed": "작업이 중단되었습니다.",
                "completed": "강의 생성이 완료되었습니다.",
            }[state]
            await db.execute(
                """
                UPDATE lectures SET status=?, run_token=NULL, status_message=?,
                    error_message=?, updated_at=CURRENT_TIMESTAMP
                WHERE id=? AND run_token=?
            """,
                (state, message, error, job.lecture_id, job.token),
            )
            if state == "completed":
                await rearm_source_failed_publish_schedule(db, job.lecture_id)
            await db.commit()
            return True
        except BaseException:
            await db.rollback()
            raise
        finally:
            await db.close()

    async def finish(self, job: Job) -> bool:
        return await self._settle(job, "completed")

    async def fail(self, job: Job, error: str, *, retryable: bool) -> bool:
        # max_attempts is persisted per job, even when the environment changes.
        db = await get_connection()
        try:
            row = await (
                await db.execute(
                    "SELECT max_attempts FROM lecture_jobs WHERE id=?", (job.id,)
                )
            ).fetchone()
        finally:
            await db.close()
        retry = bool(row and retryable and job.attempts < row["max_attempts"])
        return await self._settle(
            job,
            "queued" if retry else "failed",
            error[:2000],
            delay=min(self.retry_seconds * 2 ** (job.attempts - 1), 300)
            if retry
            else 0,
        )

    async def release(self, job: Job) -> bool:
        # Graceful shutdown does not spend a retry attempt.
        return await self._settle(job, "queued", refund=True)

    async def pause_for_review(self, job: Job) -> bool:
        db = await get_connection()
        try:
            await db.execute("BEGIN IMMEDIATE")
            now = time.time()
            cursor = await db.execute(
                """
                UPDATE lecture_jobs
                SET status='paused', lease_token=NULL, lease_until=NULL,
                    worker_id=NULL, gpu_id=NULL, last_error=NULL, updated_at=?,
                    attempts=CASE WHEN attempts > 0 THEN attempts - 1 ELSE 0 END
                WHERE id=? AND status='running' AND lease_token=? AND lease_until>?
            """,
                (now, job.id, job.token, now),
            )
            if cursor.rowcount != 1:
                await db.rollback()
                return False
            await db.execute(
                """
                UPDATE lectures
                SET status='awaiting_review', run_token=NULL,
                    review_status='awaiting_review',
                    status_message='PPT 검토 대기 중 · 승인하면 영상 생성을 이어갑니다.',
                    error_message=NULL, updated_at=CURRENT_TIMESTAMP
                WHERE id=? AND run_token=?
            """,
                (job.lecture_id, job.token),
            )
            await db.commit()
            return True
        except BaseException:
            await db.rollback()
            raise
        finally:
            await db.close()

    async def resume_review(self, lecture_id: int) -> bool:
        db = await get_connection()
        try:
            await db.execute("BEGIN IMMEDIATE")
            now = time.time()
            cursor = await db.execute(
                """
                UPDATE lecture_jobs
                SET status='queued', available_at=?, lease_token=NULL, lease_until=NULL,
                    worker_id=NULL, gpu_id=NULL, last_error=NULL, updated_at=?
                WHERE lecture_id=? AND status='paused'
            """,
                (now, now, lecture_id),
            )
            if cursor.rowcount:
                await db.execute(
                    """
                    UPDATE lectures
                    SET status='queued', run_token=NULL, error_message=NULL,
                        status_message='검토 반영 · 작업 재개 대기 중',
                        updated_at=CURRENT_TIMESTAMP
                    WHERE id=? AND status='awaiting_review'
                """,
                    (lecture_id,),
                )
            await db.commit()
            return cursor.rowcount == 1
        except BaseException:
            await db.rollback()
            raise
        finally:
            await db.close()

    async def cancel(self, lecture_id: int) -> bool:
        """Cancel only jobs that are still waiting in the durable queue."""
        db = await get_connection()
        try:
            await db.execute("BEGIN IMMEDIATE")
            now = time.time()
            cursor = await db.execute(
                """
                UPDATE lecture_jobs
                SET status='cancelled', lease_token=NULL, lease_until=NULL,
                    worker_id=NULL, gpu_id=NULL, last_error=NULL, updated_at=?
                WHERE lecture_id=? AND status='queued'
            """,
                (now, lecture_id),
            )
            if cursor.rowcount:
                await db.execute(
                    """
                    UPDATE lectures
                    SET status='cancelled', run_token=NULL,
                        status_message='사용자가 대기 중인 작업을 취소했습니다.',
                        error_message=NULL, updated_at=CURRENT_TIMESTAMP
                    WHERE id=? AND status='queued'
                """,
                    (lecture_id,),
                )
            await db.commit()
            return cursor.rowcount == 1
        except BaseException:
            await db.rollback()
            raise
        finally:
            await db.close()

    async def retry(self, lecture_id: int) -> bool:
        db = await get_connection()
        try:
            await db.execute("BEGIN IMMEDIATE")
            now = time.time()
            cursor = await db.execute(
                """
                UPDATE lecture_jobs SET status='queued', attempts=0, available_at=?,
                    last_error=NULL, updated_at=?
                WHERE lecture_id=? AND status='failed'
                  AND EXISTS (
                        SELECT 1
                        FROM lectures AS l
                        JOIN users AS u ON u.id = l.user_id
                        WHERE l.id = lecture_jobs.lecture_id
                          AND u.status='active'
                  )
            """,
                (now, now, lecture_id),
            )
            if cursor.rowcount:
                await db.execute(
                    """
                    UPDATE lectures SET status='queued', error_message=NULL,
                        status_message='재시도 대기 중', updated_at=CURRENT_TIMESTAMP WHERE id=?
                """,
                    (lecture_id,),
                )
            await db.commit()
            return cursor.rowcount == 1
        finally:
            await db.close()

    async def record_error(self, job: Job, error: str) -> None:
        db = await get_connection()
        try:
            await db.execute(
                """
                UPDATE lecture_jobs SET last_error=? WHERE id=?
                    AND lease_token=? AND status='running' AND lease_until>?
            """,
                (error[:2000], job.id, job.token, time.time()),
            )
            await db.commit()
        finally:
            await db.close()

    async def last_error(self, job: Job) -> str:
        db = await get_connection()
        try:
            row = await (
                await db.execute(
                    "SELECT last_error FROM lecture_jobs WHERE id=?", (job.id,)
                )
            ).fetchone()
            return (
                row["last_error"]
                if row and row["last_error"]
                else "작업 프로세스가 비정상 종료되었습니다."
            )
        finally:
            await db.close()
