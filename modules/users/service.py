from core.database.client import get_connection


async def get_user_status(user_id: int) -> str | None:
    db = await get_connection()
    try:
        row = await (await db.execute(
            "SELECT status FROM users WHERE id = ? LIMIT 1",
            (user_id,),
        )).fetchone()
        return str(row["status"]) if row else None
    finally:
        await db.close()


async def get_user(user_id: int):
    db = await get_connection()

    try:
        cursor = await db.execute(
            """
            SELECT
                u.id,
                u.email,
                u.status,
                u.email_verified,
                u.created_at,
                u.last_login_at,
                p.name,
                p.nickname,
                p.phone,
                p.avatar_path,
                s.language,
                s.default_openai_model,
                s.default_image_model,
                s.default_realtime_model,
                s.default_course_id,
                s.openai_budget_usd
            FROM users AS u
            LEFT JOIN user_profiles AS p
                ON p.user_id = u.id
            LEFT JOIN user_settings AS s
                ON s.user_id = u.id
            WHERE u.id = ?
            LIMIT 1
            """,
            (user_id,),
        )

        row = await cursor.fetchone()

        return dict(row) if row else None

    finally:
        await db.close()


async def update_profile(
    *,
    user_id: int,
    name: str | None,
    nickname: str | None,
    phone: str | None,
    language: str = "ko",
    openai_budget_usd: float | None = None,
):
    db = await get_connection()

    try:
        await db.execute(
            """
            UPDATE user_profiles
            SET name = ?,
                nickname = ?,
                phone = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ?
            """,
            (
                (name or "").strip() or None,
                (nickname or "").strip() or None,
                (phone or "").strip() or None,
                user_id,
            ),
        )

        await db.execute(
            """
            UPDATE user_settings
            SET language = ?,
                openai_budget_usd = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ?
            """,
            (
                language,
                openai_budget_usd,
                user_id,
            ),
        )

        await db.commit()

    finally:
        await db.close()
