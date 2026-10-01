from core.database.client import get_connection
from core.database.schema_base import ensure_base_schema
from core.database.schema_runtime import ensure_runtime_schema


async def init_database() -> None:
    db = await get_connection()
    try:
        await ensure_base_schema(db)
        await ensure_runtime_schema(db)
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()
