from __future__ import annotations

import asyncio
import shutil

from core.config import data_dir


async def remove_planning_lecture_storage(lecture_id: int | None) -> None:
    """Best-effort removal for an instructor lecture deleted before queue exposure."""
    if lecture_id is None:
        return
    path = data_dir() / "lectures" / str(int(lecture_id))
    await asyncio.to_thread(shutil.rmtree, path, True)
