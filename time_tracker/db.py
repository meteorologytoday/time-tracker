import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import config

_SORT_EXPR: dict[str, str] = {
    "name":          "t.name COLLATE NOCASE",
    "label":         "COALESCE(l.name, '') COLLATE NOCASE",
    "total_seconds": "total_seconds",
    "status":        "t.status",
    "priority": (
        "CASE WHEN t.priority='high' THEN 1 "
        "WHEN t.priority='medium' THEN 2 "
        "WHEN t.priority='low' THEN 3 ELSE 4 END"
    ),
    "deadline": "t.deadline",
    "id":       "t.id",
}

LABEL_COLORS = [
    "#e74c3c",  # red
    "#e67e22",  # orange
    "#f1c40f",  # yellow
    "#2ecc71",  # green
    "#1abc9c",  # teal
    "#3498db",  # blue
    "#9b59b6",  # purple
    "#e91e8c",  # pink
]


def _connect():
    path = config.get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(path)


def init_db():
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS labels (
                id    INTEGER PRIMARY KEY AUTOINCREMENT,
                name  TEXT NOT NULL UNIQUE,
                color TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT    NOT NULL,
                created_at TEXT    NOT NULL,
                label_id   INTEGER REFERENCES labels(id)
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
        # migrations
        cols = {row[1] for row in conn.execute("PRAGMA table_info(tasks)")}
        if "label_id" not in cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN label_id INTEGER REFERENCES labels(id)")
        if "status" not in cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")
        if "notes" not in cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN notes TEXT")
        if "deadline" not in cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN deadline TEXT")
        if "priority" not in cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN priority TEXT")
        if "pinned" not in cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0")


# ── Labels ────────────────────────────────────────────────────────────────────

def create_label(name: str, color: str) -> int:
    with _connect() as conn:
        cursor = conn.execute(
            "INSERT INTO labels (name, color) VALUES (?, ?)", (name, color)
        )
        return cursor.lastrowid


def update_label(label_id: int, name: str, color: str):
    with _connect() as conn:
        conn.execute(
            "UPDATE labels SET name = ?, color = ? WHERE id = ?",
            (name, color, label_id),
        )


def get_labels() -> list[dict]:
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM labels ORDER BY name").fetchall()
        return [dict(r) for r in rows]


def get_tasks_by_label(label_id: int) -> list[dict]:
    """Return id and name for every task assigned to this label."""
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, name FROM tasks WHERE label_id = ? ORDER BY name",
            (label_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def delete_label(label_id: int):
    """Delete the label and cascade-delete all its tasks and their sessions."""
    with _connect() as conn:
        conn.execute("""
            DELETE FROM sessions
            WHERE task_id IN (SELECT id FROM tasks WHERE label_id = ?)
        """, (label_id,))
        conn.execute("DELETE FROM tasks WHERE label_id = ?", (label_id,))
        conn.execute("DELETE FROM labels WHERE id = ?", (label_id,))


def set_task_label(task_id: int, label_id: int | None):
    with _connect() as conn:
        conn.execute(
            "UPDATE tasks SET label_id = ? WHERE id = ?", (label_id, task_id)
        )


# ── Tasks ─────────────────────────────────────────────────────────────────────

def create_task(name: str, label_id: int | None = None) -> int:
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        cursor = conn.execute(
            "INSERT INTO tasks (name, created_at, label_id) VALUES (?, ?, ?)",
            (name, now, label_id),
        )
        return cursor.lastrowid


def get_tasks(
    status: str | None = None,
    label_ids: list[int] | None = None,
    sort_col: str = "id",
    sort_asc: bool = False,
) -> list[dict]:
    """Return tasks with total accumulated duration and label info.

    status:    filter by 'active'/'inactive'/'archived'; None = all.
    label_ids: restrict to tasks whose label_id is in this list; None = all.
    sort_col:  key from _SORT_EXPR; defaults to insertion order (id DESC).
    sort_asc:  True = ascending, False = descending.
    """
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        conditions, params = [], []
        if status is not None:
            conditions.append("t.status = ?")
            params.append(status)
        if label_ids:
            placeholders = ",".join("?" * len(label_ids))
            conditions.append(f"t.label_id IN ({placeholders})")
            params.extend(label_ids)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        direction = "ASC" if sort_asc else "DESC"
        expr = _SORT_EXPR.get(sort_col, "t.id")
        # Always put NULL deadlines last regardless of sort direction
        if sort_col == "deadline":
            order_by = f"(t.deadline IS NULL) ASC, t.deadline {direction}"
        else:
            order_by = f"{expr} {direction}"

        rows = conn.execute(f"""
            SELECT
                t.id,
                t.name,
                t.created_at,
                t.label_id,
                t.status,
                t.priority,
                t.deadline,
                t.notes,
                t.pinned,
                l.name  AS label_name,
                l.color AS label_color,
                COALESCE(SUM(s.duration_seconds), 0) AS total_seconds
            FROM tasks t
            LEFT JOIN labels  l ON l.id      = t.label_id
            LEFT JOIN sessions s ON s.task_id = t.id
            {where}
            GROUP BY t.id
            ORDER BY t.pinned DESC, {order_by}
        """, params).fetchall()
        return [dict(r) for r in rows]


def get_task(task_id: int) -> dict | None:
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("""
            SELECT
                t.id, t.name, t.created_at, t.label_id, t.status,
                t.priority, t.deadline, t.notes, t.pinned,
                l.name  AS label_name,
                l.color AS label_color,
                COALESCE(SUM(s.duration_seconds), 0) AS total_seconds
            FROM tasks t
            LEFT JOIN labels   l ON l.id      = t.label_id
            LEFT JOIN sessions s ON s.task_id = t.id
            WHERE t.id = ?
            GROUP BY t.id
        """, (task_id,)).fetchone()
        return dict(row) if row else None


def update_task(
    task_id: int,
    name: str,
    label_id: int | None,
    status: str,
    notes: str | None = None,
    deadline: str | None = None,
    priority: str | None = None,
):
    with _connect() as conn:
        conn.execute(
            "UPDATE tasks SET name=?, label_id=?, status=?, notes=?, deadline=?, priority=? WHERE id=?",
            (name, label_id, status, notes or None, deadline or None, priority or None, task_id),
        )


def set_task_pinned(task_id: int, pinned: bool):
    with _connect() as conn:
        conn.execute(
            "UPDATE tasks SET pinned = ? WHERE id = ?", (int(pinned), task_id)
        )


def delete_task(task_id: int):
    with _connect() as conn:
        conn.execute("DELETE FROM sessions WHERE task_id = ?", (task_id,))
        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))


# ── Sessions ──────────────────────────────────────────────────────────────────

def start_session(task_id: int) -> int:
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        cursor = conn.execute(
            "INSERT INTO sessions (task_id, start_time) VALUES (?, ?)",
            (task_id, now),
        )
        return cursor.lastrowid


def get_task_sessions(task_id: int) -> list[dict]:
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT id, start_time, end_time, duration_seconds
            FROM sessions
            WHERE task_id = ?
            ORDER BY start_time ASC
        """, (task_id,)).fetchall()
        return [dict(r) for r in rows]


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
