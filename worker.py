"""Usage: python worker.py. One supervisor process schedules jobs across GPUs."""

import asyncio
import contextlib
import fcntl
import logging
import os
import signal
import socket
import sys
import time
from uuid import uuid4

from dotenv import load_dotenv

from core.config import PROJECT_ROOT, data_dir, job_gpu_ids, positive_int

load_dotenv(PROJECT_ROOT / ".env")

from core.database.migrations import init_database
from core.jobs.factory import get_queue

logger = logging.getLogger("uvicorn.error")


def acquire_worker_lock():
    """Prevent a second local supervisor from double-booking the same GPUs."""
    lock_path = data_dir() / "lecture-worker.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        handle.close()
        raise RuntimeError(
            f"Another lecture worker supervisor is already running ({lock_path})."
        ) from exc
    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()))
    handle.flush()
    return handle


def _is_our_runner(pid: int) -> bool:
    """Return True only for an orphaned runner launched from this project root."""
    if pid <= 1 or pid == os.getpid():
        return False
    proc = f"/proc/{pid}"
    try:
        if os.stat(proc).st_uid != os.getuid():
            return False
        cwd = os.path.realpath(f"{proc}/cwd")
        if cwd != str(PROJECT_ROOT.resolve()):
            return False
        with open(f"{proc}/cmdline", "rb") as file_handle:
            raw = file_handle.read()
        argv = [part.decode("utf-8", "replace") for part in raw.split(b"\0") if part]
    except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
        return False
    return len(argv) >= 3 and "-m" in argv and "core.jobs.runner" in argv


def _runner_pids() -> list[int]:
    if not os.path.isdir("/proc"):
        return []
    result = []
    for name in os.listdir("/proc"):
        if name.isdigit():
            pid = int(name)
            if _is_our_runner(pid):
                result.append(pid)
    return sorted(result)


def _signal_runner(pid: int, sig: signal.Signals) -> None:
    try:
        pgid = os.getpgid(pid)
        # Runners are created with start_new_session=True, so normally pgid==pid.
        # Never signal our own group if a malformed/legacy process is encountered.
        if pgid != os.getpgrp():
            os.killpg(pgid, sig)
        else:
            os.kill(pid, sig)
    except (ProcessLookupError, PermissionError):
        pass


async def terminate_leftover_runners() -> int:
    """Kill runner trees left behind by a previous crashed/reloaded app process."""
    pids = _runner_pids()
    if not pids:
        return 0
    logger.warning("Found %s leftover lecture runner(s): %s", len(pids), pids)
    for pid in pids:
        _signal_runner(pid, signal.SIGTERM)

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        alive = [pid for pid in pids if _is_our_runner(pid)]
        if not alive:
            return len(pids)
        await asyncio.sleep(0.1)

    for pid in pids:
        if _is_our_runner(pid):
            _signal_runner(pid, signal.SIGKILL)
    await asyncio.sleep(0.1)
    return len(pids)


async def kill_tree(process):
    if getattr(process, "_lite_group_cleaned", False):
        return
    process._lite_group_cleaned = True
    # Runners lead process groups; Ditto/FFmpeg inherit the runner's group.
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        await asyncio.wait_for(process.wait(), 5)
    except asyncio.TimeoutError:
        pass
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
    await process.wait()


async def supervise(
    queue, job, stop: asyncio.Event, gpu_id: str, gpu_pool: asyncio.Queue
):
    process = None
    interval = positive_int("JOB_HEARTBEAT_SECONDS", 10)
    timeout = positive_int("JOB_TIMEOUT_SECONDS", 7200)
    wait_task = stop_task = None
    try:
        if not await queue.heartbeat(job):
            return
        if not await queue.assign_gpu(job, gpu_id):
            logger.warning("Lease lost before GPU assignment for job %s", job.id)
            return

        env = os.environ.copy()
        # Pin the complete runner tree (Ditto/TensorRT included) to exactly one
        # physical GPU.  DITTO_GPU is removed so avatar.py cannot override it.
        env["CUDA_VISIBLE_DEVICES"] = gpu_id
        env["LITE_ASSIGNED_GPU"] = gpu_id
        env["LITE_SUPERVISOR_PID"] = str(os.getpid())
        env.pop("DITTO_GPU", None)

        logger.info(
            "Starting job %s (lecture %s) on GPU %s",
            job.id,
            job.lecture_id,
            gpu_id,
        )
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "core.jobs.runner",
            str(job.id),
            str(job.lecture_id),
            job.token,
            str(job.attempts),
            cwd=PROJECT_ROOT,
            env=env,
            start_new_session=True,
            stdin=asyncio.subprocess.DEVNULL,
        )
        wait_task = asyncio.create_task(process.wait())
        stop_task = asyncio.create_task(stop.wait())
        started = time.monotonic()
        while True:
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                await kill_tree(process)
                await queue.fail(
                    job, "전체 작업 제한 시간을 초과했습니다.", retryable=True
                )
                return
            done, _ = await asyncio.wait(
                {wait_task, stop_task},
                timeout=min(interval, remaining),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if stop_task in done:
                await kill_tree(process)
                await queue.release(job)
                return
            if wait_task in done:
                if process.returncode == 0:
                    await queue.finish(job)
                elif process.returncode == 3:
                    await queue.pause_for_review(job)
                else:
                    await queue.fail(
                        job,
                        await queue.last_error(job),
                        retryable=process.returncode == 75 or process.returncode < 0,
                    )
                return
            if not await queue.heartbeat(job):
                logger.warning(
                    "Lease lost for job %s; stopping its process group", job.id
                )
                await kill_tree(process)
                return
    except asyncio.CancelledError:
        if process is not None:
            await kill_tree(process)
        await queue.release(job)
        raise
    except Exception:
        if process is not None:
            await kill_tree(process)
        logger.exception(
            "Supervisor failed for job %s; lease recovery will retry it", job.id
        )
    finally:
        if process is not None:
            await kill_tree(process)
        for task in (wait_task, stop_task):
            if task is not None:
                task.cancel()
        await asyncio.gather(
            *(task for task in (wait_task, stop_task) if task),
            return_exceptions=True,
        )
        gpu_pool.put_nowait(gpu_id)
        logger.info("GPU %s released by job %s", gpu_id, job.id)


async def serve(
    stop: asyncio.Event | None = None,
    *,
    install_signal_handlers: bool = True,
    ready: asyncio.Event | None = None,
):
    if os.name != "posix":
        raise RuntimeError("The Lite media worker requires Linux/POSIX process groups.")
    if positive_int("JOB_HEARTBEAT_SECONDS", 10) * 3 >= positive_int(
        "JOB_LEASE_SECONDS", 60
    ):
        raise ValueError(
            "JOB_LEASE_SECONDS must be greater than 3 * JOB_HEARTBEAT_SECONDS"
        )

    slots = positive_int("JOB_CONCURRENCY", 4)
    gpu_ids = job_gpu_ids(concurrency=slots)
    worker_lock = acquire_worker_lock()

    # The lock proves this is the only local supervisor.  Clean up runner trees
    # orphaned by a previous hard crash/reloader kill before touching their DB leases.
    await terminate_leftover_runners()

    # When embedded in FastAPI, the app owns this stop event and Uvicorn owns
    # process signal handling.  Standalone `python worker.py` keeps the old
    # behaviour by creating its own event and installing SIGTERM/SIGINT hooks.
    if stop is None:
        stop = asyncio.Event()
    active: set[asyncio.Task] = set()
    try:
        await init_database()
        queue = get_queue()
        await queue.reconcile()
        recovery = await queue.recover_after_supervisor_restart()
        if recovery["recovered"] or recovery["completed_acknowledged"]:
            logger.warning(
                "Recovered queue after app restart: resumed=%s completed=%s",
                recovery["recovered"],
                recovery["completed_acknowledged"],
            )
        loop = asyncio.get_running_loop()
        installed_signals: list[signal.Signals] = []
        if install_signal_handlers:
            for signum in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(signum, stop.set)
                installed_signals.append(signum)

        worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:8]}"
        poll = positive_int("JOB_POLL_SECONDS", 2)
        gpu_pool: asyncio.Queue[str] = asyncio.Queue(maxsize=slots)
        for gpu_id in gpu_ids:
            gpu_pool.put_nowait(gpu_id)

        logger.info(
            "Worker %s started (slots=%s, GPUs=%s)",
            worker_id,
            slots,
            ",".join(gpu_ids),
        )
        if ready is not None:
            ready.set()

        while not stop.is_set():
            try:
                await queue.reconcile()

                done = {task for task in active if task.done()}
                for task in done:
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        task.result()
                active.difference_update(done)

                while len(active) < slots and not stop.is_set():
                    try:
                        gpu_id = gpu_pool.get_nowait()
                    except asyncio.QueueEmpty:
                        break

                    try:
                        job = await queue.claim(worker_id)
                    except Exception:
                        gpu_pool.put_nowait(gpu_id)
                        raise

                    if job is None:
                        gpu_pool.put_nowait(gpu_id)
                        break

                    task = asyncio.create_task(
                        supervise(queue, job, stop, gpu_id, gpu_pool),
                        name=f"lecture-job-{job.id}-gpu-{gpu_id}",
                    )
                    active.add(task)
            except Exception:
                logger.exception("Queue polling failed; retrying")

            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(stop.wait(), poll)
    finally:
        stop.set()
        await asyncio.gather(*active, return_exceptions=True)
        if install_signal_handlers:
            loop = asyncio.get_running_loop()
            for signum in (signal.SIGTERM, signal.SIGINT):
                with contextlib.suppress(NotImplementedError):
                    loop.remove_signal_handler(signum)
        worker_lock.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    asyncio.run(serve())
