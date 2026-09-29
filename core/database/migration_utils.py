from __future__ import annotations


async def _add_column_if_missing(
    db,
    table: str,
    column: str,
    definition: str,
):
    cursor = await db.execute(f"PRAGMA table_info({table})")
    rows = await cursor.fetchall()
    names = {row["name"] for row in rows}

    if column not in names:
        await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
