import sqlite3
from contextlib import closing
from pathlib import Path

from beartype import beartype

from reels_ripper_agent.config import DATA_DIR
from reels_ripper_agent.db.schema import SCHEMA

DB_PATH = DATA_DIR / "reels.db"


def _connect() -> closing[sqlite3.Connection]:
    """Open the database and create the reels table if it does not exist."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
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


@beartype
def pending_processing() -> list[tuple[str, str, Path]]:
    """(url, author, download_path) for reels that are downloaded and not
    processed, in id order."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT url, author, download_path FROM reels"
            " WHERE download_path IS NOT NULL AND NOT is_processed ORDER BY id"
        )
        return [(url, author, Path(path)) for (url, author, path) in rows]


@beartype
def set_processed(url: str) -> None:
    """Mark the reel at url as processed."""
    with _connect() as conn, conn:
        conn.execute("UPDATE reels SET is_processed = 1 WHERE url = ?", (url,))


@beartype
def delete_reel(url: str) -> None:
    """Remove the reel at url from the table."""
    with _connect() as conn, conn:
        conn.execute("DELETE FROM reels WHERE url = ?", (url,))
