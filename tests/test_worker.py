import asyncio
import os
import sys
from pathlib import Path

import pytest

from core.database.client import get_connection
from core.jobs.sqlite import SQLiteJobQueue
from modules.lecture.composer import run_process
from modules.lecture.repository import get_lecture, update_lecture
from worker import supervise


async def test_subprocess_timeout_terminates_child(tmp_path):
    pidfile = tmp_path / "pid"
    code = (
        "import os,time,pathlib; pathlib.Path("
        + repr(str(pidfile))
        + ").write_text(str(os.getpid())); time.sleep(30)"
    )
    with pytest.raises(TimeoutError):
        await run_process([sys.executable, "-c", code], timeout=0.5)
    with pytest.raises(ProcessLookupError):
        os.kill(int(pidfile.read_text()), 0)


async def test_runner_failure_is_persisted(make_lecture):
    queue = SQLiteJobQueue()
    lecture_id = await make_lecture()
    await queue.enqueue(lecture_id)
    job = await queue.claim("supervisor")
    gpu_pool = asyncio.Queue(maxsize=1)
    await supervise(
        queue, job, asyncio.Event(), "0", gpu_pool
    )  # Missing Ditto -> fails before network.
    result = await get_lecture(lecture_id)
    assert result["status"] == "failed"
    assert "FileNotFoundError" in result["error_message"]


async def test_graceful_stop_kills_process_group_and_requeues(
    make_lecture, monkeypatch, tmp_path
):
    queue = SQLiteJobQueue()
    lecture_id = await make_lecture()
    await queue.enqueue(lecture_id)
    job = await queue.claim("supervisor")
    real_spawn = asyncio.create_subprocess_exec
    created = asyncio.Event()
    processes = []
    pidfile = tmp_path / "child-pid"
    code = (
        'import subprocess,sys,time,pathlib; p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"]); '
        "pathlib.Path("
        + repr(str(pidfile))
        + ").write_text(str(p.pid)); time.sleep(30)"
    )

    async def spawn(*args, **kwargs):
        process = await real_spawn(sys.executable, "-c", code, start_new_session=True)
        processes.append(process)
        created.set()
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    stop = asyncio.Event()
    gpu_pool = asyncio.Queue(maxsize=1)
    task = asyncio.create_task(supervise(queue, job, stop, "0", gpu_pool))
    await created.wait()
    for _ in range(100):
        if pidfile.exists():
            break
        await asyncio.sleep(0.01)
    stop.set()
    await asyncio.wait_for(task, 10)
    assert processes[0].returncode is not None
    child = Path("/proc") / pidfile.read_text() / "stat"
    assert not child.exists() or child.read_text().split()[2] == "Z"
    assert (await get_lecture(lecture_id))["status"] == "queued"
    assert (await queue.claim("next")).attempts == 1


async def test_crash_after_pipeline_completion_is_acknowledged(
    make_lecture, monkeypatch
):
    monkeypatch.setenv("JOB_MAX_ATTEMPTS", "1")
    queue = SQLiteJobQueue()
    lecture_id = await make_lecture()
    await queue.enqueue(lecture_id)
    job = await queue.claim("dead-before-ack")
    await update_lecture(
        lecture_id, run_token=job.token, status="completed", progress=100
    )
    db = await get_connection()
    try:
        await db.execute("UPDATE lecture_jobs SET lease_until=0")
        await db.commit()
    finally:
        await db.close()
    assert await queue.claim("recovery") is None
    assert (await get_lecture(lecture_id))["status"] == "completed"
