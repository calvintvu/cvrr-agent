import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Literal

from beartype import beartype

from reels_ripper_agent.config import DATA_DIR
from reels_ripper_agent.db.schema import SCHEMA
from reels_ripper_agent.llm.base import Message

DB_PATH = DATA_DIR / "reels.db"


def _connect() -> closing[sqlite3.Connection]:
    """Open the database and create the tables if they do not exist."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
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
def pending_renders(cuts: list[str]) -> list[tuple[int, str, str, Path, list[str]]]:
    """(reel_id, url, author, download_path, missing_cuts) for each downloaded
    reel that has no render for one or more of cuts, in id order. missing_cuts
    keeps the order of cuts."""
    with _connect() as conn:
        done = set(conn.execute("SELECT reel_id, cut FROM renders"))
        rows = conn.execute(
            "SELECT id, url, author, download_path FROM reels"
            " WHERE download_path IS NOT NULL ORDER BY id"
        ).fetchall()
    pending = []
    for reel_id, url, author, path in rows:
        missing = [cut for cut in cuts if (reel_id, cut) not in done]
        if missing:
            pending.append((reel_id, url, author, Path(path), missing))
    return pending


@beartype
def add_render(reel_id: int, cut: str, path: Path) -> None:
    """Record that the reel with reel_id was rendered with cut to path."""
    with _connect() as conn, conn:
        conn.execute(
            "INSERT INTO renders (reel_id, cut, path) VALUES (?, ?, ?)",
            (reel_id, cut, str(path)),
        )


@beartype
def next_unposted() -> tuple[int, Path] | None:
    """(render_id, path) of the oldest render that is not posted, or None."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, path FROM renders WHERE posted_at IS NULL ORDER BY id LIMIT 1"
        ).fetchone()
    return None if row is None else (row[0], Path(row[1]))


@beartype
def set_posted(render_id: int) -> None:
    """Mark the render with render_id as posted now."""
    with _connect() as conn, conn:
        conn.execute(
            "UPDATE renders SET posted_at = CURRENT_TIMESTAMP WHERE id = ?",
            (render_id,),
        )


@beartype
def delete_reel(url: str) -> None:
    """Remove the reel at url and its renders."""
    with _connect() as conn, conn:
        conn.execute("DELETE FROM reels WHERE url = ?", (url,))


@beartype
def create_run(messages: list[Message]) -> int:
    """Insert a new run with status 'running' and its first messages, in one
    transaction. Returns its id."""
    with _connect() as conn, conn:
        run_id = conn.execute("INSERT INTO runs DEFAULT VALUES").lastrowid
        assert run_id is not None
        conn.executemany(
            "INSERT INTO messages (run_id, seq, body) VALUES (?, ?, ?)",
            [(run_id, seq, m.model_dump_json()) for seq, m in enumerate(messages)],
        )
        return run_id


@beartype
def append_message(run_id: int, seq: int, message: Message) -> None:
    """Store message as entry seq of the run."""
    with _connect() as conn, conn:
        conn.execute(
            "INSERT INTO messages (run_id, seq, body) VALUES (?, ?, ?)",
            (run_id, seq, message.model_dump_json()),
        )


@beartype
def load_messages(run_id: int) -> list[Message]:
    """The stored messages of the run, in seq order."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT body FROM messages WHERE run_id = ? ORDER BY seq", (run_id,)
        )
        return [Message.model_validate_json(body) for (body,) in rows]


@beartype
def finish_run(
    run_id: int, status: Literal["done", "failed"], result: str | None
) -> None:
    """Set the final status and result of the run."""
    with _connect() as conn, conn:
        conn.execute(
            "UPDATE runs SET status = ?, result = ? WHERE id = ?",
            (status, result, run_id),
        )


@beartype
def unfinished_run() -> int | None:
    """Id of the newest run with status 'running', or None."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT id FROM runs WHERE status = 'running' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return None if row is None else row[0]
