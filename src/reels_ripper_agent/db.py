import sqlite3
from contextlib import closing
from pathlib import Path

from beartype import beartype

DB_PATH = Path("reels.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS reels (
    id         INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    url        TEXT NOT NULL UNIQUE,
    author     TEXT NOT NULL
)
"""


@beartype
def save_reels(reels: list[tuple[str, str]]) -> int:
    """Insert (url, author) pairs into the reels table. Creates the table if it
    does not exist. Skips urls that are already stored (INSERT OR IGNORE).

    Returns the number of new rows.
    """
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        conn.execute(SCHEMA)
        before = conn.total_changes
        conn.executemany(
            "INSERT OR IGNORE INTO reels (url, author) VALUES (?, ?)", reels
        )
        return conn.total_changes - before
