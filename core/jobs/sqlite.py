"""Single-host SQLite queue; transactions serialize claims across worker processes."""
import time
from uuid import uuid4

from core.config import positive_int
from core.database.client import get_connection
from core.jobs.base import Job


class SQLiteJobQueue:
    @staticmethod
    async def _rearm_source_failed_publish_schedule(db, lecture_id: int) -> None:
        """Re-activate a delayed publish only after lecture generation recovers.

        A source-generation failure is the only scheduler failure that happens
        before a Moodle upload attempt is spent, so ``attempts = 0`` is the
        durable discriminator.  Moodle/ambiguous deployment failures have
        ``attempts >= 1`` and must remain failed for explicit operator action.

        The schedule is intentionally re-armed on *successful job completion*,
        not when the user clicks retry.  This prevents a due schedule from
        publishing stale media while the retry is still rendering.
        """
        await db.execute("""
            UPDATE lecture_publish_schedules
            SET status='pending', last_error=NULL, lease_token=NULL,
                lease_until=NULL, updated_at=CURRENT_TIMESTAMP
            WHERE lecture_id=?
              AND status='failed'
              AND attempts=0
              AND published_at IS NULL
              AND COALESCE(create_state, 'idle')='idle'
              AND create_result_json IS NULL
        """, (lecture_id,))

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
            await db.execute("""
                INSERT OR IGNORE INTO lecture_jobs
                    (lecture_id, max_attempts, available_at, updated_at)
                SELECT id, ?, ?, ? FROM lectures WHERE id=? AND status='queued'
            """, (self.max_attempts, now, now, lecture_id))
            await db.commit()
        finally:
            await db.close()

    async def reconcile(self) -> None:
        """Repair the commit/enqueue crash window, including pre-worker legacy jobs."""
        db = await get_connection()
        try:
            now = time.time()
            await db.execute("""
                INSERT OR IGNORE INTO lecture_jobs
                    (lecture_id, max_attempts, available_at, updated_at)
                SELECT id, ?, ?, ? FROM lectures
                WHERE status IN ('queued', 'running') AND portrait_path IS NOT NULL
            """, (self.max_attempts, now, now))
            await db.commit()
        finally:
            await db.close()

    async def recover_after_supervisor_restart(self) -> dict[str, int]:
        """Recover durable jobs immediately after the one local supervisor starts.

        The worker singleton lock guarantees that no second Lite supervisor owns these
        rows on this host.  A previous app process may have died while a lease was still
        valid, so waiting for ``lease_until`` would unnecessarily strand the UI in
        ``queued``/``running``.  We therefore return every unfinished running job to the
        queue immediately and refund that interrupted attempt.

        Completed stage checkpoints are intentionally left untouched; the next runner
        validates their files and resumes from the first unfinished stage.
        """
        db = await get_connection()
        try:
            await db.execute("BEGIN IMMEDIATE")
            now = time.time()

            # A worker can die after the lecture transaction reached completed but before
            # the queue acknowledgement.  Never replay such a lecture.
            completed_lecture_rows = await (await db.execute("""
                SELECT lecture_id
                FROM lecture_jobs
                WHERE status='running'
                  AND lecture_id IN (SELECT id FROM lectures WHERE status='completed')
            """)).fetchall()
            completed = await db.execute("""
                UPDATE lecture_jobs
                SET status='completed', lease_token=NULL, lease_until=NULL,
                    worker_id=NULL, gpu_id=NULL, last_error=NULL, updated_at=?
                WHERE status='running'
                  AND lecture_id IN (SELECT id FROM lectures WHERE status='completed')
            """, (now,))
            completed_count = completed.rowcount
            for completed_row in completed_lecture_rows:
                await self._rearm_source_failed_publish_schedule(
                    db, int(completed_row['lecture_id'])
                )

            rows = await (await db.execute("""
                SELECT id, lecture_id, lease_token
                FROM lecture_jobs
                WHERE status='running'
            """)).fetchall()

            recovered = 0
            for row in rows:
                await db.execute("""
                    UPDATE lecture_jobs
                    SET status='queued',
                        attempts=CASE WHEN attempts > 0 THEN attempts - 1 ELSE 0 END,
                        available_at=?, lease_token=NULL, lease_until=NULL,
                        worker_id=NULL, gpu_id=NULL,
                        last_error='앱 재시작으로 작업을 이어서 실행합니다.', updated_at=?
                    WHERE id=? AND status='running'
                """, (now, now, row['id']))
                await db.execute("""
                    UPDATE lectures
                    SET status='queued', run_token=NULL, error_message=NULL,
                        status_message='앱 재시작 · 저장된 단계부터 재개 대기 중',
                        updated_at=CURRENT_TIMESTAMP
                    WHERE id=? AND status!='completed'
                """, (row['lecture_id'],))
                recovered += 1

            # Legacy/incomplete queue rows can exist after older versions.  Keep the
            # lecture projection aligned without touching completed/failed jobs.
            await db.execute("""
                UPDATE lectures
                SET status='queued', run_token=NULL, error_message=NULL,
                    status_message=COALESCE(status_message, '작업 대기 중'),
                    updated_at=CURRENT_TIMESTAMP
                WHERE status='running'
                  AND id IN (SELECT lecture_id FROM lecture_jobs WHERE status='queued')
            """)

            await db.commit()
            return {
                'recovered': recovered,
                'completed_acknowledged': completed_count,
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
            expired = await (await db.execute("""
                SELECT * FROM lecture_jobs WHERE status='running' AND lease_until<=?
            """, (now,))).fetchall()
            for row in expired:
                lecture = await (await db.execute(
                    'SELECT status FROM lectures WHERE id=?', (row['lecture_id'],)
                )).fetchone()
                if lecture and lecture['status'] == 'completed':
                    # Completion committed before a worker crash: acknowledge it.
                    await db.execute("""
                        UPDATE lecture_jobs SET status='completed', lease_token=NULL,
                            lease_until=NULL, worker_id=NULL, gpu_id=NULL, updated_at=? WHERE id=?
                    """, (now, row['id']))
                    await db.execute('UPDATE lectures SET run_token=NULL WHERE id=?', (row['lecture_id'],))
                    await self._rearm_source_failed_publish_schedule(
                        db, int(row['lecture_id'])
                    )
                    continue
                state = 'failed' if row['attempts'] >= row['max_attempts'] else 'queued'
                message = '워커 연결이 끊겨 재시도합니다.' if state == 'queued' else '워커 중단 후 최대 시도 횟수를 초과했습니다.'
                await db.execute("""
                    UPDATE lecture_jobs SET status=?, lease_token=NULL, lease_until=NULL,
                        worker_id=NULL, gpu_id=NULL, available_at=?, last_error=?, updated_at=? WHERE id=?
                """, (state, now, message, now, row['id']))
                await db.execute("""
                    UPDATE lectures SET status=?, run_token=NULL, status_message=?,
                        error_message=?, updated_at=CURRENT_TIMESTAMP
                    WHERE id=? AND run_token=? AND status!='completed'
                """, (state, message, message if state == 'failed' else None,
                      row['lecture_id'], row['lease_token']))
            count = (await (await db.execute(
                "SELECT COUNT(*) FROM lecture_jobs WHERE status='running'"
            )).fetchone())[0]
            if count >= self.capacity:
                await db.commit()
                return None
            row = await (await db.execute("""
                SELECT queued.*
                FROM lecture_jobs AS queued
                JOIN lectures AS queued_lecture ON queued_lecture.id = queued.lecture_id
                WHERE queued.status='queued'
                  AND queued.available_at<=?
                  AND (
                      SELECT COUNT(*)
                      FROM lecture_jobs AS running
                      JOIN lectures AS running_lecture ON running_lecture.id = running.lecture_id
                      WHERE running.status='running'
                        AND running_lecture.user_id = queued_lecture.user_id
                  ) < ?
                ORDER BY queued.available_at, queued.id
                LIMIT 1
            """, (now, self.per_user_capacity))).fetchone()
            if row is None:
                await db.commit()
                return None
            token = uuid4().hex
            await db.execute("""
                UPDATE lecture_jobs SET status='running', attempts=attempts+1,
                    lease_token=?, lease_until=?, worker_id=?, gpu_id=NULL, updated_at=? WHERE id=?
            """, (token, now + self.lease_seconds, worker_id, now, row['id']))
            await db.execute("""
                UPDATE lectures SET run_token=?,
                    status=CASE WHEN status='completed' THEN status ELSE 'running' END,
                    error_message=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=?
            """, (token, row['lecture_id']))
            await db.commit()
            return Job(row['id'], row['lecture_id'], token, row['attempts'] + 1)
        except BaseException:
            await db.rollback()
            raise
        finally:
            await db.close()

    async def owns(self, job: Job) -> bool:
        db = await get_connection()
        try:
            row = await (await db.execute("""
                SELECT 1 FROM lecture_jobs WHERE id=? AND status='running'
                    AND lease_token=? AND lease_until>?
            """, (job.id, job.token, time.time()))).fetchone()
            return row is not None
        finally:
            await db.close()

    async def heartbeat(self, job: Job) -> bool:
        db = await get_connection()
        try:
            now = time.time()
            cursor = await db.execute("""
                UPDATE lecture_jobs SET lease_until=?, updated_at=? WHERE id=?
                AND status='running' AND lease_token=? AND lease_until>?
            """, (now + self.lease_seconds, now, job.id, job.token, now))
            await db.commit()
            return cursor.rowcount == 1
        finally:
            await db.close()

    async def assign_gpu(self, job: Job, gpu_id: str) -> bool:
        db = await get_connection()
        try:
            now = time.time()
            cursor = await db.execute("""
                UPDATE lecture_jobs SET gpu_id=?, updated_at=? WHERE id=?
                AND status='running' AND lease_token=? AND lease_until>?
            """, (gpu_id, now, job.id, job.token, now))
            await db.commit()
            return cursor.rowcount == 1
        finally:
            await db.close()

    async def _settle(self, job, state, error=None, *, refund=False, delay=0) -> bool:
        db = await get_connection()
        try:
            await db.execute("BEGIN IMMEDIATE")
            now = time.time()
            cursor = await db.execute("""
                UPDATE lecture_jobs SET status=?, available_at=?, lease_token=NULL,
                    lease_until=NULL, worker_id=NULL, gpu_id=NULL, last_error=?, updated_at=?,
                    attempts=attempts-? WHERE id=? AND status='running'
                    AND lease_token=? AND lease_until>?
            """, (state, now + delay, error, now, int(refund), job.id, job.token, now))
            if cursor.rowcount != 1:
                await db.rollback()
                return False
            message = {'queued': '작업 대기 중 · 저장된 단계부터 재개합니다.',
                       'failed': '작업이 중단되었습니다.', 'completed': '강의 생성이 완료되었습니다.'}[state]
            await db.execute("""
                UPDATE lectures SET status=?, run_token=NULL, status_message=?,
                    error_message=?, updated_at=CURRENT_TIMESTAMP
                WHERE id=? AND run_token=?
            """, (state, message, error, job.lecture_id, job.token))
            if state == 'completed':
                await self._rearm_source_failed_publish_schedule(db, job.lecture_id)
            await db.commit()
            return True
        except BaseException:
            await db.rollback()
            raise
        finally:
            await db.close()

    async def finish(self, job: Job) -> bool:
        return await self._settle(job, 'completed')

    async def fail(self, job: Job, error: str, *, retryable: bool) -> bool:
        # max_attempts is persisted per job, even when the environment changes.
        db = await get_connection()
        try:
            row = await (await db.execute(
                'SELECT max_attempts FROM lecture_jobs WHERE id=?', (job.id,)
            )).fetchone()
        finally:
            await db.close()
        retry = bool(row and retryable and job.attempts < row['max_attempts'])
        return await self._settle(job, 'queued' if retry else 'failed', error[:2000],
                                  delay=min(self.retry_seconds * 2 ** (job.attempts - 1), 300) if retry else 0)

    async def release(self, job: Job) -> bool:
        # Graceful shutdown does not spend a retry attempt.
        return await self._settle(job, 'queued', refund=True)

    async def retry(self, lecture_id: int) -> bool:
        db = await get_connection()
        try:
            await db.execute('BEGIN IMMEDIATE')
            now = time.time()
            cursor = await db.execute("""
                UPDATE lecture_jobs SET status='queued', attempts=0, available_at=?,
                    last_error=NULL, updated_at=? WHERE lecture_id=? AND status='failed'
            """, (now, now, lecture_id))
            if cursor.rowcount:
                await db.execute("""
                    UPDATE lectures SET status='queued', error_message=NULL,
                        status_message='재시도 대기 중', updated_at=CURRENT_TIMESTAMP WHERE id=?
                """, (lecture_id,))
            await db.commit()
            return cursor.rowcount == 1
        finally:
            await db.close()

    async def record_error(self, job: Job, error: str) -> None:
        db = await get_connection()
        try:
            await db.execute("""
                UPDATE lecture_jobs SET last_error=? WHERE id=?
                    AND lease_token=? AND status='running' AND lease_until>?
            """, (error[:2000], job.id, job.token, time.time()))
            await db.commit()
        finally:
            await db.close()

    async def last_error(self, job: Job) -> str:
        db = await get_connection()
        try:
            row = await (await db.execute(
                'SELECT last_error FROM lecture_jobs WHERE id=?', (job.id,)
            )).fetchone()
            return row['last_error'] if row and row['last_error'] else '작업 프로세스가 비정상 종료되었습니다.'
        finally:
            await db.close()
