from core.database.client import get_connection


async def _ensure_column(db, table: str, column: str, ddl: str) -> None:
    cursor = await db.execute(f"PRAGMA table_info({table})")
    columns = {str(row["name"]) for row in await cursor.fetchall()}
    if column not in columns:
        await db.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


async def _foreign_key_targets(db, table: str) -> set[tuple[str, str, str]]:
    cursor = await db.execute(f"PRAGMA foreign_key_list({table})")
    return {
        (str(row["from"]), str(row["table"]), str(row["to"]))
        for row in await cursor.fetchall()
    }


async def _ensure_instructor_foreign_keys(db) -> None:
    """Upgrade legacy instructor tables that predated user/lecture FKs.

    SQLite cannot add a foreign-key constraint with ALTER TABLE, so legacy Lite
    databases are rebuilt in place. Orphaned profile/run rows are intentionally
    discarded; a missing user cannot own background work, and a missing lecture
    is normalized to NULL on the run row.
    """
    profile_fks = await _foreign_key_targets(db, "ai_instructor_profiles")
    if ("user_id", "users", "id") not in profile_fks:
        await db.execute("DROP TABLE IF EXISTS ai_instructor_profiles_new")
        await db.execute(
            """
            CREATE TABLE ai_instructor_profiles_new (
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
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        await db.execute(
            """
            INSERT INTO ai_instructor_profiles_new (
                user_id, enabled, timezone, weekdays_json, publish_hour,
                publish_minute, lead_hours, weekly_limit, semester_start_date,
                semester_weeks, course_scope, selected_course_ids_json,
                instructions, avatar_path, text_model, image_model, tts_model,
                tts_voice, generate_images, target_duration_minutes,
                target_slide_count, created_at, updated_at
            )
            SELECT p.user_id, p.enabled, p.timezone, p.weekdays_json,
                   p.publish_hour, p.publish_minute, p.lead_hours, p.weekly_limit,
                   p.semester_start_date, p.semester_weeks, p.course_scope,
                   p.selected_course_ids_json, p.instructions, p.avatar_path,
                   p.text_model, p.image_model, p.tts_model, p.tts_voice,
                   p.generate_images, p.target_duration_minutes,
                   p.target_slide_count, p.created_at, p.updated_at
            FROM ai_instructor_profiles AS p
            JOIN users AS u ON u.id = p.user_id
            """
        )
        await db.execute("DROP TABLE ai_instructor_profiles")
        await db.execute(
            "ALTER TABLE ai_instructor_profiles_new RENAME TO ai_instructor_profiles"
        )

    run_fks = await _foreign_key_targets(db, "ai_instructor_runs")
    required_run_fks = {
        ("user_id", "users", "id"),
        ("lecture_id", "lectures", "id"),
    }
    if not required_run_fks.issubset(run_fks):
        await db.execute("DROP TABLE IF EXISTS ai_instructor_runs_new")
        await db.execute(
            """
            CREATE TABLE ai_instructor_runs_new (
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
                planning_token TEXT,
                planning_lease_until TEXT,
                planning_attempts INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, scheduled_at),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (lecture_id) REFERENCES lectures(id) ON DELETE SET NULL
            )
            """
        )
        await db.execute(
            """
            INSERT INTO ai_instructor_runs_new (
                id, user_id, scheduled_at, timezone, week_number, status,
                lecture_id, course_id, course_name, section_num, section_name,
                title, topic, rationale, last_error, planning_token,
                planning_lease_until, planning_attempts, created_at, updated_at
            )
            SELECT r.id, r.user_id, r.scheduled_at, r.timezone, r.week_number,
                   r.status,
                   CASE
                       WHEN r.lecture_id IS NULL THEN NULL
                       WHEN EXISTS (SELECT 1 FROM lectures l WHERE l.id = r.lecture_id)
                           THEN r.lecture_id
                       ELSE NULL
                   END,
                   r.course_id, r.course_name, r.section_num, r.section_name,
                   r.title, r.topic, r.rationale, r.last_error, r.planning_token,
                   r.planning_lease_until, r.planning_attempts,
                   r.created_at, r.updated_at
            FROM ai_instructor_runs AS r
            JOIN users AS u ON u.id = r.user_id
            """
        )
        await db.execute("DROP TABLE ai_instructor_runs")
        await db.execute(
            "ALTER TABLE ai_instructor_runs_new RENAME TO ai_instructor_runs"
        )


async def ensure_instructor_schema() -> None:
    db = await get_connection()
    try:
        await db.execute("BEGIN IMMEDIATE")
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
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
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
                planning_token TEXT,
                planning_lease_until TEXT,
                planning_attempts INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, scheduled_at),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (lecture_id) REFERENCES lectures(id) ON DELETE SET NULL
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

        await _ensure_instructor_foreign_keys(db)

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
    except BaseException:
        await db.rollback()
        raise
    finally:
        await db.close()
