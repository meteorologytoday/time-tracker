import time
from datetime import datetime, timezone
from tkinter import filedialog

import customtkinter as ctk

from . import config, db

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

_NO_LABEL = "No label"

# (display text, color) for each task status value
_STATUS_STYLE: dict[str, tuple[str, str]] = {
    "active":   ("Active",   "#2ecc71"),
    "inactive": ("Inactive", "#aaaaaa"),
    "archived": ("Archived", "#666666"),
}


def _fmt_duration(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


class _ColorPicker(ctk.CTkFrame):
    """A row of colored swatch buttons; selected one has a white border."""

    def __init__(self, parent, initial: str | None = None):
        super().__init__(parent, fg_color="transparent")
        self._selected = initial or db.LABEL_COLORS[0]
        self._buttons: dict[str, ctk.CTkButton] = {}
        for col, color in enumerate(db.LABEL_COLORS):
            btn = ctk.CTkButton(
                self, text="", width=26, height=26, corner_radius=5,
                fg_color=color, hover_color=color,
                border_width=2,
                border_color="white" if color == self._selected else color,
                command=lambda c=color: self._select(c),
            )
            btn.grid(row=0, column=col, padx=3)
            self._buttons[color] = btn

    def _select(self, color: str):
        self._buttons[self._selected].configure(border_color=self._selected)
        self._selected = color
        self._buttons[color].configure(border_color="white")

    def get(self) -> str:
        return self._selected

    def reset(self):
        self._select(db.LABEL_COLORS[0])


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Time Tracker")
        self.geometry("780x580")
        self.resizable(True, True)

        self._active_task_id: int | None = None
        self._active_session_id: int | None = None
        self._start_ts: float | None = None
        self._running = False

        self._task_buttons: dict[int, ctk.CTkButton] = {}
        self._task_total_labels: dict[int, ctk.CTkLabel] = {}
        self._active_base_seconds: int = 0

        # label id lookup: display name → id  (populated in _refresh_label_menu)
        self._label_name_to_id: dict[str, int] = {}

        # current filter shown in the task list ("Active"/"Inactive"/"Archived"/"All")
        self._status_filter = "Active"

        self._build_ui()
        db.init_db()
        self._refresh_label_menu()
        self._refresh_tasks()

    # ── UI construction ──────────────────────────────────────────────────────

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # ── Row 0: Timer display ──
        timer_bar = ctk.CTkFrame(self, corner_radius=10)
        timer_bar.grid(row=0, column=0, padx=16, pady=(16, 4), sticky="ew")

        self._timer_label = ctk.CTkLabel(
            timer_bar,
            text="Timer: --:--:--",
            font=("", 22, "bold"),
            text_color="#f39c12",
            anchor="center",
        )
        self._timer_label.pack(pady=14)

        # ── Row 1: Create new task ──
        top = ctk.CTkFrame(self, corner_radius=10)
        top.grid(row=1, column=0, padx=16, pady=(4, 8), sticky="ew")
        top.grid_columnconfigure(0, weight=1)

        self._name_entry = ctk.CTkEntry(
            top, placeholder_text="New task name…", height=36, font=("", 14)
        )
        self._name_entry.grid(row=0, column=0, padx=(12, 8), pady=10, sticky="ew")
        self._name_entry.bind("<Return>", lambda _: self._create_task())

        # label selector
        self._label_menu = ctk.CTkOptionMenu(
            top, width=130, height=36, font=("", 13),
            values=[_NO_LABEL],
        )
        self._label_menu.grid(row=0, column=1, padx=(0, 8), pady=10)

        ctk.CTkButton(
            top,
            text="+ Create",
            width=90,
            height=36,
            font=("", 13, "bold"),
            command=self._create_task,
        ).grid(row=0, column=2, padx=(0, 8), pady=10)

        ctk.CTkButton(
            top,
            text="Labels",
            width=74,
            height=36,
            font=("", 13),
            fg_color="#555",
            hover_color="#444",
            command=self._open_labels_dialog,
        ).grid(row=0, column=3, padx=(0, 8), pady=10)

        ctk.CTkButton(
            top,
            text="Settings",
            width=74,
            height=36,
            font=("", 13),
            fg_color="#444",
            hover_color="#333",
            command=self._open_settings_dialog,
        ).grid(row=0, column=4, padx=(0, 12), pady=10)

        # ── Row 2: Task list ──
        list_frame = ctk.CTkFrame(self, fg_color="transparent")
        list_frame.grid(row=2, column=0, padx=16, pady=(0, 16), sticky="nsew")
        list_frame.grid_rowconfigure(2, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)

        # filter bar
        self._filter_bar = ctk.CTkSegmentedButton(
            list_frame,
            values=["Active", "Inactive", "Archived", "All"],
            command=self._set_status_filter,
        )
        self._filter_bar.set("Active")
        self._filter_bar.grid(row=0, column=0, sticky="w", pady=(0, 6))

        hdr = ctk.CTkFrame(list_frame, fg_color="#2b2b2b", corner_radius=6)
        hdr.grid(row=1, column=0, sticky="ew", pady=(0, 2))
        for col, (text, w, anchor) in enumerate([
            ("Task",       0,   "w"),
            ("Label",      90,  "w"),
            ("Total time", 110, "e"),
            ("Status",     80,  "w"),
            ("",           95,  "w"),
            ("",           60,  "w"),
        ]):
            ctk.CTkLabel(
                hdr, text=text, font=("", 12, "bold"),
                width=w, anchor=anchor,
            ).grid(row=0, column=col, padx=(12, 0), pady=4,
                   sticky="ew" if w == 0 else "")
        hdr.grid_columnconfigure(0, weight=1)

        self._scroll = ctk.CTkScrollableFrame(list_frame, corner_radius=8)
        self._scroll.grid(row=2, column=0, sticky="nsew")
        self._scroll.grid_columnconfigure(0, weight=1)

    # ── Label menu helpers ────────────────────────────────────────────────────

    def _refresh_label_menu(self):
        labels = db.get_labels()
        self._label_name_to_id = {l["name"]: l["id"] for l in labels}
        values = [_NO_LABEL] + [l["name"] for l in labels]
        self._label_menu.configure(values=values)
        if self._label_menu.get() not in values:
            self._label_menu.set(_NO_LABEL)

    def _selected_label_id(self) -> int | None:
        name = self._label_menu.get()
        return self._label_name_to_id.get(name)

    # ── Labels dialog ─────────────────────────────────────────────────────────

    def _open_labels_dialog(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Manage Labels")
        dialog.geometry("400x420")
        dialog.resizable(False, False)
        dialog.update()
        dialog.grab_set()

        dialog.grid_columnconfigure(0, weight=1)
        dialog.grid_rowconfigure(1, weight=1)

        # ── Create new label ──
        create_frame = ctk.CTkFrame(dialog, corner_radius=8)
        create_frame.grid(row=0, column=0, padx=14, pady=(14, 6), sticky="ew")
        create_frame.grid_columnconfigure(0, weight=1)

        name_var = ctk.StringVar()
        name_field = ctk.CTkEntry(
            create_frame, placeholder_text="Label name…",
            textvariable=name_var, height=34, font=("", 13),
        )
        name_field.grid(row=0, column=0, padx=(10, 8), pady=(10, 4), sticky="ew")

        def _add_label():
            n = name_var.get().strip()
            if not n:
                return
            db.create_label(n, color_picker.get())
            name_var.set("")
            color_picker.reset()
            self._refresh_label_menu()
            _refresh_list()

        ctk.CTkButton(
            create_frame, text="Add", width=52, height=34,
            font=("", 13, "bold"), command=_add_label,
        ).grid(row=0, column=1, padx=(0, 10), pady=(10, 4))
        name_field.bind("<Return>", lambda _: _add_label())

        color_picker = _ColorPicker(create_frame)
        color_picker.grid(row=1, column=0, columnspan=2, padx=10, pady=(0, 10), sticky="w")

        # ── Existing labels ──
        scroll = ctk.CTkScrollableFrame(dialog, corner_radius=8)
        scroll.grid(row=1, column=0, padx=14, pady=(0, 14), sticky="nsew")
        scroll.grid_columnconfigure(0, weight=1)

        def _open_edit(lbl: dict):
            edit = ctk.CTkToplevel(dialog)
            edit.title("Edit Label")
            edit.geometry("400x140")
            edit.resizable(False, False)
            edit.update()
            edit.grab_set()
            edit.grid_columnconfigure(0, weight=1)

            name_e_var = ctk.StringVar(value=lbl["name"])
            name_e = ctk.CTkEntry(
                edit, textvariable=name_e_var, height=34, font=("", 13),
            )
            name_e.grid(row=0, column=0, padx=(12, 8), pady=(12, 4), sticky="ew")

            ep = _ColorPicker(edit, initial=lbl["color"])
            ep.grid(row=1, column=0, padx=12, pady=(0, 8), sticky="w")

            def _save():
                n = name_e_var.get().strip()
                if not n:
                    return
                db.update_label(lbl["id"], n, ep.get())
                self._refresh_label_menu()
                self._refresh_tasks()
                edit.destroy()
                _refresh_list()

            btn_row = ctk.CTkFrame(edit, fg_color="transparent")
            btn_row.grid(row=2, column=0, padx=12, pady=(0, 12), sticky="e")
            ctk.CTkButton(btn_row, text="Save", width=70, height=30,
                          font=("", 13, "bold"), command=_save,
                          ).pack(side="left", padx=(0, 6))
            ctk.CTkButton(btn_row, text="Cancel", width=70, height=30,
                          font=("", 13), fg_color="#555", hover_color="#444",
                          command=edit.destroy,
                          ).pack(side="left")
            name_e.bind("<Return>", lambda _: _save())

        def _refresh_list():
            for w in scroll.winfo_children():
                w.destroy()
            for i, lbl in enumerate(db.get_labels()):
                row = ctk.CTkFrame(scroll, fg_color="#1e1e1e", corner_radius=4)
                row.grid(row=i, column=0, sticky="ew", pady=1)
                row.grid_columnconfigure(0, weight=1)
                ctk.CTkLabel(
                    row, text=lbl["name"], anchor="w", font=("", 13),
                    text_color=lbl["color"],
                ).grid(row=0, column=0, pady=6, padx=(8, 0), sticky="ew")
                ctk.CTkButton(
                    row, text="Edit", width=48, height=26, font=("", 12),
                    fg_color="#555", hover_color="#444",
                    command=lambda l=lbl: _open_edit(l),
                ).grid(row=0, column=1, padx=(0, 8), pady=6)

        _refresh_list()

    # ── Settings dialog ───────────────────────────────────────────────────────

    def _open_settings_dialog(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Settings")
        dialog.geometry("520x150")
        dialog.resizable(False, False)
        dialog.update()
        dialog.grab_set()
        dialog.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            dialog, text="Database path:", anchor="w", font=("", 13),
        ).grid(row=0, column=0, columnspan=3, padx=14, pady=(14, 4), sticky="ew")

        path_var = ctk.StringVar(value=str(config.get_db_path()))
        path_entry = ctk.CTkEntry(dialog, textvariable=path_var, height=34, font=("", 12))
        path_entry.grid(row=1, column=0, padx=(14, 4), pady=(0, 4), sticky="ew")

        def _browse():
            current = path_var.get().strip()
            from pathlib import Path as _Path
            p = filedialog.asksaveasfilename(
                parent=dialog,
                title="Choose database location",
                defaultextension=".db",
                filetypes=[("SQLite database", "*.db"), ("All files", "*.*")],
                initialfile=_Path(current).name if current else "time_tracker.db",
                initialdir=str(_Path(current).parent) if current else str(_Path.home()),
            )
            if p:
                path_var.set(p)

        ctk.CTkButton(
            dialog, text="Browse", width=74, height=34, font=("", 13),
            fg_color="#555", hover_color="#444", command=_browse,
        ).grid(row=1, column=1, padx=(0, 4), pady=(0, 4))

        msg_label = ctk.CTkLabel(dialog, text="", font=("", 11), text_color="#e74c3c")
        msg_label.grid(row=2, column=0, columnspan=2, padx=14, sticky="w")

        def _save():
            if self._running:
                msg_label.configure(text="Please stop the active recording first.")
                return
            p = path_var.get().strip()
            if not p:
                msg_label.configure(text="Path cannot be empty.")
                return
            config.set_db_path(path_var.get().strip())
            db.init_db()
            self._refresh_label_menu()
            self._refresh_tasks()
            dialog.destroy()

        ctk.CTkButton(
            dialog, text="Save", width=60, height=34, font=("", 13, "bold"),
            command=_save,
        ).grid(row=1, column=2, padx=(0, 14), pady=(0, 4))
        path_entry.bind("<Return>", lambda _: _save())

    def _set_status_filter(self, value: str):
        self._status_filter = value
        self._refresh_tasks()

    # ── Create task ──────────────────────────────────────────────────────────

    def _create_task(self):
        name = self._name_entry.get().strip()
        if not name:
            self._name_entry.configure(border_color="red")
            return
        self._name_entry.configure(border_color=("gray65", "gray25"))
        db.create_task(name, self._selected_label_id())
        self._name_entry.delete(0, "end")
        self._label_menu.set(_NO_LABEL)
        self._refresh_tasks()

    # ── Record / Stop ────────────────────────────────────────────────────────

    def _toggle_record(self, task_id: int):
        if self._active_task_id == task_id:
            self._stop()
        else:
            if self._active_task_id is not None:
                self._stop()
            self._start(task_id)

    def _start(self, task_id: int):
        self._active_task_id = task_id
        self._active_session_id = db.start_session(task_id)
        self._start_ts = time.monotonic()
        self._running = True

        tasks = {t["id"]: t for t in db.get_tasks()}
        self._active_base_seconds = tasks[task_id]["total_seconds"] if task_id in tasks else 0

        btn = self._task_buttons.get(task_id)
        if btn:
            btn.configure(text="Stop", fg_color="#e74c3c", hover_color="#c0392b")

        self._tick()

    def _stop(self):
        self._running = False
        db.stop_session(self._active_session_id)

        btn = self._task_buttons.get(self._active_task_id)
        if btn:
            btn.configure(text="Record", fg_color="#2ecc71", hover_color="#27ae60")

        self._active_task_id = None
        self._active_session_id = None
        self._start_ts = None
        self._timer_label.configure(text="Timer: --:--:--")

        self._refresh_tasks()

    # ── Tick (main-thread, scheduled via self.after) ─────────────────────────

    def _tick(self):
        if not self._running:
            return
        elapsed = int(time.monotonic() - self._start_ts)
        total = self._active_base_seconds + elapsed
        self._timer_label.configure(text=f"Timer: {_fmt_duration(elapsed)}")
        lbl = self._task_total_labels.get(self._active_task_id)
        if lbl:
            lbl.configure(text=_fmt_duration(total))
        self.after(1000, self._tick)

    # ── Task list ────────────────────────────────────────────────────────────

    def _refresh_tasks(self):
        for widget in self._scroll.winfo_children():
            widget.destroy()
        self._task_buttons.clear()
        self._task_total_labels.clear()

        db_status = None if self._status_filter == "All" else self._status_filter.lower()
        for row_idx, task in enumerate(db.get_tasks(db_status)):
            tid = task["id"]
            is_active = tid == self._active_task_id
            is_archived = task["status"] == "archived"
            bg = "#1e1e1e" if row_idx % 2 == 0 else "#252525"

            row = ctk.CTkFrame(self._scroll, fg_color=bg, corner_radius=4)
            row.grid(row=row_idx, column=0, sticky="ew", pady=1)
            row.grid_columnconfigure(0, weight=1)

            name_color = "#888" if is_archived else ("gray80", "gray80")
            ctk.CTkLabel(
                row, text=task["name"], anchor="w", font=("", 13),
                text_color="#aaaaaa" if is_archived else ("#d0d0d0", "#d0d0d0"),
            ).grid(row=0, column=0, padx=(12, 8), pady=6, sticky="ew")

            # label badge
            label_text = task["label_name"] or ""
            label_color = task["label_color"] or "#888"
            ctk.CTkLabel(
                row,
                text=label_text,
                text_color=label_color,
                width=90, anchor="w", font=("", 12),
            ).grid(row=0, column=1, padx=(0, 8), pady=6)

            total_lbl = ctk.CTkLabel(
                row,
                text=_fmt_duration(task["total_seconds"]),
                width=110, anchor="e", font=("", 13),
                text_color="#f39c12",
            )
            total_lbl.grid(row=0, column=2, padx=(0, 8), pady=6)
            self._task_total_labels[tid] = total_lbl

            # status badge
            status_text, status_color = _STATUS_STYLE.get(
                task["status"], ("?", "#888")
            )
            ctk.CTkLabel(
                row, text=status_text, text_color=status_color,
                width=80, anchor="w", font=("", 11),
            ).grid(row=0, column=3, padx=(0, 6), pady=6)

            # record button — disabled (visually) for archived tasks
            if is_active:
                btn_text, btn_fg, btn_hover = "Stop", "#e74c3c", "#c0392b"
                btn_cmd = lambda t=tid: self._toggle_record(t)
            elif is_archived:
                btn_text, btn_fg, btn_hover = "Record", "#444444", "#444444"
                btn_cmd = lambda: None
            else:
                btn_text, btn_fg, btn_hover = "Record", "#2ecc71", "#27ae60"
                btn_cmd = lambda t=tid: self._toggle_record(t)

            btn = ctk.CTkButton(
                row,
                text=btn_text, width=95, height=28, font=("", 12),
                fg_color=btn_fg, hover_color=btn_hover,
                command=btn_cmd,
            )
            btn.grid(row=0, column=4, padx=(0, 6), pady=6)
            self._task_buttons[tid] = btn

            ctk.CTkButton(
                row,
                text="Detail",
                width=60, height=28, font=("", 12),
                fg_color="#3a3a5c", hover_color="#2e2e4a",
                command=lambda t=tid: self._open_task_detail_dialog(t),
            ).grid(row=0, column=5, padx=(0, 10), pady=6)


    # ── Task detail dialog ───────────────────────────────────────────────────

    def _open_task_detail_dialog(self, task_id: int):
        task = db.get_task(task_id)
        if task is None:
            return

        dialog = ctk.CTkToplevel(self)
        dialog.title(f"Task Detail — {task['name']}")
        dialog.geometry("520x500")
        dialog.resizable(True, True)
        dialog.update()
        dialog.grab_set()
        dialog.grid_columnconfigure(0, weight=1)
        dialog.grid_rowconfigure(2, weight=1)

        # ── Info / edit frame ──
        info = ctk.CTkFrame(dialog, corner_radius=8)
        info.grid(row=0, column=0, padx=14, pady=(14, 6), sticky="ew")
        info.grid_columnconfigure(1, weight=1)

        def _row_label(text, r):
            ctk.CTkLabel(info, text=text, anchor="e", font=("", 12),
                         text_color="#888").grid(
                row=r, column=0, padx=(12, 8), pady=4, sticky="e")

        _row_label("Name:", 0)
        name_var = ctk.StringVar(value=task["name"])
        ctk.CTkEntry(info, textvariable=name_var, height=32, font=("", 13),
                     ).grid(row=0, column=1, columnspan=2, padx=(0, 12),
                            pady=4, sticky="ew")

        _row_label("Label:", 1)
        labels = db.get_labels()
        label_name_to_id = {l["name"]: l["id"] for l in labels}
        label_values = [_NO_LABEL] + [l["name"] for l in labels]
        current_label = task["label_name"] or _NO_LABEL
        label_menu = ctk.CTkOptionMenu(
            info, values=label_values, width=160, height=32, font=("", 13),
        )
        label_menu.set(current_label)
        label_menu.grid(row=1, column=1, columnspan=2, padx=(0, 12),
                        pady=4, sticky="w")

        _row_label("Status:", 2)
        status_menu = ctk.CTkOptionMenu(
            info, values=["active", "inactive", "archived"],
            width=130, height=32, font=("", 13),
        )
        status_menu.set(task.get("status", "active"))
        status_menu.grid(row=2, column=1, columnspan=2, padx=(0, 12),
                         pady=4, sticky="w")

        _row_label("Created:", 3)
        created_local = datetime.fromisoformat(task["created_at"]).astimezone()
        ctk.CTkLabel(info, text=created_local.strftime("%Y-%m-%d %H:%M"),
                     anchor="w", font=("", 12)).grid(
            row=3, column=1, columnspan=2, padx=(0, 12), pady=4, sticky="w")

        _row_label("Total time:", 4)
        ctk.CTkLabel(info,
                     text=_fmt_duration(task["total_seconds"]),
                     anchor="w", font=("", 12), text_color="#f39c12").grid(
            row=4, column=1, columnspan=2, padx=(0, 12), pady=(4, 8),
            sticky="w")

        msg_label = ctk.CTkLabel(dialog, text="", font=("", 11),
                                 text_color="#e74c3c")
        msg_label.grid(row=1, column=0, padx=14, sticky="w")

        def _save():
            n = name_var.get().strip()
            if not n:
                msg_label.configure(text="Name cannot be empty.")
                return
            sel = label_menu.get()
            lid = label_name_to_id.get(sel) if sel != _NO_LABEL else None
            db.update_task(task_id, n, lid, status_menu.get())
            if task_id in self._task_buttons:
                self._refresh_tasks()
            dialog.title(f"Task Detail — {n}")
            msg_label.configure(text="Saved.", text_color="#2ecc71")

        save_btn = ctk.CTkButton(
            info, text="Save", width=70, height=32, font=("", 13, "bold"),
            command=_save,
        )
        save_btn.grid(row=0, column=3, rowspan=3, padx=(6, 12), pady=4)

        # ── Sessions list ──
        ctk.CTkLabel(dialog, text="Sessions", font=("", 13, "bold"),
                     anchor="w").grid(row=2, column=0, padx=14, pady=(6, 2),
                                      sticky="nw")

        sessions_outer = ctk.CTkFrame(dialog, corner_radius=8)
        sessions_outer.grid(row=2, column=0, padx=14, pady=(28, 14),
                            sticky="nsew")
        sessions_outer.grid_columnconfigure(0, weight=1)
        sessions_outer.grid_rowconfigure(1, weight=1)

        # header row
        shdr = ctk.CTkFrame(sessions_outer, fg_color="#2b2b2b", corner_radius=4)
        shdr.grid(row=0, column=0, sticky="ew", padx=4, pady=(4, 0))
        for scol, (stxt, sw) in enumerate([
            ("#",        30),
            ("Start",   165),
            ("End",     165),
            ("Duration", 90),
        ]):
            ctk.CTkLabel(shdr, text=stxt, width=sw, font=("", 11, "bold"),
                         anchor="w").grid(row=0, column=scol, padx=(6, 0),
                                          pady=3)

        scroll = ctk.CTkScrollableFrame(sessions_outer, corner_radius=4)
        scroll.grid(row=1, column=0, sticky="nsew", padx=4, pady=(0, 4))
        scroll.grid_columnconfigure(1, weight=1)

        sessions = db.get_task_sessions(task_id)
        if not sessions:
            ctk.CTkLabel(scroll, text="No sessions recorded yet.",
                         font=("", 12), text_color="#888").grid(
                row=0, column=0, columnspan=4, padx=8, pady=8, sticky="w")
        else:
            for i, s in enumerate(sessions):
                bg = "#1e1e1e" if i % 2 == 0 else "#252525"
                srow = ctk.CTkFrame(scroll, fg_color=bg, corner_radius=3)
                srow.grid(row=i, column=0, sticky="ew", pady=1)

                start_dt = datetime.fromisoformat(s["start_time"]).astimezone()
                start_str = start_dt.strftime("%Y-%m-%d %H:%M")

                if s["end_time"]:
                    end_dt = datetime.fromisoformat(s["end_time"]).astimezone()
                    end_str = end_dt.strftime("%Y-%m-%d %H:%M")
                else:
                    end_str = "In progress"

                dur = _fmt_duration(s["duration_seconds"] or 0)

                for scol, (val, sw, color) in enumerate([
                    (str(i + 1),  30,  "#888"),
                    (start_str,  165,  "#ccc"),
                    (end_str,    165,  "#ccc" if s["end_time"] else "#f39c12"),
                    (dur,         90,  "#f39c12"),
                ]):
                    ctk.CTkLabel(
                        srow, text=val, width=sw, font=("", 11),
                        anchor="w", text_color=color,
                    ).grid(row=0, column=scol, padx=(6, 0), pady=3)


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
