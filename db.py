import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent / "time_tracker.db"


def _connect():
    return sqlite3.connect(DB_PATH)


def init_db():
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT    NOT NULL,
                created_at TEXT    NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id          INTEGER NOT NULL REFERENCES tasks(id),
                start_time       TEXT    NOT NULL,
                end_time         TEXT,
                duration_seconds INTEGER
            )
        """)


def create_task(name: str) -> int:
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        cursor = conn.execute(
            "INSERT INTO tasks (name, created_at) VALUES (?, ?)", (name, now)
        )
        return cursor.lastrowid


def start_session(task_id: int) -> int:
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        cursor = conn.execute(
            "INSERT INTO sessions (task_id, start_time) VALUES (?, ?)",
            (task_id, now),
        )
        return cursor.lastrowid


def stop_session(session_id: int):
    now = datetime.now(timezone.utc)
    with _connect() as conn:
        row = conn.execute(
            "SELECT start_time FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if row is None:
            return
        start = datetime.fromisoformat(row[0])
        duration = int((now - start).total_seconds())
        conn.execute(
            "UPDATE sessions SET end_time = ?, duration_seconds = ? WHERE id = ?",
            (now.isoformat(), duration, session_id),
        )


def get_tasks() -> list[dict]:
    """Return all tasks with total accumulated duration (seconds)."""
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT
                t.id,
                t.name,
                t.created_at,
                COALESCE(SUM(s.duration_seconds), 0) AS total_seconds
            FROM tasks t
            LEFT JOIN sessions s ON s.task_id = t.id
            GROUP BY t.id
            ORDER BY t.id DESC
        """).fetchall()
        return [dict(r) for r in rows]
