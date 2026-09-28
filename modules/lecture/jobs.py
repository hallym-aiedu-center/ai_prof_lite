"""Compatibility helpers for the durable lecture queue.

Older code imported enqueue_lecture_job from this module.  The previous
in-process asyncio workers are intentionally gone: every producer now writes to
the same durable queue consumed by worker.py, so web-created and instructor-
created lectures share the same GPU scheduler.
"""
from core.jobs.factory import get_queue


async def enqueue_lecture_job(lecture_id: int) -> None:
    await get_queue().enqueue(lecture_id)


async def start_lecture_workers() -> None:
    """Deprecated no-op. Run exactly one ``python worker.py`` supervisor."""
    return


async def stop_lecture_workers() -> None:
    """Deprecated no-op kept for import compatibility."""
    return
