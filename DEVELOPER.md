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
    status     TEXT NOT NULL DEFAULT 'active',
                                  -- 'active' | 'inactive' | 'archived'
    notes      TEXT,              -- free-form user text, nullable
    deadline   TEXT,              -- date as YYYY-MM-DD, nullable
    priority   TEXT,              -- 'high' | 'medium' | 'low' | NULL
    pinned     INTEGER NOT NULL DEFAULT 0
                                  -- 1 = pinned to top, 0 = normal
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

**Sorting**: `_SORT_EXPR` (module-level dict) maps column key strings to SQL expressions used in the `ORDER BY` clause of `get_tasks`. Priority uses a `CASE/WHEN` expression to impose high→medium→low→NULL ordering. Deadline uses `(t.deadline IS NULL) ASC` to push NULLs last regardless of direction. Adding a new sortable column means adding one entry to `_SORT_EXPR`. The full ORDER BY always prepends `t.pinned DESC` so pinned tasks stay at the top regardless of the user's chosen sort column.

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
| `get_tasks(status=None, label_ids=None, sort_col="id", sort_asc=False) -> list[dict]` | Tasks with totals; filter by status and/or label ids; sort by any column key |
| `get_task(task_id) -> dict\|None` | Single task with label info and total |
| `update_task(task_id, name, label_id, status, notes=None, deadline=None, priority=None)` | Edit all mutable task fields |
| `set_task_pinned(task_id, pinned: bool)` | Toggle pinned state (0/1) |
| `delete_task(task_id)` | Delete task and all its sessions (permanent) |
| `start_session(task_id) -> int` | Opens a session; returns session id |
| `stop_session(session_id)` | Closes session, writes duration |
| `get_task_sessions(task_id) -> list[dict]` | All sessions for a task, chronological |

`get_tasks` and `get_task` return dicts with these keys:
`id, name, created_at, label_id, status, priority, deadline, notes, pinned, label_name, label_color, total_seconds`

All timestamps are stored and returned as UTC ISO-8601 strings. The UI layer converts to local time for display using `datetime.fromisoformat(...).astimezone()`.

**Note**: `set_task_label` is a leftover from an earlier refactor and is now redundant with `update_task`. It is safe to remove.

### `app.py`

Single-file GUI. Everything is one `App(ctk.CTk)` class plus two module-level helpers.

**Module-level constants / helpers**:

- `_NO_LABEL = "No label"` — sentinel string used in dropdowns when no label is selected.
- `_STATUS_STYLE: dict[str, tuple[str, str]]` — maps each status db value to `(display_text, hex_color)`.
- `_PRIORITY_STYLE: dict[str, tuple[str, str]]` — maps each priority db value to `(display_text, hex_color)`: High=red, Med=amber, Low=blue.
- `_COL_DEFS: dict[str, tuple[str, int, str]]` — maps each column key to `(header_label, fixed_width, anchor)`. Width `0` means flexible. Drives both header construction and task-row widget creation.
- `_DEFAULT_COL_ORDER: list[str]` — the initial left-to-right order of data columns. Users can reorder via drag; the list is stored in `App._col_order` at runtime.
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
| `_label_filter` | `set[int]` | Label ids to include; empty set = no label restriction |
| `_sort_col` | `str` | Active sort column key (matches a key in `_SORT_EXPR`); default `"id"` |
| `_sort_asc` | `bool` | Sort direction; `False` = descending (newest-first default) |
| `_header_widgets` | `dict[str, CTkButton]` | Column key → header button; updated by `_update_header_text()` to show ▲/▼ |
| `_label_filter_frame` | `CTkFrame` | Container for label chip buttons; rebuilt by `_refresh_label_filter_bar()` |
| `_col_order` | `list[str]` | Current left-to-right order of data column keys; starts as `_DEFAULT_COL_ORDER`; mutated by drag-to-reorder |
| `_hdr` | `CTkFrame` | Reference to the header frame; `_rebuild_header()` clears and repopulates it in-place |
| `_drag_col` | `str \| None` | Column key being dragged; `None` when idle |
| `_drag_start_x` | `int` | Root-x at `<ButtonPress-1>` — used to distinguish a click (< 8 px) from a drag |
| `_active_task_name` | `str` | Name of the task being recorded — cached at `_start()` to avoid per-tick DB calls |
| `_active_task_label` | `str \| None` | Label name of the task being recorded — cached at `_start()` |
| `_stop_btn` | `CTkButton` | Stop button in the timer bar; enabled/red while recording, disabled/gray when idle |

**Main window layout** (tkinter grid rows):

```
Row 0  Timer bar (CTkFrame)         — task label + elapsed time (amber) + Stop button
Row 1  Create-task bar (CTkFrame)   — name entry, label dropdown, buttons
Row 2  Task list (CTkFrame)         — contains: filter bars, header, scroll list
```

Row 2 is given `weight=1` so it stretches vertically when the window is resized.

**Timer bar** uses a two-column grid: col 0 (weight=1) holds the timer label; col 1 holds the Stop button. While recording the timer label shows `[Label] Task name: HH:MM:SS`; idle shows `--:--:--`. The Stop button is `state="disabled"` and gray when idle, red and enabled while recording.

**Task list layout** (inside `list_frame`, also grid):

```
Row 0  Status filter bar (CTkSegmentedButton)
Row 1  Label filter chip bar (CTkFrame)            — rebuilt on every label change
Row 2  Column header (CTkFrame with buttons)       — sortable columns are CTkButtons
Row 3  Scrollable task rows (CTkScrollableFrame)   ← weight=1
```

Column headers are `CTkButton` widgets with `cursor="hand2"` and `command=None`. They use `<ButtonPress-1>` / `<B1-Motion>` / `<ButtonRelease-1>` bindings. On release: if the mouse moved < 8 px it's treated as a sort click (`_set_sort`); if ≥ 8 px it's a drag — `_col_at_x()` finds the target column by checking `winfo_rootx()` of each header button, swaps the two entries in `_col_order`, and calls `_rebuild_header()` + `_refresh_tasks()`. Non-data columns (pin, Record, Detail) are plain `CTkLabel` and are not draggable.

`_rebuild_header()` clears all children of `self._hdr`, resets all column weights, then recreates buttons for each key in `_col_order` plus fixed placeholders for the pin and action columns. It sets `weight=1` on the column that holds `"name"` so the task-name column stays flexible regardless of position.

**Task row columns** — the pin button is always col 0; data columns follow in `_col_order` order (cols 1…N); Record and Detail are always last. The flexible weight tracks whichever column index holds `"name"` in the current order.

| Col | Widget | Width | Content |
|---|---|---|---|
| 0 | CTkButton | 36 | Pin toggle (amber tint when pinned, dim when not) |
| 1…N | CTkLabel | per `_COL_DEFS` | Data columns in current `_col_order` |
| N+1 | CTkButton | 95 | Record / Stop |
| N+2 | CTkButton | 60 | Detail |

Default `_col_order`: `label (90) · name (flex) · total_seconds (110) · deadline (100) · status (75) · priority (75)`

Pinned rows get background `#211f0a` (amber tint) instead of the normal alternating dark grays, making them visually distinct at a glance. `_make_task_col_widget(parent, key, task, tid)` is the widget factory — add a new `if key == "..."` branch there to support a new column.

**Timer mechanism**: `_start()` saves `time.monotonic()` and calls `_tick()`. `_tick()` computes `elapsed = now - _start_ts`, updates the timer bar and the active task's total label, then schedules itself again with `self.after(1000, self._tick)`. This runs entirely on the main thread — no threads, no concurrency issues.

**Dialogs**: All secondary windows (`CTkToplevel`) call `dialog.update()` before `dialog.grab_set()`. This prevents a race condition on some platforms where `grab_set()` fails if the window hasn't been rendered yet.

**Window close**: `App.__init__` registers `_on_close` as the `WM_DELETE_WINDOW` handler. It calls `_stop()` if a session is in progress, then calls `self.destroy()`. Without this, closing the window mid-recording would leave the session's `end_time` and `duration_seconds` as `NULL` in the database.

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
| Priority High | `#e74c3c` |
| Priority Medium | `#f39c12` |
| Priority Low | `#3498db` |
| Disabled button | `#444444` |
| Row background (even) | `#1e1e1e` |
| Row background (odd) | `#252525` |
| Pinned row background | `#211f0a` |
| Header bar | `#2b2b2b` |

Label colors are stored in `db.LABEL_COLORS` (8 options): red, orange, yellow, green, teal, blue, purple, pink.

---

## Current Features

- **Create tasks** with an optional label, via the top bar or Enter key.
- **Record time**: one task at a time; switching tasks auto-stops the previous one.
- **Live timer**: the timer bar shows `[Label] Task name: HH:MM:SS` while recording (idle shows `--:--:--`); task total in the list updates every second. A **Stop button** sits at the right of the timer bar — always visible, enabled and red while recording, disabled and gray otherwise.
- **Labels**: create with custom name and color swatch; edit name/color; assign to tasks at creation or via Detail. Delete a label via the label manager — cascade-deletes all tasks and their sessions, with a confirmation that lists every affected task by name.
- **Task detail dialog**: view and edit name, label, status, priority, deadline (YYYY-MM-DD, validated), and free-text notes; read-only created date and total time; scrollable session history with per-session start/end/duration; delete task with double confirmation (blocked while the task is actively recording).
- **Task status**: `active` / `inactive` / `archived`; archived tasks have the Record button disabled. Status is editable in the Detail dialog.
- **Priority**: three levels — `high` (red), `medium` (amber), `low` (blue) — shown as a badge in the task list and as a dropdown in the Detail dialog.
- **Deadline**: optional date (YYYY-MM-DD) set in the Detail dialog; validated with `date.fromisoformat()` on save. In the task list, the deadline cell turns red when fewer than 3 days remain (covers overdue, due today, due tomorrow, due in 2 days); gray otherwise.
- **Status filter tabs**: segmented button above the list ("Active" default, "Inactive", "Archived", "All").
- **Label filter chips**: a row of colored toggleable chip buttons below the status tabs, one per label. Multiple labels can be active simultaneously; only tasks whose label matches are shown. A "Clear" button is always visible at the far left of the chip bar. The chip row rebuilds whenever labels change, and stale ids are pruned from `_label_filter` automatically.
- **Pinned tasks**: a "pin" button (col 0) floats a task to the top of the list regardless of the active sort. Pinned rows have an amber-tinted background. Pinned ordering is enforced in SQL (`t.pinned DESC` is always the first ORDER BY term).
- **Deadline in list**: the Deadline column is shown in the main list alongside other data columns. The cell turns red when `(deadline − today).days < 3` (overdue, today, tomorrow, or 2 days away); gray otherwise.
- **Sortable columns**: clicking any column header sorts by that column (ascending first; click again to reverse). Active column highlighted in amber with ▲/▼. Sort is done in SQL via `_SORT_EXPR`. Priority sorts high→medium→low→unset; deadline sorts NULL-last in both directions. All filters (status, label, sort, pin) compose.
- **Drag-to-reorder columns**: dragging a column header left or right swaps it with the column under the drop point. A move < 8 px is treated as a sort click instead. Column order is stored in `_col_order` and survives for the lifetime of the process (not yet persisted to disk).
- **Graceful shutdown**: closing the window while recording auto-stops and saves the active session before the process exits.
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

### Session Editing
The session history in the Detail dialog is currently read-only. Useful additions:
- Edit start/end time of a past session (and recompute `duration_seconds`).
- Delete a session (with confirmation).
- Manually add a session for time tracked offline.

### Persist Column Order
`_col_order` is reset to `_DEFAULT_COL_ORDER` on every launch. Saving it to `config.json` would let users keep their preferred layout across restarts.

### Search by Name
A text-input search box filtering the task list by name substring. Would slot in alongside the existing status and label filters, passed as a `LIKE` clause in `get_tasks`.

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
