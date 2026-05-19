# Time Tracker — Developer Guide

A desktop GUI app for tracking time spent on personal tasks. Built in Python with customtkinter (a themed wrapper around tkinter) and SQLite. The goal is simple: start a timer on a task, stop it, accumulate a history, and eventually analyse where time goes.

---

## Quick Start

```bash
# Install in editable mode (recommended for development)
pip install -e .

# Run
time-tracker
```

Requires Python 3.10+ (uses `X | Y` union type hints). The only non-stdlib dependency is `customtkinter>=5.2.0`.

---

## Repository Layout

```
time-tracker/
├── pyproject.toml          # packaging (setuptools), entry point
├── CLAUDE.md               # instructions for AI collaborators
├── DEVELOPER.md            # this file
└── time_tracker/
    ├── __init__.py         # empty; marks as package
    ├── config.py           # read/write ~/.time_tracker/config.json
    ├── db.py               # all SQLite access — no SQL outside this file
    └── app.py              # entire GUI (customtkinter)
```

---

## Module Descriptions

### `config.py`

Manages a single JSON config file at `~/.time_tracker/config.json`. Currently the only setting is `db_path`, which defaults to `~/.time_tracker/time_tracker.db`.

The config is read fresh on every call — no in-memory cache — so changes made by the Settings dialog take effect immediately the next time `db.py` opens a connection.

```python
get_db_path() -> Path
set_db_path(path: Path)
```

### `db.py`

All database logic lives here. The rest of the app never touches SQLite directly.

**Connection**: `_connect()` calls `config.get_db_path()` each time, so switching databases at runtime (via Settings) is as simple as calling `init_db()` again.

**Schema** (three tables):

```sql
labels (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name  TEXT NOT NULL UNIQUE,
    color TEXT NOT NULL           -- hex string e.g. "#e74c3c"
)

tasks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL,
    created_at TEXT    NOT NULL,  -- UTC ISO-8601
    label_id   INTEGER REFERENCES labels(id),
    status     TEXT NOT NULL DEFAULT 'active'
                                  -- 'active' | 'inactive' | 'archived'
)

sessions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id          INTEGER NOT NULL REFERENCES tasks(id),
    start_time       TEXT    NOT NULL,  -- UTC ISO-8601
    end_time         TEXT,              -- NULL while recording
    duration_seconds INTEGER            -- NULL while recording
)
```

**Migration strategy**: `init_db()` uses `ALTER TABLE ... ADD COLUMN` guarded by `PRAGMA table_info`. New columns are appended at the end of `init_db()`. This keeps existing databases working without a migration framework.

**Public API**:

| Function | Description |
|---|---|
| `init_db()` | Create tables + run migrations |
| `create_label(name, color) -> int` | Returns new label id |
| `update_label(label_id, name, color)` | Rename / recolor a label |
| `get_labels() -> list[dict]` | All labels, alphabetical |
| `get_tasks_by_label(label_id) -> list[dict]` | Tasks (id, name) assigned to a label — used to populate the delete confirmation |
| `delete_label(label_id)` | Delete label and cascade-delete all its tasks and sessions (permanent) |
| `set_task_label(task_id, label_id\|None)` | Quick label reassignment |
| `create_task(name, label_id=None) -> int` | Returns new task id |
| `get_tasks(status=None) -> list[dict]` | All tasks with totals; filter by status string or None for all |
| `get_task(task_id) -> dict\|None` | Single task with label info and total |
| `update_task(task_id, name, label_id, status)` | Edit name, label, status |
| `delete_task(task_id)` | Delete task and all its sessions (permanent) |
| `start_session(task_id) -> int` | Opens a session; returns session id |
| `stop_session(session_id)` | Closes session, writes duration |
| `get_task_sessions(task_id) -> list[dict]` | All sessions for a task, chronological |

`get_tasks` and `get_task` return dicts with these keys:
`id, name, created_at, label_id, status, label_name, label_color, total_seconds`

All timestamps are stored and returned as UTC ISO-8601 strings. The UI layer converts to local time for display using `datetime.fromisoformat(...).astimezone()`.

**Note**: `set_task_label` is a leftover from an earlier refactor and is now redundant with `update_task`. It is safe to remove.

### `app.py`

Single-file GUI. Everything is one `App(ctk.CTk)` class plus two module-level helpers.

**Module-level constants / helpers**:

- `_NO_LABEL = "No label"` — sentinel string used in dropdowns when no label is selected.
- `_STATUS_STYLE: dict[str, tuple[str, str]]` — maps each status db value to `(display_text, hex_color)`.
- `_fmt_duration(seconds) -> str` — formats an integer of seconds as `HH:MM:SS`.
- `_ColorPicker(ctk.CTkFrame)` — reusable widget: a row of colored swatch buttons where the selected swatch gets a white border. Used in both the label-create and label-edit flows.

**App instance state**:

| Attribute | Type | Purpose |
|---|---|---|
| `_active_task_id` | `int \| None` | Which task is currently being timed |
| `_active_session_id` | `int \| None` | The open session row in the DB |
| `_start_ts` | `float \| None` | `time.monotonic()` snapshot at start — used to compute elapsed without drift |
| `_running` | `bool` | Guards the `_tick` loop and the Settings save action |
| `_active_base_seconds` | `int` | Total seconds already recorded for the active task before this session — added to elapsed for the live "total" display |
| `_task_buttons` | `dict[int, CTkButton]` | Maps task id → Record/Stop button, so `_start`/`_stop` can update button text/color without a full `_refresh_tasks` |
| `_task_total_labels` | `dict[int, CTkLabel]` | Maps task id → total-time label, updated every tick |
| `_label_name_to_id` | `dict[str, int]` | Display name → db id for the create-task label dropdown |
| `_status_filter` | `str` | Current tab: `"Active"`, `"Inactive"`, `"Archived"`, or `"All"` |

**Main window layout** (tkinter grid rows):

```
Row 0  Timer bar (CTkFrame)         — large orange elapsed counter
Row 1  Create-task bar (CTkFrame)   — name entry, label dropdown, buttons
Row 2  Task list (CTkFrame)         — contains: filter bar, header, scroll list
```

Row 2 is given `weight=1` so it stretches vertically when the window is resized.

**Task list layout** (inside `list_frame`, also grid):

```
Row 0  Filter bar (CTkSegmentedButton)
Row 1  Column header (CTkFrame with labels)
Row 2  Scrollable task rows (CTkScrollableFrame)   ← weight=1
```

**Task row columns** (inside each `CTkFrame` in the scroll):

| Col | Widget | Width | Content |
|---|---|---|---|
| 0 | CTkLabel | flexible | Task name |
| 1 | CTkLabel | 90 | Label badge (colored text) |
| 2 | CTkLabel | 110 | Total time (amber) |
| 3 | CTkLabel | 80 | Status badge (colored) |
| 4 | CTkButton | 95 | Record / Stop |
| 5 | CTkButton | 60 | Detail |

**Timer mechanism**: `_start()` saves `time.monotonic()` and calls `_tick()`. `_tick()` computes `elapsed = now - _start_ts`, updates the timer bar and the active task's total label, then schedules itself again with `self.after(1000, self._tick)`. This runs entirely on the main thread — no threads, no concurrency issues.

**Dialogs**: All secondary windows (`CTkToplevel`) call `dialog.update()` before `dialog.grab_set()`. This prevents a race condition on some platforms where `grab_set()` fails if the window hasn't been rendered yet.

---

## Key Design Decisions

- **No threads**: The tick loop uses `self.after` (tkinter's event-loop scheduler) rather than a background thread. This avoids any cross-thread widget mutation and is safe.
- **Full list rebuild on refresh**: `_refresh_tasks()` destroys all child widgets and rebuilds the list from scratch. Simple and correct; performance is fine for hundreds of tasks. If the list grows to thousands, a virtualised list would help.
- **Timestamps in UTC, display in local time**: All times stored in the DB are UTC ISO-8601. They are converted to local time only at the moment of display (`datetime.fromisoformat(...).astimezone()`). This makes the data portable and DST-safe.
- **Flat module structure**: No sub-packages, no service layer. The three modules (`config`, `db`, `app`) map cleanly to config / data / presentation. Adding a fourth for analytics or a separate data-export module would be the natural next step.
- **`dict` return type from db**: `sqlite3.Row` objects are converted to plain `dict` immediately after every query. This keeps `db.py` as the only module that knows about the sqlite3 API, and makes results easy to pass around and inspect.

---

## Color Palette

The UI uses a fixed dark theme. Recurring colors:

| Usage | Hex |
|---|---|
| Amber accent (timer, time values) | `#f39c12` |
| Record (green) | `#2ecc71` / hover `#27ae60` |
| Stop / danger (red) | `#e74c3c` / hover `#c0392b` |
| Active status | `#2ecc71` |
| Inactive status | `#aaaaaa` |
| Archived status | `#666666` |
| Disabled button | `#444444` |
| Row background (even) | `#1e1e1e` |
| Row background (odd) | `#252525` |
| Header bar | `#2b2b2b` |

Label colors are stored in `db.LABEL_COLORS` (8 options): red, orange, yellow, green, teal, blue, purple, pink.

---

## Current Features

- **Create tasks** with an optional label, via the top bar or Enter key.
- **Record time**: one task at a time; switching tasks auto-stops the previous one.
- **Live timer**: elapsed time for the current session shown in the top bar; task total updates every second.
- **Labels**: create with custom name and color swatch; edit name/color; assign to tasks at creation or via Detail.
- **Task detail dialog**: view and edit name, label, status; read-only created date and total time; scrollable session history with per-session start/end/duration; delete task with double confirmation.
- **Task status**: `active` / `inactive` / `archived`; archived tasks have the Record button disabled. Status is editable in the Detail dialog.
- **Status filter tabs**: segmented button above the list ("Active" default, "Inactive", "Archived", "All").
- **Settings**: customizable database path with file browser; reloads the DB on save.

---

## Ideas for Future Development

These have been discussed or are natural next steps. They are not yet started.

### Analysis / Reporting
The most-requested next feature. Options to consider:
- A separate "Analysis" window or tab showing time per label, per task, per day.
- A bar or pie chart using `matplotlib` embedded in a `CTkFrame` via `FigureCanvasTkAgg`.
- Date-range filtering (today / this week / custom range).
- Export to CSV for external analysis.

The DB query foundation: aggregate `sessions.duration_seconds` grouped by `tasks.label_id` or by `DATE(start_time)`.

### Delete Labels
Labels can be deleted via the Manage Labels dialog. Deleting a label cascade-deletes all tasks assigned to it and their sessions. The confirmation dialog lists the affected task names before the final destructive action.

### Session Editing
The session history in the Detail dialog is currently read-only. Useful additions:
- Edit start/end time of a past session (and recompute `duration_seconds`).
- Delete a session (with confirmation).
- Manually add a session for time tracked offline.

### Task Notes / Description
Add a `notes TEXT` column to `tasks`. Show a multi-line text area in the Detail dialog. Useful for jotting context about a task.

### Task Ordering / Pinning
Tasks are ordered by `id DESC` (most recent first). Consider:
- Drag-to-reorder with a `sort_order INTEGER` column.
- Pin / favorite tasks to always appear at the top.

### Search and Filtering
A search box filtering the task list by name. Could combine with the status filter.

### Multiple Databases / Workspaces
Config already supports a custom DB path. A "recent databases" list or named workspaces would make switching contexts easier.

### Packaging
- macOS: `py2app` or `PyInstaller` for a self-contained `.app`.
- Windows: `PyInstaller` for an `.exe`.
- Linux: AppImage or a `.deb`.
The app runs on all three today but requires a Python environment.

---

## Adding a New Feature — Checklist

1. **DB change**: Add to `db.py`. If the schema changes, add a migration guard in `init_db()` using `PRAGMA table_info`.
2. **New query or write**: Add a function in `db.py`; keep all SQL there.
3. **UI**: Add or modify methods in `app.py`. For a new dialog, follow the `_open_*_dialog` pattern: `CTkToplevel` → `dialog.update()` → `dialog.grab_set()`.
4. **Refresh**: After any write, call `self._refresh_tasks()` and/or `self._refresh_label_menu()` so the list stays in sync.
5. **No commits without permission** (see `CLAUDE.md`).
