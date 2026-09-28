from core.database.client import get_connection


async def _ensure_column(db, table: str, column: str, ddl: str) -> None:
    cursor = await db.execute(f"PRAGMA table_info({table})")
    columns = {str(row["name"]) for row in await cursor.fetchall()}
    if column not in columns:
        await db.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


async def ensure_instructor_schema() -> None:
    db = await get_connection()
    try:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_instructor_profiles (
                user_id INTEGER PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 0,
                timezone TEXT NOT NULL DEFAULT 'Asia/Seoul',
                weekdays_json TEXT NOT NULL DEFAULT '[0,2,4]',
                publish_hour INTEGER NOT NULL DEFAULT 18,
                publish_minute INTEGER NOT NULL DEFAULT 0,
                lead_hours INTEGER NOT NULL DEFAULT 24,
                weekly_limit INTEGER NOT NULL DEFAULT 3,
                semester_start_date TEXT NOT NULL DEFAULT '',
                semester_weeks INTEGER NOT NULL DEFAULT 15,
                course_scope TEXT NOT NULL DEFAULT 'all',
                selected_course_ids_json TEXT NOT NULL DEFAULT '[]',
                instructions TEXT,
                avatar_path TEXT,
                text_model TEXT NOT NULL DEFAULT 'gpt-5.1',
                image_model TEXT NOT NULL DEFAULT 'gpt-image-2',
                tts_model TEXT NOT NULL DEFAULT 'gpt-4o-mini-tts',
                tts_voice TEXT NOT NULL DEFAULT 'alloy',
                generate_images INTEGER NOT NULL DEFAULT 1,
                target_duration_minutes INTEGER NOT NULL DEFAULT 40,
                target_slide_count INTEGER NOT NULL DEFAULT 10,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await _ensure_column(
            db,
            "ai_instructor_profiles",
            "semester_start_date",
            "semester_start_date TEXT NOT NULL DEFAULT ''",
        )
        await _ensure_column(
            db,
            "ai_instructor_profiles",
            "semester_weeks",
            "semester_weeks INTEGER NOT NULL DEFAULT 15",
        )
        await _ensure_column(
            db,
            "ai_instructor_profiles",
            "target_duration_minutes",
            "target_duration_minutes INTEGER NOT NULL DEFAULT 40",
        )
        await _ensure_column(
            db,
            "ai_instructor_profiles",
            "target_slide_count",
            "target_slide_count INTEGER NOT NULL DEFAULT 10",
        )

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_instructor_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                scheduled_at TEXT NOT NULL,
                timezone TEXT NOT NULL DEFAULT 'Asia/Seoul',
                week_number INTEGER,
                status TEXT NOT NULL DEFAULT 'planned',
                lecture_id INTEGER,
                course_id INTEGER,
                course_name TEXT,
                section_num INTEGER,
                section_name TEXT,
                title TEXT,
                topic TEXT,
                rationale TEXT,
                last_error TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, scheduled_at)
            )
            """
        )
        await _ensure_column(
            db,
            "ai_instructor_runs",
            "week_number",
            "week_number INTEGER",
        )
        await _ensure_column(
            db,
            "ai_instructor_runs",
            "planning_token",
            "planning_token TEXT",
        )
        await _ensure_column(
            db,
            "ai_instructor_runs",
            "planning_lease_until",
            "planning_lease_until TEXT",
        )
        await _ensure_column(
            db,
            "ai_instructor_runs",
            "planning_attempts",
            "planning_attempts INTEGER NOT NULL DEFAULT 0",
        )
        await db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_ai_instructor_runs_due
            ON ai_instructor_runs(status, scheduled_at)
            """
        )
        await db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_ai_instructor_runs_user
            ON ai_instructor_runs(user_id, scheduled_at)
            """
        )
        await db.commit()
    finally:
        await db.close()
