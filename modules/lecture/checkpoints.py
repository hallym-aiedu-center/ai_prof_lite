import json

from core.database.client import get_connection
from core.jobs.base import LeaseLost


async def get_stage(lecture_id: int, name: str):
    db = await get_connection()
    try:
        row = await (
            await db.execute(
                "SELECT status, outputs_json FROM lecture_stages WHERE lecture_id=? AND name=?",
                (lecture_id, name),
            )
        ).fetchone()
        if row is None:
            return None
        return {
            "status": row["status"],
            "outputs": json.loads(row["outputs_json"] or "{}"),
        }
    finally:
        await db.close()


async def save_stage(
    lecture_id: int, name: str, status: str, outputs: dict, *, run_token: str
):
    db = await get_connection()
    try:
        cursor = await db.execute(
            """
            INSERT INTO lecture_stages(lecture_id, name, status, outputs_json)
            SELECT id, ?, ?, ? FROM lectures WHERE id=? AND run_token=?
            ON CONFLICT(lecture_id, name) DO UPDATE SET status=excluded.status,
                outputs_json=excluded.outputs_json, updated_at=CURRENT_TIMESTAMP
        """,
            (
                name,
                status,
                json.dumps(outputs, ensure_ascii=False),
                lecture_id,
                run_token,
            ),
        )
        if cursor.rowcount != 1:
            raise LeaseLost("This worker no longer owns the lecture checkpoint.")
        await db.commit()
    finally:
        await db.close()
