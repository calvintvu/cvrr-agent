SCHEMA = """
CREATE TABLE IF NOT EXISTS reels (
    id            INTEGER PRIMARY KEY,
    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    url           TEXT NOT NULL UNIQUE,
    author        TEXT NOT NULL,
    download_path TEXT,
    is_processed  INTEGER NOT NULL DEFAULT 0
)
"""
