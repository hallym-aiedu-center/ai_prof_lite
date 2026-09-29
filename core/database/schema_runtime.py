from core.database.migration_utils import _add_column_if_missing


async def ensure_runtime_schema(db) -> None:
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS openai_usage_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            lecture_id INTEGER REFERENCES lectures(id) ON DELETE SET NULL,
            kind TEXT NOT NULL,
            endpoint TEXT,
            operation TEXT,
            stage TEXT,
            item_key TEXT,
            item_index INTEGER,
            model TEXT NOT NULL,
            request_id TEXT,
            status TEXT NOT NULL DEFAULT 'reserved',
            reserved_cost_usd REAL NOT NULL DEFAULT 0,
            cost_usd REAL NOT NULL DEFAULT 0,
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            cached_input_tokens INTEGER NOT NULL DEFAULT 0,
            metadata_json TEXT,
            usage_json TEXT,
            pricing_json TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_openai_usage_user_created
            ON openai_usage_events(user_id, created_at);
    """)

    await _add_column_if_missing(db, "openai_usage_events", "endpoint", "TEXT")
    await _add_column_if_missing(db, "openai_usage_events", "operation", "TEXT")
    await _add_column_if_missing(db, "openai_usage_events", "stage", "TEXT")
    await _add_column_if_missing(db, "openai_usage_events", "item_key", "TEXT")
    await _add_column_if_missing(db, "openai_usage_events", "item_index", "INTEGER")
    await _add_column_if_missing(db, "openai_usage_events", "request_id", "TEXT")
    await _add_column_if_missing(db, "openai_usage_events", "usage_json", "TEXT")
    await _add_column_if_missing(db, "openai_usage_events", "pricing_json", "TEXT")

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
