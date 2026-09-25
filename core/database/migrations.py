from core.database.client import get_connection


async def _add_column_if_missing(
    db,
    table: str,
    column: str,
    definition: str,
):
    cursor = await db.execute(
        f"PRAGMA table_info({table})"
    )
    rows = await cursor.fetchall()
    names = {
        row["name"]
        for row in rows
    }

    if column not in names:
        await db.execute(
            f"ALTER TABLE {table} "
            f"ADD COLUMN {column} {definition}"
        )


async def init_database() -> None:
    db = await get_connection()

    try:
        await db.executescript(
            """
            BEGIN IMMEDIATE;
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                email_verified INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_login_at TEXT
            );

            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id INTEGER PRIMARY KEY,
                name TEXT,
                nickname TEXT,
                phone TEXT,
                avatar_path TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (user_id)
                    REFERENCES users(id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS organizations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                slug TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS organization_members (
                organization_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL DEFAULT 'member',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                PRIMARY KEY (
                    organization_id,
                    user_id
                ),

                FOREIGN KEY (organization_id)
                    REFERENCES organizations(id)
                    ON DELETE CASCADE,

                FOREIGN KEY (user_id)
                    REFERENCES users(id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS credentials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                user_id INTEGER,
                organization_id INTEGER,

                provider TEXT NOT NULL,
                credential_type TEXT NOT NULL,
                name TEXT NOT NULL DEFAULT 'default',

                encrypted_secret BLOB NOT NULL,
                metadata_json TEXT,

                key_version INTEGER NOT NULL DEFAULT 1,

                expires_at TEXT,
                revoked_at TEXT,

                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (user_id)
                    REFERENCES users(id)
                    ON DELETE CASCADE,

                FOREIGN KEY (organization_id)
                    REFERENCES organizations(id)
                    ON DELETE CASCADE,

                CHECK (
                    (user_id IS NOT NULL AND organization_id IS NULL)
                    OR
                    (user_id IS NULL AND organization_id IS NOT NULL)
                )
            );

            CREATE UNIQUE INDEX IF NOT EXISTS
                idx_credentials_user_unique
            ON credentials (
                user_id,
                provider,
                credential_type,
                name
            )
            WHERE user_id IS NOT NULL;

            CREATE UNIQUE INDEX IF NOT EXISTS
                idx_credentials_org_unique
            ON credentials (
                organization_id,
                provider,
                credential_type,
                name
            )
            WHERE organization_id IS NOT NULL;

            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER PRIMARY KEY,

                language TEXT NOT NULL DEFAULT 'ko',

                default_openai_model TEXT,
                default_image_model TEXT,
                default_realtime_model TEXT,
                default_course_id INTEGER,

                settings_json TEXT,

                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (user_id)
                    REFERENCES users(id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS lectures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,

                title TEXT NOT NULL,
                topic TEXT NOT NULL,

                status TEXT NOT NULL DEFAULT 'queued',
                progress INTEGER NOT NULL DEFAULT 0,
                status_message TEXT,
                error_message TEXT,

                text_model TEXT NOT NULL,
                image_model TEXT,
                tts_model TEXT NOT NULL,
                tts_voice TEXT NOT NULL DEFAULT 'alloy',
                generate_images INTEGER NOT NULL DEFAULT 1,

                target_duration_minutes INTEGER NOT NULL DEFAULT 40,
                target_slide_count INTEGER NOT NULL DEFAULT 10,

                moodle_course_id INTEGER,
                moodle_section_num INTEGER,
                moodle_deploy_mode TEXT NOT NULL DEFAULT 'create',
                moodle_videotracker_cmid INTEGER,
                upload_to_moodle INTEGER NOT NULL DEFAULT 0,

                portrait_path TEXT,

                plan_json TEXT,
                quiz_json TEXT,

                pptx_path TEXT,
                narration_path TEXT,
                slides_video_path TEXT,
                avatar_path TEXT,
                final_video_path TEXT,

                moodle_result_json TEXT,

                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (user_id)
                    REFERENCES users(id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS
                idx_lectures_user_created
            ON lectures(
                user_id,
                created_at DESC
            );
            """
        )

        # Upgrade an already-created local SQLite DB in-place.
        await _add_column_if_missing(
            db,
            "user_settings",
            "default_course_id",
            "INTEGER",
        )

        await _add_column_if_missing(
            db,
            "lectures",
            "moodle_section_num",
            "INTEGER",
        )

        await _add_column_if_missing(
            db,
            "lectures",
            "target_duration_minutes",
            "INTEGER NOT NULL DEFAULT 40",
        )

        await _add_column_if_missing(
            db,
            "lectures",
            "target_slide_count",
            "INTEGER NOT NULL DEFAULT 10",
        )

        await _add_column_if_missing(
            db,
            "lectures",
            "moodle_deploy_mode",
            "TEXT NOT NULL DEFAULT 'create'",
        )

        await _add_column_if_missing(db, "lectures", "run_token", "TEXT")
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS lecture_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lecture_id INTEGER NOT NULL UNIQUE REFERENCES lectures(id) ON DELETE CASCADE,
                status TEXT NOT NULL DEFAULT 'queued',
                attempts INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL,
                available_at REAL NOT NULL,
                lease_until REAL,
                lease_token TEXT,
                worker_id TEXT,
                gpu_id TEXT,
                last_error TEXT,
                updated_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_jobs_ready
                ON lecture_jobs(status, available_at);
            CREATE TABLE IF NOT EXISTS lecture_stages (
                lecture_id INTEGER NOT NULL REFERENCES lectures(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                status TEXT NOT NULL,
                outputs_json TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(lecture_id, name)
            );
            CREATE TABLE IF NOT EXISTS lecture_publish_schedules (
                lecture_id INTEGER PRIMARY KEY REFERENCES lectures(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                mode TEXT NOT NULL DEFAULT 'exact',
                weekday INTEGER,
                hour INTEGER,
                minute INTEGER NOT NULL DEFAULT 0,
                timezone TEXT NOT NULL DEFAULT 'Asia/Seoul',
                scheduled_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                published_at TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_lecture_publish_due
                ON lecture_publish_schedules(status, scheduled_at);
        """)

        await _add_column_if_missing(
            db,
            "lecture_jobs",
            "gpu_id",
            "TEXT",
        )
        await _add_column_if_missing(
            db,
            "lecture_publish_schedules",
            "lease_token",
            "TEXT",
        )
        await _add_column_if_missing(
            db,
            "lecture_publish_schedules",
            "lease_until",
            "TEXT",
        )
        await _add_column_if_missing(
            db,
            "lecture_publish_schedules",
            "create_state",
            "TEXT NOT NULL DEFAULT 'idle'",
        )
        await _add_column_if_missing(
            db,
            "lecture_publish_schedules",
            "create_result_json",
            "TEXT",
        )

        await db.commit()

    finally:
        await db.close()
