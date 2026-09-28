"""One isolated process per job, supervised by worker.py."""
import asyncio
import logging

logger = logging.getLogger(__name__)
import os
import signal
import sys

from dotenv import load_dotenv

from core.config import PROJECT_ROOT, positive_int
from core.jobs.base import Job, LeaseLost
from core.jobs.errors import retryable
from core.jobs.factory import get_queue


async def run(job: Job) -> int:
    from modules.lecture.service import run_lecture_job
    queue = get_queue()
    supervisor_pid_raw = os.getenv('LITE_SUPERVISOR_PID', '').strip()
    supervisor_pid = int(supervisor_pid_raw) if supervisor_pid_raw.isdigit() else None

    def assert_supervisor_alive():
        if supervisor_pid is None:
            return
        # A runner is a direct child of the embedded supervisor process.  If that
        # app process is hard-killed, Linux reparents us; stop the entire runner
        # process group immediately instead of continuing as an orphan.
        if os.getppid() != supervisor_pid:
            raise LeaseLost('앱 프로세스가 종료되어 작업을 안전하게 중단합니다.')
        try:
            os.kill(supervisor_pid, 0)
        except ProcessLookupError as exc:
            raise LeaseLost('앱 프로세스가 종료되어 작업을 안전하게 중단합니다.') from exc

    async def assert_owned():
        assert_supervisor_alive()
        if not await queue.owns(job):
            raise LeaseLost('작업 임대가 만료되었습니다.')

    async def monitor():
        while True:
            # Check parent death quickly; DB lease heartbeats can stay relatively sparse.
            await asyncio.sleep(min(positive_int('JOB_HEARTBEAT_SECONDS', 10), 2))
            await assert_owned()

    pipeline = asyncio.create_task(run_lecture_job(job, queue))
    watchdog = asyncio.create_task(monitor())
    try:
        await assert_owned()
        done, _ = await asyncio.wait({pipeline, watchdog}, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
        return 0
    except LeaseLost:
        # Also clean descendants if the supervisor itself was killed.
        if os.name == 'posix' and os.getpgrp() == os.getpid():
            os.killpg(os.getpgrp(), signal.SIGTERM)
        return 1
    except Exception as exc:
        logger.exception('Lecture %s failed', job.lecture_id)
        await queue.record_error(job, f'{type(exc).__name__}: {exc}')
        return 75 if retryable(exc) else 1
    finally:
        for task in (pipeline, watchdog):
            task.cancel()
        await asyncio.gather(pipeline, watchdog, return_exceptions=True)


def main():
    load_dotenv(PROJECT_ROOT / '.env')
    logging.basicConfig(level=logging.INFO)
    job_id, lecture_id, token, attempts = sys.argv[1:]
    raise SystemExit(asyncio.run(run(Job(int(job_id), int(lecture_id), token, int(attempts)))))


if __name__ == '__main__':
    main()
