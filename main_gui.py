import sys
import json
import threading
import os
import time
import csv
from datetime import datetime, timedelta
from threading import Event
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout,
    QPushButton, QTextEdit, QLabel,
    QLineEdit, QFileDialog,
    QTableWidget, QTableWidgetItem,
    QSpinBox
)
from PySide6.QtCore import Signal, QObject
from PySide6.QtGui import QIcon

from sync_engine import sync_one_way


# -------------------- CONSTANTS --------------------
STATUS_IDLE = "⚪ IDLE"
STATUS_RUNNING = "🟢 RUNNING"
STATUS_STOPPED = "🔴 STOPPED"


# -------------------- LOGGER --------------------
class Logger(QObject):
    log_signal = Signal(str)


class CSVLogger:
    def __init__(self, log_dir="logs"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)
        self.current_date = None
        self.file = None
        self.writer = None

    def _open_if_needed(self):
        today = datetime.now().date()
        if self.current_date != today:
            if self.file:
                self.file.close()

            self.current_date = today
            path = self.log_dir / f"logs_{today}.csv"
            new = not path.exists()

            self.file = open(path, "a", newline="", encoding="utf-8")
            self.writer = csv.writer(self.file)

            if new:
                self.writer.writerow(["Timestamp", "Profile", "Message"])

    def log(self, profile, message):
        self._open_if_needed()
        self.writer.writerow([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            profile,
            message
        ])
        self.file.flush()


def resource_path(name):
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, name)
    return os.path.join(os.path.abspath("."), name)


# -------------------- MAIN APP --------------------
class SyncApp(QMainWindow):
    def __init__(self):
        super().__init__()

        self.csv_logger = CSVLogger()
        self.logger = Logger()
        self.logger.log_signal.connect(self.add_log)

        self.workers = {}
        self.profile_status = {}
        self.next_run_times = {}

        self.config_path = "config.json"
        self.load_config()

        self.setWindowTitle(" SyncBridge ")
        self.setWindowIcon(QIcon(resource_path("syncbridge.ico")))
        QApplication.setWindowIcon(QIcon(resource_path("syncbridge.ico")))
        self.resize(1100, 600)

        self.statusBar().showMessage(
            "SyncBridge © 2026 | Developed by Abhishek Kumar Shriwastva | ABP Network IT"
        )

        # ---------------- UI ----------------
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)

        # LEFT
        left = QVBoxLayout()
        layout.addLayout(left, 3)

        self.profile_table = QTableWidget(0, 3)
        self.profile_table.setHorizontalHeaderLabels(
            ["Profile", "Status", "Next Run"]
        )
        self.profile_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.profile_table.setEditTriggers(QTableWidget.NoEditTriggers)
        left.addWidget(self.profile_table)

        btns = QHBoxLayout()
        self.add_btn = QPushButton("➕ Add")
        self.del_btn = QPushButton("🗑 Delete")
        btns.addWidget(self.add_btn)
        btns.addWidget(self.del_btn)
        left.addLayout(btns)

        # RIGHT
        right = QVBoxLayout()
        layout.addLayout(right, 6)

        right.addWidget(QLabel("Profile Name"))
        self.name_edit = QLineEdit()
        right.addWidget(self.name_edit)

        right.addWidget(QLabel("Source"))
        self.src_edit = QLineEdit()
        src_btn = QPushButton("Browse")
        src_btn.clicked.connect(lambda: self.browse(self.src_edit))
        row = QHBoxLayout()
        row.addWidget(self.src_edit)
        row.addWidget(src_btn)
        right.addLayout(row)

        right.addWidget(QLabel("Destination"))
        self.dst_edit = QLineEdit()
        dst_btn = QPushButton("Browse")
        dst_btn.clicked.connect(lambda: self.browse(self.dst_edit))
        row = QHBoxLayout()
        row.addWidget(self.dst_edit)
        row.addWidget(dst_btn)
        right.addLayout(row)

        right.addWidget(QLabel("Schedule (Minutes)"))
        self.schedule_spin = QSpinBox()
        self.schedule_spin.setRange(1, 1440)
        right.addWidget(self.schedule_spin)

        controls = QHBoxLayout()
        self.run_btn = QPushButton("▶ Run Selected")
        self.run_all_btn = QPushButton("▶ Run All")
        self.stop_btn = QPushButton("⏹ Stop Selected")
        self.stop_all_btn = QPushButton("⏹ Stop All")
        controls.addWidget(self.run_btn)
        controls.addWidget(self.run_all_btn)
        controls.addWidget(self.stop_btn)
        controls.addWidget(self.stop_all_btn)
        right.addLayout(controls)

        right.addWidget(QLabel("Log"))
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        right.addWidget(self.log_view)

        # SIGNALS
        self.profile_table.itemSelectionChanged.connect(self.load_profile)
        self.add_btn.clicked.connect(self.add_profile)
        self.del_btn.clicked.connect(self.delete_profile)
        self.run_btn.clicked.connect(self.start_selected_profile)
        self.run_all_btn.clicked.connect(self.start_all_profiles)
        self.stop_btn.clicked.connect(self.stop_selected_profile)
        self.stop_all_btn.clicked.connect(self.stop_all_profiles)

        self.name_edit.textEdited.connect(self.rename_profile)
        self.src_edit.textEdited.connect(self.save_current_profile)
        self.dst_edit.textEdited.connect(self.save_current_profile)
        self.schedule_spin.valueChanged.connect(self.save_current_profile)

        self.populate_profiles()

    # ---------------- CONFIG ----------------
    def load_config(self):
        if not os.path.exists(self.config_path):
            self.cfg = {"profiles": []}
            self.save_config()
        else:
            with open(self.config_path, "r", encoding="utf-8") as f:
                self.cfg = json.load(f)

    def save_config(self):
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self.cfg, f, indent=2)

    # ---------------- PROFILES ----------------
    def populate_profiles(self):
     self.profile_table.setRowCount(0)

     for p in self.cfg["profiles"]:
        row = self.profile_table.rowCount()
        self.profile_table.insertRow(row)

        name = p["name"]

        status = self.profile_status.get(name, STATUS_IDLE)
        next_run = self.next_run_times.get(name, "-")

        self.profile_table.setItem(row, 0, QTableWidgetItem(name))
        self.profile_table.setItem(row, 1, QTableWidgetItem(status))
        self.profile_table.setItem(row, 2, QTableWidgetItem(next_run))

     if self.profile_table.rowCount():
        self.profile_table.selectRow(0)

    def current_profile_index(self):
        sel = self.profile_table.selectionModel().selectedRows()
        return sel[0].row() if sel else -1

    def load_profile(self):
        i = self.current_profile_index()
        if i < 0:
            return
        p = self.cfg["profiles"][i]
        self.name_edit.setText(p["name"])
        self.src_edit.setText(p["source"])
        self.dst_edit.setText(p["destination"])
        self.schedule_spin.setValue(p.get("schedule", {}).get("minutes", 15))

    def rename_profile(self, new_name):
        i = self.current_profile_index()
        if i < 0:
            return

        old = self.cfg["profiles"][i]["name"]
        new = new_name.strip()
        if not new or new == old:
            return

        # migrate runtime state
        if old in self.workers:
            self.workers[new] = self.workers.pop(old)
        if old in self.profile_status:
            self.profile_status[new] = self.profile_status.pop(old)
        if old in self.next_run_times:
            self.next_run_times[new] = self.next_run_times.pop(old)

        self.cfg["profiles"][i]["name"] = new
        self.profile_table.item(i, 0).setText(new)
        self.save_config()

    def save_current_profile(self):
        i = self.current_profile_index()
        if i < 0:
            return
        p = self.cfg["profiles"][i]
        p["source"] = self.src_edit.text()
        p["destination"] = self.dst_edit.text()
        p["schedule"] = {"type": "interval", "minutes": self.schedule_spin.value()}
        self.save_config()

    def add_profile(self):
        self.cfg["profiles"].append({
            "name": "New Profile",
            "source": "",
            "destination": "",
            "delete_extras": True,
            "schedule": {"type": "interval", "minutes": 15}
        })
        self.save_config()
        self.populate_profiles()

    def delete_profile(self):
        i = self.current_profile_index()
        if i < 0:
            return
        name = self.cfg["profiles"][i]["name"]
        if name in self.workers:
            self.workers[name].set()
        del self.cfg["profiles"][i]
        self.save_config()
        self.populate_profiles()

    # ---------------- LOGGING ----------------
    def add_log(self, msg):
        self.log_view.append(msg)

        profile = "SYSTEM"
        if msg.startswith("[") and "]" in msg:
            profile = msg[1:msg.index("]")]

        clean = msg.replace("▶", "").replace("🛑", "").replace("⚠", "").replace("❌", "").strip()
        self.csv_logger.log(profile, clean)

    # ---------------- WORKER ----------------
    def start_worker(self, profile):
        name = profile["name"]
        if name in self.workers:
            return

        stop = Event()
        self.workers[name] = stop
        self.set_status(name, STATUS_RUNNING)

        minutes = profile.get("schedule", {}).get("minutes", 15)
        interval = minutes * 60
        self.set_next(name, datetime.now() + timedelta(seconds=interval))

        def run():
            self.logger.log_signal.emit(f"▶ [{name}] started")
            while not stop.is_set():
                sync_one_way(
    profile["source"],
    profile["destination"],
    profile["delete_extras"],
    logger=lambda m: self.logger.log_signal.emit(f"[{name}] {m}"),
    stop_event=stop
)

                self.set_next(name, datetime.now() + timedelta(seconds=interval))
                for _ in range(interval):
                    if stop.is_set():
                        break
                    time.sleep(1)

            self.set_status(name, STATUS_STOPPED)
            self.set_next(name, "-")
            self.workers.pop(name, None)
            self.logger.log_signal.emit(f"🛑 [{name}] stopped")

        threading.Thread(target=run, daemon=True).start()

    # ---------------- STATUS ----------------
    def set_status(self, name, status):

    # save runtime status
     self.profile_status[name] = status

     for r in range(self.profile_table.rowCount()):
        if self.profile_table.item(r, 0).text() == name:
            self.profile_table.item(r, 1).setText(status)
    def set_next(self, name, dt):

     if isinstance(dt, datetime):
        txt = dt.strftime("%d-%b-%Y %H:%M:%S")
     else:
        txt = "-"

     self.next_run_times[name] = txt

     for r in range(self.profile_table.rowCount()):
        if self.profile_table.item(r, 0).text() == name:
            self.profile_table.item(r, 2).setText(txt)

    # ---------------- RUN / STOP ----------------
    def start_selected_profile(self):
        i = self.current_profile_index()
        if i >= 0:
            self.start_worker(self.cfg["profiles"][i])

    def start_all_profiles(self):
        for p in self.cfg["profiles"]:
            self.start_worker(p)

    def stop_selected_profile(self):
        i = self.current_profile_index()
        if i >= 0:
            name = self.cfg["profiles"][i]["name"]
            if name in self.workers:
                self.workers[name].set()

    def stop_all_profiles(self):
     for name, e in list(self.workers.items()):
        e.set()

     self.add_log("🛑 Stop requested for ALL profiles")

    def browse(self, edit):

     dialog = QFileDialog(self, "Select Folder")

    # Show folders only
     dialog.setFileMode(QFileDialog.Directory)

    # Do NOT use Qt's internal browser (important)
     dialog.setOption(QFileDialog.DontUseNativeDialog, False)

    # Start from "This PC" so all drives appear
     dialog.setDirectory("")

     if dialog.exec():
        path = dialog.selectedFiles()[0]
        edit.setText(path)


# ---------------- ENTRY ----------------
if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = SyncApp()
    win.show()
    sys.exit(app.exec())
