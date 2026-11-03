SCHEMA = """
CREATE TABLE IF NOT EXISTS reels (
    id            INTEGER PRIMARY KEY,
    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    url           TEXT NOT NULL UNIQUE,
    author        TEXT NOT NULL,
    download_path TEXT
);

-- One row per video that process_reels made: one reel with one audio cut.
-- cut is the path of the cut relative to assets/. posted_at is NULL until
-- the video is posted.
CREATE TABLE IF NOT EXISTS renders (
    id         INTEGER PRIMARY KEY,
    reel_id    INTEGER NOT NULL REFERENCES reels(id) ON DELETE CASCADE,
    cut        TEXT NOT NULL,
    path       TEXT NOT NULL,
    posted_at  TEXT,
    UNIQUE (reel_id, cut)
);

-- One row per agent run. A run stays 'running' until it ends, so after a
-- crash the newest 'running' row is the run to resume.
CREATE TABLE IF NOT EXISTS runs (
    id         INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status     TEXT NOT NULL DEFAULT 'running'
               CHECK (status IN ('running', 'done', 'failed')),
    result     TEXT
);

-- The message list of a run, one row per message in loop order.
-- body is Message.model_dump_json().
CREATE TABLE IF NOT EXISTS messages (
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    seq    INTEGER NOT NULL,
    body   TEXT NOT NULL,
    PRIMARY KEY (run_id, seq)
);
"""
