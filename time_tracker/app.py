import time

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QComboBox,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from time_tracker import db

_NO_LABEL = "No label"

DARK_BG      = "#1a1a1a"
PANEL_BG     = "#2b2b2b"
ROW_BG_A     = "#1e1e1e"
ROW_BG_B     = "#252525"
ACCENT       = "#f39c12"
GREEN        = "#2ecc71"
GREEN_HOVER  = "#27ae60"
RED          = "#e74c3c"
RED_HOVER    = "#c0392b"
GREY_BTN     = "#555555"


def _fmt_duration(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _btn(text: str, color: str, hover: str, width: int = 0) -> QPushButton:
    b = QPushButton(text)
    if width:
        b.setFixedWidth(width)
    b.setFixedHeight(30)
    b.setStyleSheet(f"""
        QPushButton {{
            background: {color}; color: white;
            border: none; border-radius: 5px;
            font-weight: bold; font-size: 13px; padding: 0 10px;
        }}
        QPushButton:hover {{ background: {hover}; }}
    """)
    return b


class LabelsDialog(QDialog):
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setWindowTitle("Manage Labels")
        self.setFixedSize(360, 400)
        self.setStyleSheet(f"background: {DARK_BG}; color: white;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        # create row
        create_frame = QFrame()
        create_frame.setStyleSheet(f"background: {PANEL_BG}; border-radius: 8px;")
        create_layout = QHBoxLayout(create_frame)
        create_layout.setContentsMargins(10, 8, 10, 8)

        self._name_field = QLineEdit()
        self._name_field.setPlaceholderText("Label name…")
        self._name_field.setFixedHeight(32)
        self._name_field.setStyleSheet(
            "background: #3a3a3a; color: white; border: none; border-radius: 4px; padding: 0 6px;"
        )
        create_layout.addWidget(self._name_field)

        self._color_combo = QComboBox()
        self._color_combo.setFixedSize(90, 32)
        self._color_combo.setStyleSheet(
            "background: #3a3a3a; color: white; border: none; border-radius: 4px; padding: 0 4px;"
        )
        for c in db.LABEL_COLORS:
            self._color_combo.addItem(c)
        create_layout.addWidget(self._color_combo)

        add_btn = _btn("Add", "#3498db", "#2980b9", width=50)
        add_btn.clicked.connect(self._add_label)
        create_layout.addWidget(add_btn)
        self._name_field.returnPressed.connect(self._add_label)

        layout.addWidget(create_frame)

        # list
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: none;")
        self._list_widget = QWidget()
        self._list_widget.setStyleSheet(f"background: {DARK_BG};")
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(2)
        self._list_layout.addStretch()
        scroll.setWidget(self._list_widget)
        layout.addWidget(scroll)

        self._refresh_list()

    def _add_label(self):
        name = self._name_field.text().strip()
        if not name:
            return
        color = self._color_combo.currentText()
        db.create_label(name, color)
        self._name_field.clear()
        self._refresh_list()

    def _refresh_list(self):
        # remove all except the trailing stretch
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for lbl in db.get_labels():
            row = QFrame()
            row.setFixedHeight(36)
            row.setStyleSheet(f"background: {PANEL_BG}; border-radius: 4px;")
            h = QHBoxLayout(row)
            h.setContentsMargins(10, 0, 10, 0)

            dot = QLabel("●")
            dot.setStyleSheet(f"color: {lbl['color']}; font-size: 16px;")
            h.addWidget(dot)

            name_lbl = QLabel(lbl["name"])
            name_lbl.setStyleSheet("color: white; font-size: 13px;")
            h.addWidget(name_lbl)
            h.addStretch()

            self._list_layout.insertWidget(self._list_layout.count() - 1, row)


class TaskRow(QFrame):
    """One row in the task list."""

    def __init__(self, task: dict, is_active: bool, toggle_cb, bg: str):
        super().__init__()
        self.setFixedHeight(42)
        self.setStyleSheet(f"background: {bg}; border-radius: 4px;")

        h = QHBoxLayout(self)
        h.setContentsMargins(12, 0, 10, 0)
        h.setSpacing(8)

        name = QLabel(task["name"])
        name.setStyleSheet("color: white; font-size: 13px;")
        name.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        h.addWidget(name)

        # label badge
        if task.get("label_name"):
            badge = QLabel(f"● {task['label_name']}")
            badge.setFixedWidth(100)
            badge.setStyleSheet(f"color: {task['label_color']}; font-size: 12px;")
            h.addWidget(badge)
        else:
            spacer = QLabel("")
            spacer.setFixedWidth(100)
            h.addWidget(spacer)

        self.total_lbl = QLabel(_fmt_duration(task["total_seconds"]))
        self.total_lbl.setFixedWidth(110)
        self.total_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.total_lbl.setStyleSheet(f"color: {ACCENT}; font-size: 13px;")
        h.addWidget(self.total_lbl)

        if is_active:
            rec_btn = _btn("■  Stop", RED, RED_HOVER, width=95)
        else:
            rec_btn = _btn("▶  Record", GREEN, GREEN_HOVER, width=95)
        rec_btn.clicked.connect(toggle_cb)
        h.addWidget(rec_btn)
        self.rec_btn = rec_btn


class App(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Time Tracker")
        self.resize(700, 580)
        self.setStyleSheet(f"background: {DARK_BG}; color: white;")

        self._active_task_id: int | None = None
        self._active_session_id: int | None = None
        self._start_ts: float | None = None
        self._base_seconds: int = 0

        self._task_rows: dict[int, TaskRow] = {}

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

        self._build_ui()
        db.init_db()
        self._refresh_label_combo()
        self._refresh_tasks()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(8)

        # ── Timer bar ──
        timer_frame = QFrame()
        timer_frame.setStyleSheet(f"background: {PANEL_BG}; border-radius: 10px;")
        timer_layout = QHBoxLayout(timer_frame)
        self._timer_label = QLabel("Timer: --:--:--")
        self._timer_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._timer_label.setStyleSheet(f"color: {ACCENT}; font-size: 22px; font-weight: bold;")
        timer_layout.addWidget(self._timer_label)
        root.addWidget(timer_frame)

        # ── Create bar ──
        create_frame = QFrame()
        create_frame.setStyleSheet(f"background: {PANEL_BG}; border-radius: 10px;")
        create_layout = QHBoxLayout(create_frame)
        create_layout.setContentsMargins(12, 10, 12, 10)
        create_layout.setSpacing(8)

        self._name_entry = QLineEdit()
        self._name_entry.setPlaceholderText("New task name…")
        self._name_entry.setFixedHeight(38)
        self._name_entry.setStyleSheet(
            "background: #3a3a3a; color: white; border: none; border-radius: 5px;"
            "padding: 0 8px; font-size: 14px;"
        )
        self._name_entry.returnPressed.connect(self._create_task)
        create_layout.addWidget(self._name_entry)

        self._label_combo = QComboBox()
        self._label_combo.setFixedSize(130, 38)
        self._label_combo.setStyleSheet(
            "background: #3a3a3a; color: white; border: none; border-radius: 5px; padding: 0 6px; font-size: 13px;"
        )
        create_layout.addWidget(self._label_combo)

        create_btn = _btn("+ Create", "#3498db", "#2980b9", width=90)
        create_btn.setFixedHeight(38)
        create_btn.clicked.connect(self._create_task)
        create_layout.addWidget(create_btn)

        labels_btn = _btn("Labels", GREY_BTN, "#444", width=74)
        labels_btn.setFixedHeight(38)
        labels_btn.clicked.connect(self._open_labels_dialog)
        create_layout.addWidget(labels_btn)

        root.addWidget(create_frame)

        # ── Task list ──
        hdr = QFrame()
        hdr.setFixedHeight(30)
        hdr.setStyleSheet(f"background: {PANEL_BG}; border-radius: 6px;")
        hdr_layout = QHBoxLayout(hdr)
        hdr_layout.setContentsMargins(12, 0, 10, 0)
        hdr_layout.setSpacing(8)
        for text, width, align in [
            ("Task",       0,   Qt.AlignmentFlag.AlignLeft),
            ("Label",      100, Qt.AlignmentFlag.AlignLeft),
            ("Total time", 110, Qt.AlignmentFlag.AlignRight),
            ("",           95,  Qt.AlignmentFlag.AlignLeft),
        ]:
            lbl = QLabel(text)
            lbl.setStyleSheet("color: #aaa; font-size: 12px; font-weight: bold;")
            lbl.setAlignment(align | Qt.AlignmentFlag.AlignVCenter)
            if width:
                lbl.setFixedWidth(width)
            else:
                lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            hdr_layout.addWidget(lbl)
        root.addWidget(hdr)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: none;")
        self._list_widget = QWidget()
        self._list_widget.setStyleSheet(f"background: {DARK_BG};")
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(2)
        self._list_layout.addStretch()
        scroll.setWidget(self._list_widget)
        root.addWidget(scroll)

    # ── Label combo ───────────────────────────────────────────────────────────

    def _refresh_label_combo(self):
        self._labels = db.get_labels()
        self._label_combo.clear()
        self._label_combo.addItem(_NO_LABEL)
        for lbl in self._labels:
            self._label_combo.addItem(lbl["name"])

    def _selected_label_id(self) -> int | None:
        idx = self._label_combo.currentIndex()
        if idx == 0:
            return None
        return self._labels[idx - 1]["id"]

    # ── Labels dialog ─────────────────────────────────────────────────────────

    def _open_labels_dialog(self):
        dlg = LabelsDialog(self)
        dlg.exec()
        self._refresh_label_combo()
        self._refresh_tasks()

    # ── Create task ───────────────────────────────────────────────────────────

    def _create_task(self):
        name = self._name_entry.text().strip()
        if not name:
            self._name_entry.setStyleSheet(
                self._name_entry.styleSheet() + "border: 1px solid red;"
            )
            return
        self._name_entry.setStyleSheet(
            self._name_entry.styleSheet().replace("border: 1px solid red;", "")
        )
        db.create_task(name, self._selected_label_id())
        self._name_entry.clear()
        self._label_combo.setCurrentIndex(0)
        self._refresh_tasks()

    # ── Record / Stop ─────────────────────────────────────────────────────────

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

        tasks = {t["id"]: t for t in db.get_tasks()}
        self._base_seconds = tasks[task_id]["total_seconds"] if task_id in tasks else 0

        row = self._task_rows.get(task_id)
        if row:
            row.rec_btn.setText("■  Stop")
            row.rec_btn.setStyleSheet(row.rec_btn.styleSheet()
                .replace(GREEN, RED).replace(GREEN_HOVER, RED_HOVER))

        self._timer.start()

    def _stop(self):
        self._timer.stop()
        db.stop_session(self._active_session_id)

        row = self._task_rows.get(self._active_task_id)
        if row:
            row.rec_btn.setText("▶  Record")
            row.rec_btn.setStyleSheet(row.rec_btn.styleSheet()
                .replace(RED, GREEN).replace(RED_HOVER, GREEN_HOVER))

        self._active_task_id = None
        self._active_session_id = None
        self._start_ts = None
        self._timer_label.setText("Timer: --:--:--")

        self._refresh_tasks()

    # ── Tick ──────────────────────────────────────────────────────────────────

    def _tick(self):
        elapsed = int(time.monotonic() - self._start_ts)
        self._timer_label.setText(f"Timer: {_fmt_duration(elapsed)}")
        row = self._task_rows.get(self._active_task_id)
        if row:
            row.total_lbl.setText(_fmt_duration(self._base_seconds + elapsed))

    # ── Task list ─────────────────────────────────────────────────────────────

    def _refresh_tasks(self):
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._task_rows.clear()

        for i, task in enumerate(db.get_tasks()):
            tid = task["id"]
            is_active = tid == self._active_task_id
            bg = ROW_BG_A if i % 2 == 0 else ROW_BG_B
            row = TaskRow(task, is_active, lambda checked, t=tid: self._toggle_record(t), bg)
            self._list_layout.insertWidget(self._list_layout.count() - 1, row)
            self._task_rows[tid] = row


def main():
    import sys
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = App()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
