import time

import customtkinter as ctk

import db

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


def _fmt_duration(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Time Tracker")
        self.geometry("620x540")
        self.resizable(True, True)

        self._active_task_id: int | None = None
        self._active_session_id: int | None = None
        self._start_ts: float | None = None
        self._running = False

        self._task_buttons: dict[int, ctk.CTkButton] = {}
        self._task_total_labels: dict[int, ctk.CTkLabel] = {}
        self._active_base_seconds: int = 0

        self._build_ui()
        db.init_db()
        self._refresh_tasks()

    # ── UI construction ──────────────────────────────────────────────────────

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # ── Top: create new task ──
        top = ctk.CTkFrame(self, corner_radius=10)
        top.grid(row=0, column=0, padx=16, pady=(16, 8), sticky="ew")
        top.grid_columnconfigure(0, weight=1)

        self._name_entry = ctk.CTkEntry(
            top, placeholder_text="New task name…", height=40, font=("", 15)
        )
        self._name_entry.grid(row=0, column=0, padx=(12, 8), pady=12, sticky="ew")
        self._name_entry.bind("<Return>", lambda _: self._create_task())

        ctk.CTkButton(
            top,
            text="+ Create",
            width=100,
            height=40,
            font=("", 14, "bold"),
            command=self._create_task,
        ).grid(row=0, column=1, padx=(0, 8), pady=12)

        # live timer shown while a task is recording
        self._timer_label = ctk.CTkLabel(
            top, text="", font=("", 16, "bold"), width=90, text_color="#f39c12"
        )
        self._timer_label.grid(row=0, column=2, padx=(0, 12), pady=12)

        # ── Task list ──
        list_frame = ctk.CTkFrame(self, fg_color="transparent")
        list_frame.grid(row=1, column=0, padx=16, pady=(0, 16), sticky="nsew")
        list_frame.grid_rowconfigure(1, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)

        # column headers
        hdr = ctk.CTkFrame(list_frame, fg_color="#2b2b2b", corner_radius=6)
        hdr.grid(row=0, column=0, sticky="ew", pady=(0, 2))
        for col, (label, w) in enumerate(
            [("Task", 0), ("Total time", 110), ("", 100)]
        ):
            ctk.CTkLabel(
                hdr, text=label, font=("", 12, "bold"),
                width=w if w else 0, anchor="w"
            ).grid(row=0, column=col, padx=(12, 0), pady=4,
                   sticky="ew" if w == 0 else "")
        hdr.grid_columnconfigure(0, weight=1)

        self._scroll = ctk.CTkScrollableFrame(list_frame, corner_radius=8)
        self._scroll.grid(row=1, column=0, sticky="nsew")
        self._scroll.grid_columnconfigure(0, weight=1)

    # ── Create task ──────────────────────────────────────────────────────────

    def _create_task(self):
        name = self._name_entry.get().strip()
        if not name:
            self._name_entry.configure(border_color="red")
            return
        self._name_entry.configure(border_color=("gray65", "gray25"))
        db.create_task(name)
        self._name_entry.delete(0, "end")
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

        # snapshot the task's already-accumulated total so the live tick adds on top
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
        self._timer_label.configure(text="")

        self._refresh_tasks()

    # ── Tick (main-thread, scheduled via self.after) ─────────────────────────

    def _tick(self):
        if not self._running:
            return
        elapsed = int(time.monotonic() - self._start_ts)
        total = self._active_base_seconds + elapsed
        self._timer_label.configure(text=_fmt_duration(elapsed))
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
                row, text=task["name"], anchor="w", font=("", 13)
            ).grid(row=0, column=0, padx=(12, 8), pady=6, sticky="ew")

            total_lbl = ctk.CTkLabel(
                row,
                text=_fmt_duration(task["total_seconds"]),
                width=110, anchor="e", font=("", 13),
                text_color="#f39c12",
            )
            total_lbl.grid(row=0, column=1, padx=(0, 8), pady=6)
            self._task_total_labels[tid] = total_lbl

            btn = ctk.CTkButton(
                row,
                text="■  Stop" if is_active else "▶  Record",
                width=95,
                height=28,
                font=("", 12),
                fg_color="#e74c3c" if is_active else "#2ecc71",
                hover_color="#c0392b" if is_active else "#27ae60",
                command=lambda t=tid: self._toggle_record(t),
            )
            btn.grid(row=0, column=2, padx=(0, 10), pady=6)
            self._task_buttons[tid] = btn


if __name__ == "__main__":
    app = App()
    app.mainloop()
