import time

import customtkinter as ctk

import db

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

_NO_LABEL = "No label"


def _fmt_duration(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Time Tracker")
        self.geometry("680x580")
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
        ).grid(row=0, column=3, padx=(0, 12), pady=10)

        # ── Row 2: Task list ──
        list_frame = ctk.CTkFrame(self, fg_color="transparent")
        list_frame.grid(row=2, column=0, padx=16, pady=(0, 16), sticky="nsew")
        list_frame.grid_rowconfigure(1, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)

        hdr = ctk.CTkFrame(list_frame, fg_color="#2b2b2b", corner_radius=6)
        hdr.grid(row=0, column=0, sticky="ew", pady=(0, 2))
        for col, (text, w, anchor) in enumerate([
            ("Task",       0,   "w"),
            ("Label",      90,  "w"),
            ("Total time", 110, "e"),
            ("",           95,  "w"),
        ]):
            ctk.CTkLabel(
                hdr, text=text, font=("", 12, "bold"),
                width=w, anchor=anchor,
            ).grid(row=0, column=col, padx=(12, 0), pady=4,
                   sticky="ew" if w == 0 else "")
        hdr.grid_columnconfigure(0, weight=1)

        self._scroll = ctk.CTkScrollableFrame(list_frame, corner_radius=8)
        self._scroll.grid(row=1, column=0, sticky="nsew")
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
        dialog.geometry("340x380")
        dialog.resizable(False, False)
        dialog.update()
        dialog.grab_set()

        dialog.grid_columnconfigure(0, weight=1)
        dialog.grid_rowconfigure(1, weight=1)

        # create new label
        create_frame = ctk.CTkFrame(dialog, corner_radius=8)
        create_frame.grid(row=0, column=0, padx=14, pady=(14, 6), sticky="ew")
        create_frame.grid_columnconfigure(0, weight=1)

        name_var = ctk.StringVar()
        name_field = ctk.CTkEntry(
            create_frame, placeholder_text="Label name…",
            textvariable=name_var, height=34, font=("", 13),
        )
        name_field.grid(row=0, column=0, padx=(10, 6), pady=10, sticky="ew")

        color_var = ctk.StringVar(value=db.LABEL_COLORS[0])
        color_menu = ctk.CTkOptionMenu(
            create_frame,
            values=db.LABEL_COLORS,
            variable=color_var,
            width=110, height=34, font=("", 12),
        )
        color_menu.grid(row=0, column=1, padx=(0, 6), pady=10)

        def _add_label():
            n = name_var.get().strip()
            if not n:
                return
            db.create_label(n, color_var.get())
            name_var.set("")
            self._refresh_label_menu()
            _refresh_list()

        ctk.CTkButton(
            create_frame, text="Add", width=52, height=34,
            font=("", 13, "bold"), command=_add_label,
        ).grid(row=0, column=2, padx=(0, 10), pady=10)
        name_field.bind("<Return>", lambda _: _add_label())

        # existing labels
        scroll = ctk.CTkScrollableFrame(dialog, corner_radius=8)
        scroll.grid(row=1, column=0, padx=14, pady=(0, 14), sticky="nsew")
        scroll.grid_columnconfigure(0, weight=1)

        def _refresh_list():
            for w in scroll.winfo_children():
                w.destroy()
            for i, lbl in enumerate(db.get_labels()):
                row = ctk.CTkFrame(scroll, fg_color="#1e1e1e", corner_radius=4)
                row.grid(row=i, column=0, sticky="ew", pady=1)
                row.grid_columnconfigure(1, weight=1)
                ctk.CTkLabel(
                    row, text="●", text_color=lbl["color"],
                    font=("", 16), width=24,
                ).grid(row=0, column=0, padx=(8, 4), pady=6)
                ctk.CTkLabel(
                    row, text=lbl["name"], anchor="w", font=("", 13),
                ).grid(row=0, column=1, pady=6, sticky="ew")

        _refresh_list()

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
            btn.configure(text="■  Stop", fg_color="#e74c3c", hover_color="#c0392b")

        self._tick()

    def _stop(self):
        self._running = False
        db.stop_session(self._active_session_id)

        btn = self._task_buttons.get(self._active_task_id)
        if btn:
            btn.configure(text="▶  Record", fg_color="#2ecc71", hover_color="#27ae60")

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

        for row_idx, task in enumerate(db.get_tasks()):
            tid = task["id"]
            is_active = tid == self._active_task_id
            bg = "#1e1e1e" if row_idx % 2 == 0 else "#252525"

            row = ctk.CTkFrame(self._scroll, fg_color=bg, corner_radius=4)
            row.grid(row=row_idx, column=0, sticky="ew", pady=1)
            row.grid_columnconfigure(0, weight=1)

            ctk.CTkLabel(
                row, text=task["name"], anchor="w", font=("", 13),
            ).grid(row=0, column=0, padx=(12, 8), pady=6, sticky="ew")

            # label badge
            label_text = task["label_name"] or ""
            label_color = task["label_color"] or "#888"
            ctk.CTkLabel(
                row,
                text=f"● {label_text}" if label_text else "",
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

            btn = ctk.CTkButton(
                row,
                text="■  Stop" if is_active else "▶  Record",
                width=95, height=28, font=("", 12),
                fg_color="#e74c3c" if is_active else "#2ecc71",
                hover_color="#c0392b" if is_active else "#27ae60",
                command=lambda t=tid: self._toggle_record(t),
            )
            btn.grid(row=0, column=3, padx=(0, 10), pady=6)
            self._task_buttons[tid] = btn


if __name__ == "__main__":
    app = App()
    app.mainloop()
