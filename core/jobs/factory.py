import os

from core.jobs.base import JobQueue


def get_queue() -> JobQueue:
    backend = os.getenv("JOB_QUEUE_BACKEND", "sqlite").lower()
    if backend == "sqlite":
        from core.jobs.sqlite import SQLiteJobQueue
        return SQLiteJobQueue()
    raise RuntimeError(f"Unsupported JOB_QUEUE_BACKEND: {backend}. Redis adapter is not installed.")
