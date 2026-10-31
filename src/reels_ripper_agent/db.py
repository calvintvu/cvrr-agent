import sqlite3
from contextlib import closing
from pathlib import Path

from beartype import beartype

DB_PATH = Path("reels.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS reels (
    id            INTEGER PRIMARY KEY,
    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    url           TEXT NOT NULL UNIQUE,
    author        TEXT NOT NULL,
    download_path TEXT
)
"""


def _connect() -> closing[sqlite3.Connection]:
    """Open the database and create the reels table if it does not exist."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(SCHEMA)
    return closing(conn)


@beartype
def save_reels(reels: list[tuple[str, str]]) -> int:
    """Insert (url, author) pairs into the reels table. Skips urls that are
    already stored (INSERT OR IGNORE).

    Returns the number of new rows.
    """
    with _connect() as conn, conn:
        before = conn.total_changes
        conn.executemany(
            "INSERT OR IGNORE INTO reels (url, author) VALUES (?, ?)", reels
        )
        return conn.total_changes - before


@beartype
def pending_downloads() -> list[str]:
    """Urls whose download_path is null, in id order."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT url FROM reels WHERE download_path IS NULL ORDER BY id"
        )
        return [url for (url,) in rows]


@beartype
def set_download_path(url: str, path: Path) -> None:
    """Record where the reel at url was saved."""
    with _connect() as conn, conn:
        conn.execute(
            "UPDATE reels SET download_path = ? WHERE url = ?", (str(path), url)
        )
