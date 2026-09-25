import asyncio
import os
import sys
import time

import pytest

from core.database.client import get_connection
from core.database.migrations import init_database
from core.jobs.base import LeaseLost
from core.jobs.sqlite import SQLiteJobQueue
from modules.lecture.repository import get_lecture, update_lecture


async def sql(statement, values=()):
    db = await get_connection()
    try:
        cursor = await db.execute(statement, values)
        rows = await cursor.fetchall()
        await db.commit()
        return rows
    finally:
        await db.close()


async def test_migration_repeat_keeps_data(make_lecture):
    lecture_id = await make_lecture()
    await init_database()
    await init_database()
    assert (await get_lecture(lecture_id))['title'] == '테스트 강의'


async def test_enqueue_idempotent_and_claim_atomic(make_lecture):
    queue = SQLiteJobQueue()
    lecture_id = await make_lecture()
    await asyncio.gather(*(queue.enqueue(lecture_id) for _ in range(12)))
    claimed = await asyncio.gather(*(SQLiteJobQueue().claim(str(i)) for i in range(12)))
    assert len([j for j in claimed if j]) == 1
    assert len(await sql('SELECT * FROM lecture_jobs')) == 1


async def test_capacity_shared_across_processes(make_lecture, monkeypatch):
    monkeypatch.setenv('JOB_CONCURRENCY', '1')
    queue = SQLiteJobQueue()
    for _ in range(4):
        await queue.enqueue(await make_lecture())
    code = "import asyncio; from core.jobs.sqlite import SQLiteJobQueue; j=asyncio.run(SQLiteJobQueue().claim('child')); print(j.id if j else 'none')"
    processes = await asyncio.gather(*(asyncio.create_subprocess_exec(
        sys.executable, '-c', code, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env=os.environ.copy(),
    ) for _ in range(5)))
    outputs = await asyncio.gather(*(p.communicate() for p in processes))
    assert all(p.returncode == 0 for p in processes), outputs
    assert sum(out.strip() != b'none' for out, _ in outputs) == 1


async def test_expired_worker_cannot_update_or_ack(make_lecture):
    queue = SQLiteJobQueue()
    lecture_id = await make_lecture()
    await queue.enqueue(lecture_id)
    old = await queue.claim('old')
    await sql('UPDATE lecture_jobs SET lease_until=0')
    new = await queue.claim('new')
    assert new.attempts == 2 and old.token != new.token
    assert not await queue.heartbeat(old)
    assert not await queue.finish(old)
    with pytest.raises(LeaseLost):
        await update_lecture(lecture_id, run_token=old.token, progress=99)
    assert await queue.owns(new)


async def test_retry_backoff_max_attempts_and_manual_retry(make_lecture, monkeypatch):
    monkeypatch.setenv('JOB_MAX_ATTEMPTS', '2')
    queue = SQLiteJobQueue()
    lecture_id = await make_lecture()
    await queue.enqueue(lecture_id)
    first = await queue.claim('one')
    await queue.fail(first, 'temporary', retryable=True)
    assert await queue.claim('early') is None
    row = (await sql('SELECT * FROM lecture_jobs'))[0]
    assert row['available_at'] > time.time()
    await sql('UPDATE lecture_jobs SET available_at=0')
    second = await queue.claim('two')
    await queue.fail(second, 'temporary', retryable=True)
    assert (await get_lecture(lecture_id))['status'] == 'failed'
    assert await queue.retry(lecture_id)
    assert (await queue.claim('manual')).attempts == 1


async def test_graceful_release_refunds_attempt_and_reconcile_gap(make_lecture):
    queue = SQLiteJobQueue()
    lecture_id = await make_lecture()  # Simulates crash between DB commit and enqueue.
    await queue.reconcile()
    job = await queue.claim('first')
    assert job.lecture_id == lecture_id
    assert await queue.release(job)
    assert (await queue.claim('second')).attempts == 1


async def test_expired_last_attempt_is_terminal(make_lecture, monkeypatch):
    monkeypatch.setenv('JOB_MAX_ATTEMPTS', '1')
    queue = SQLiteJobQueue()
    lecture_id = await make_lecture()
    await queue.enqueue(lecture_id)
    await queue.claim('dead')
    await sql('UPDATE lecture_jobs SET lease_until=0')
    assert await queue.claim('replacement') is None
    assert (await get_lecture(lecture_id))['status'] == 'failed'


async def test_nonretryable_failure_is_not_requeued(make_lecture):
    queue = SQLiteJobQueue()
    lecture_id = await make_lecture()
    await queue.enqueue(lecture_id)
    await queue.fail(await queue.claim('worker'), 'bad input', retryable=False)
    assert await queue.claim('worker') is None
    assert (await get_lecture(lecture_id))['error_message'] == 'bad input'
