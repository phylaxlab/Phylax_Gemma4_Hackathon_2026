"""
Database layer for Phylax.
Uses aiosqlite for async SQLite operations.
Tables: videos, analysis_events, live_sessions.
"""

import logging

import aiosqlite
from config import DB_PATH

# -- SQL Schema --

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS videos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT    NOT NULL,
    filename        TEXT    NOT NULL,
    filepath        TEXT    NOT NULL,
    thumbnail       TEXT,
    duration        REAL    DEFAULT 0,
    upload_time     TEXT    NOT NULL DEFAULT (datetime('now')),
    video_type      TEXT    NOT NULL DEFAULT 'uploaded',   -- 'uploaded' or 'live'
    status          TEXT    NOT NULL DEFAULT 'pending',    -- 'pending', 'analyzing', 'done', 'error'
    analysis_progress REAL  DEFAULT 0                     -- 0.0 to 1.0
);

CREATE TABLE IF NOT EXISTS cameras (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL,
    stream_url      TEXT    NOT NULL,
    is_active       BOOLEAN DEFAULT 1,
    ai_enabled      BOOLEAN DEFAULT 1,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS analysis_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id        INTEGER,
    camera_id       INTEGER,
    timestamp_sec   REAL    NOT NULL,
    frame_path      TEXT,
    description     TEXT    NOT NULL,
    event_type      TEXT    DEFAULT 'none',               -- 'motion', 'person', 'vehicle', 'anomaly', 'none'
    severity        TEXT    DEFAULT 'normal',                 -- 'normal', 'abnormal', 'emergency'
    diff_description TEXT,
    summary         TEXT,
    keywords        TEXT,
    raw_json        TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (video_id) REFERENCES videos(id) ON DELETE CASCADE,
    FOREIGN KEY (camera_id) REFERENCES cameras(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS camera_ai_reviews (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_id       INTEGER NOT NULL,
    timestamp_sec   REAL    NOT NULL,
    frame_path      TEXT,
    description     TEXT    NOT NULL,
    event_type      TEXT    DEFAULT 'none',
    severity        TEXT    DEFAULT 'Normal',
    summary         TEXT,
    keywords        TEXT,
    raw_json        TEXT,
    is_waived       BOOLEAN DEFAULT 1,
    is_error        BOOLEAN DEFAULT 0,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (camera_id) REFERENCES cameras(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS localized_event_texts (
    source_kind     TEXT    NOT NULL,
    source_id       INTEGER NOT NULL,
    language        TEXT    NOT NULL,
    source_hash     TEXT    NOT NULL,
    summary         TEXT,
    description     TEXT,
    frame_observation TEXT,
    temporal_assessment TEXT,
    anomaly_rationale TEXT,
    changes_json    TEXT,
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (source_kind, source_id, language)
);

CREATE TABLE IF NOT EXISTS live_sessions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT    NOT NULL,
    start_time      TEXT    NOT NULL DEFAULT (datetime('now')),
    end_time        TEXT,
    status          TEXT    NOT NULL DEFAULT 'active',     -- 'active', 'stopped'
    recording_path  TEXT,
    video_id        INTEGER,
    FOREIGN KEY (video_id) REFERENCES videos(id) ON DELETE SET NULL
);

-- Index for fast text search on event descriptions
CREATE INDEX IF NOT EXISTS idx_events_description ON analysis_events(description);
CREATE INDEX IF NOT EXISTS idx_events_video_id ON analysis_events(video_id);
CREATE INDEX IF NOT EXISTS idx_events_event_type ON analysis_events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_video_timestamp ON analysis_events(video_id, timestamp_sec);
CREATE INDEX IF NOT EXISTS idx_events_camera_timestamp ON analysis_events(camera_id, timestamp_sec);
CREATE INDEX IF NOT EXISTS idx_camera_ai_reviews_camera_id ON camera_ai_reviews(camera_id);
CREATE INDEX IF NOT EXISTS idx_camera_ai_reviews_timestamp ON camera_ai_reviews(timestamp_sec);
CREATE INDEX IF NOT EXISTS idx_camera_ai_reviews_camera_timestamp ON camera_ai_reviews(camera_id, timestamp_sec);
CREATE INDEX IF NOT EXISTS idx_localized_event_texts_lookup ON localized_event_texts(source_kind, language, source_id);
"""


async def get_db() -> aiosqlite.Connection:
    """
    Create and return an async database connection.
    Enables WAL mode and foreign keys for performance and integrity.
    """
    db = await aiosqlite.connect(str(DB_PATH))
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    await db.execute("PRAGMA synchronous=NORMAL")
    await db.execute("PRAGMA temp_store=MEMORY")
    await db.execute("PRAGMA busy_timeout=5000")
    return db


async def _analysis_events_video_id_is_required(db: aiosqlite.Connection) -> bool:
    cursor = await db.execute("PRAGMA table_info(analysis_events)")
    columns = await cursor.fetchall()
    for column in columns:
        if column["name"] == "video_id":
            return bool(column["notnull"])
    return False


async def _allow_camera_events_without_video_id(db: aiosqlite.Connection) -> None:
    """Rebuild legacy analysis_events tables where video_id was NOT NULL."""
    if not await _analysis_events_video_id_is_required(db):
        return

    logger = logging.getLogger(__name__)
    logger.info("Migrating analysis_events.video_id to allow camera-only events.")
    await db.commit()
    await db.execute("PRAGMA foreign_keys=OFF")
    try:
        await db.execute("BEGIN")
        await db.execute("ALTER TABLE analysis_events RENAME TO analysis_events_legacy")
        await db.execute(
            """
            CREATE TABLE analysis_events (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id        INTEGER,
                camera_id       INTEGER,
                timestamp_sec   REAL    NOT NULL,
                frame_path      TEXT,
                description     TEXT    NOT NULL,
                event_type      TEXT    DEFAULT 'none',
                severity        TEXT    DEFAULT 'normal',
                diff_description TEXT,
                summary         TEXT,
                keywords        TEXT,
                raw_json        TEXT,
                created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (video_id) REFERENCES videos(id) ON DELETE CASCADE,
                FOREIGN KEY (camera_id) REFERENCES cameras(id) ON DELETE CASCADE
            )
            """
        )
        await db.execute(
            """
            INSERT INTO analysis_events
                (id, video_id, camera_id, timestamp_sec, frame_path, description,
                 event_type, severity, diff_description, summary, keywords, raw_json, created_at)
            SELECT
                id, video_id, camera_id, timestamp_sec, frame_path, description,
                event_type, severity, diff_description, summary, keywords, raw_json, created_at
            FROM analysis_events_legacy
            """
        )
        await db.execute("DROP TABLE analysis_events_legacy")
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.execute("PRAGMA foreign_keys=ON")


async def init_db():
    """
    Initialize the database schema.
    Safe to call multiple times (uses IF NOT EXISTS).
    """
    db = await get_db()
    try:
        await db.executescript(SCHEMA_SQL)
        
        # Safely migrate existing databases to include 'keywords' column
        try:
            await db.execute("ALTER TABLE analysis_events ADD COLUMN keywords TEXT")
            logging.getLogger(__name__).info("Migrated: Added 'keywords' column to analysis_events table.")
        except aiosqlite.OperationalError as e:
            # OperationalError is thrown if the column already exists
            if "duplicate column name" not in str(e).lower():
                raise
                
        # Safely migrate existing databases to include 'camera_id'
        try:
            await db.execute("ALTER TABLE analysis_events ADD COLUMN camera_id INTEGER REFERENCES cameras(id)")
            logging.getLogger(__name__).info("Migrated: Added 'camera_id' column to analysis_events table.")
        except aiosqlite.OperationalError as e:
            if "duplicate column name" not in str(e).lower():
                raise
                
        # Safely migrate existing databases to include 'ai_enabled' on cameras
        try:
            await db.execute("ALTER TABLE cameras ADD COLUMN ai_enabled BOOLEAN DEFAULT 1")
            logging.getLogger(__name__).info("Migrated: Added 'ai_enabled' column to cameras table.")
        except aiosqlite.OperationalError as e:
            if "duplicate column name" not in str(e).lower():
                raise

        await _allow_camera_events_without_video_id(db)

        await db.execute("CREATE INDEX IF NOT EXISTS idx_events_camera_id ON analysis_events(camera_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_events_video_timestamp ON analysis_events(video_id, timestamp_sec)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_events_camera_timestamp ON analysis_events(camera_id, timestamp_sec)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_camera_ai_reviews_camera_timestamp ON camera_ai_reviews(camera_id, timestamp_sec)")
        await db.execute(
            """CREATE TABLE IF NOT EXISTS localized_event_texts (
                source_kind     TEXT    NOT NULL,
                source_id       INTEGER NOT NULL,
                language        TEXT    NOT NULL,
                source_hash     TEXT    NOT NULL,
                summary         TEXT,
                description     TEXT,
                frame_observation TEXT,
                temporal_assessment TEXT,
                anomaly_rationale TEXT,
                changes_json    TEXT,
                updated_at      TEXT    NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (source_kind, source_id, language)
            )"""
        )
        await db.execute("CREATE INDEX IF NOT EXISTS idx_localized_event_texts_lookup ON localized_event_texts(source_kind, language, source_id)")

        await db.commit()
    finally:
        await db.close()
