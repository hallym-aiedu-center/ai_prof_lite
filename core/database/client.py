import os
from pathlib import Path

import aiosqlite

from core.config import project_path


def get_database_path() -> Path:
    path = project_path(
        os.getenv(
            "DATABASE_PATH",
            "./data/ai_prof_lite.db",
        )
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


async def get_connection() -> aiosqlite.Connection:
    db = await aiosqlite.connect(get_database_path())
    db.row_factory = aiosqlite.Row

    await db.execute("PRAGMA foreign_keys = ON")
    await db.execute("PRAGMA journal_mode = WAL")
    await db.execute("PRAGMA busy_timeout = 5000")

    return db
