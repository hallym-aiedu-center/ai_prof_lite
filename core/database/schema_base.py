from core.database.migration_utils import _add_column_if_missing


async def _create_base_tables(db) -> None:
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

            language TEXT NOT NULL DEFAULT 'auto',

            default_openai_model TEXT,
            default_image_model TEXT,
            default_realtime_model TEXT,
            default_course_id INTEGER,
            openai_budget_usd REAL,

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

            review_before_video INTEGER NOT NULL DEFAULT 0,
            review_status TEXT NOT NULL DEFAULT 'not_required',
            source_files_json TEXT,
            reference_mode TEXT NOT NULL DEFAULT 'rag',

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


async def _upgrade_base_schema(db) -> None:
    # Upgrade an already-created local SQLite DB in-place.
    await _add_column_if_missing(
        db,
        "user_settings",
        "default_course_id",
        "INTEGER",
    )
    await _add_column_if_missing(
        db,
        "user_settings",
        "openai_budget_usd",
        "REAL",
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
    await _add_column_if_missing(
        db,
        "lectures",
        "review_before_video",
        "INTEGER NOT NULL DEFAULT 0",
    )
    await _add_column_if_missing(
        db,
        "lectures",
        "review_status",
        "TEXT NOT NULL DEFAULT 'not_required'",
    )
    await _add_column_if_missing(db, "lectures", "source_files_json", "TEXT")
    await _add_column_if_missing(
        db,
        "lectures",
        "reference_mode",
        "TEXT NOT NULL DEFAULT 'rag'",
    )

    await _add_column_if_missing(db, "lectures", "run_token", "TEXT")


async def ensure_base_schema(db) -> None:
    # Keep the existing transaction boundary: the CREATE script begins the
    # transaction and the database bootstrapper commits after all schema groups.
    await _create_base_tables(db)
    await _upgrade_base_schema(db)
