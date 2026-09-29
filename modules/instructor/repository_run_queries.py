from core.database.client import get_connection


async def list_instructor_runs(
    user_id: int,
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    db = await get_connection()
    try:
        cursor = await db.execute(
            """
            SELECT r.*, l.status AS lecture_status, l.progress AS lecture_progress,
                   l.status_message AS lecture_status_message,
                   p.status AS publish_status, p.published_at AS published_at
            FROM ai_instructor_runs r
            LEFT JOIN lectures l ON l.id = r.lecture_id
            LEFT JOIN lecture_publish_schedules p ON p.lecture_id = r.lecture_id
            WHERE r.user_id = ?
            ORDER BY r.scheduled_at DESC
            LIMIT ? OFFSET ?
            """,
            (user_id, limit, max(0, offset)),
        )
        return [dict(row) for row in await cursor.fetchall()]
    finally:
        await db.close()


async def list_recent_agent_lecture_titles(user_id: int, limit: int = 12) -> list[str]:
    db = await get_connection()
    try:
        cursor = await db.execute(
            """
            SELECT title FROM ai_instructor_runs
            WHERE user_id = ? AND title IS NOT NULL
            ORDER BY id DESC LIMIT ?
            """,
            (user_id, limit),
        )
        return [str(row["title"]) for row in await cursor.fetchall()]
    finally:
        await db.close()


async def count_runs_between(user_id: int, start_utc: str, end_utc: str) -> int:
    db = await get_connection()
    try:
        cursor = await db.execute(
            """
            SELECT COUNT(*) AS count
            FROM ai_instructor_runs
            WHERE user_id = ?
              AND scheduled_at >= ?
              AND scheduled_at < ?
              AND status NOT IN ('cancelled', 'failed')
            """,
            (user_id, start_utc, end_utc),
        )
        row = await cursor.fetchone()
        return int(row["count"] if row else 0)
    finally:
        await db.close()

