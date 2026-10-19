"""Main window: quick settings, queue and log on the first page, every config file on the second"""
from __future__ import annotations
import shutil
from pathlib import Path
from PySide6.QtCore import QFileSystemWatcher, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QListWidget, QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton, QSplitter,
    QStackedWidget, QTableView, QTabWidget, QToolBar, QToolButton, QVBoxLayout, QWidget,
)
from pdcv2_helpers.paths import run_folder_name
from .dialogs import CustomJobDialog, SettingsDialog, SweepDialog, save_settings
from .jobs import JOBS_DIR, Job, JobQueue, preflight
from .widgets import FileEditor, LogView, QueueModel, QuickPanel, fmt_time
from .workspace import Workspace

PY_DIR = Path(__file__).resolve().parent.parent


class MainWindow(QMainWindow):
    def __init__(self, ws: Workspace, queue: JobQueue, settings: dict):
        super().__init__()
        self.ws, self.queue, self.settings = ws, queue, settings
        self.resize(1480, 940)
        self._build()
        self._wire()
        self._apply_settings()
        self._watch()
        self._refresh_state()

    # ------------------------------------------------------------------ UI
    def _build(self) -> None:
        ws, q = self.ws, self.queue
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        # toolbar
        tb = QToolBar("Run")
        tb.setMovable(False)
        self.addToolBar(tb)
        self.act_run = QAction("▶ Run queue", self, shortcut="F5", toolTip="Run the queued jobs one after another")
        self.act_pause = QAction("⏸ Pause after current", self, checkable=True, toolTip="Finish the running job, then wait")
        self.act_stop = QAction("■ Stop", self, shortcut="Ctrl+.", toolTip="Interrupt the running job (supplies are ramped down) and stop the queue")
        self.act_kill = QAction("✖ Force kill…", self, toolTip="Last resort. Supplies are NOT ramped down")
        self.act_validate = QAction("✔ Check config", self, shortcut="Ctrl+K", toolTip="Run the script's own --show-config on the settings on screen")
        self.act_save = QAction("💾 Save configs", self, shortcut=QKeySequence.Save, toolTip="Write the edited config files to disk")
        self.act_settings = QAction("⚙ Settings", self)
        for a in (self.act_run, self.act_pause, self.act_stop, self.act_kill):
            tb.addAction(a)
        tb.addSeparator()
        for a in (self.act_validate, self.act_save):
            tb.addAction(a)
        tb.addSeparator()
        tb.addAction(self.act_settings)

        # main page
        main = QWidget()
        ml = QVBoxLayout(main)
        ml.setContentsMargins(6, 6, 6, 6)
        top = QSplitter(Qt.Horizontal)
        self.quick = QuickPanel(ws)
        top.addWidget(self.quick)
        top.addWidget(self._queue_panel())
        top.setSizes([430, 900])
        vert = QSplitter(Qt.Vertical)
        vert.addWidget(top)
        vert.addWidget(self._log_panel())
        vert.setSizes([520, 380])
        ml.addWidget(vert)
        self.tabs.addTab(main, "Main")

        # config page
        cfg = QWidget()
        cl = QHBoxLayout(cfg)
        self.file_list = QListWidget()
        self.file_list.setMaximumWidth(210)
        self.stack = QStackedWidget()
        self.editors: dict[str, FileEditor] = {}
        for fid, f in ws.files.items():
            self.file_list.addItem(f.label)
            self.editors[fid] = FileEditor(ws, fid)
            self.stack.addWidget(self.editors[fid])
        self.file_list.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.file_list.setCurrentRow(0)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(QLabel("Config files"))
        ll.addWidget(self.file_list, 1)
        ll.addWidget(QLabel("Tick Main to show a setting\non the main page."))
        cl.addWidget(left)
        cl.addWidget(self.stack, 1)
        self.tabs.addTab(cfg, "Configs")
        self.status = self.statusBar()

    def _queue_panel(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("<b>Queue</b>"))
        self.add_btn = QToolButton(text="＋ Add current settings", popupMode=QToolButton.MenuButtonPopup)
        self.add_btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
        menu = QMenu(self)
        menu.addAction("Add current settings", self.add_current)
        menu.addAction("Add sweep…", self.add_sweep)
        menu.addAction("Add script job…", self.add_custom)
        self.add_btn.setMenu(menu)
        self.add_btn.clicked.connect(self.add_current)
        bar.addWidget(self.add_btn)
        self.btns = {}
        for name, tip, fn in (("▲", "Move up", lambda: self._move(-1)), ("▼", "Move down", lambda: self._move(1)),
                              ("Duplicate", "Copy the selected job with its settings", self._duplicate),
                              ("Re-queue", "Run the selected finished job again", self._requeue),
                              ("Load settings", "Put the selected job's settings back on screen", self._load_job),
                              ("Remove", "Remove the selected jobs", self._remove),
                              ("Clear finished", "Remove done, failed and stopped jobs", lambda: self.queue.clear_finished())):
            b = QPushButton(name, toolTip=tip)
            b.clicked.connect(fn)
            bar.addWidget(b)
            self.btns[name] = b
        bar.addStretch(1)
        lay.addLayout(bar)
        self.model = QueueModel(self.queue)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setSelectionMode(QTableView.ExtendedSelection)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setStretchLastSection(True)
        for i, width in enumerate((28, 30, 110, 130, 230, 260, 60, 80)):
            self.table.setColumnWidth(i, width)
        self.table.selectionModel().selectionChanged.connect(self._selection_changed)
        lay.addWidget(self.table, 1)
        self.queue_info = QLabel()
        lay.addWidget(self.queue_info)
        return w

    def _log_panel(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.now = QLabel("Idle")
        self.now.setMinimumWidth(300)
        self.bar = QProgressBar()
        self.bar.setTextVisible(True)
        self.bar.setMaximumHeight(16)
        self.live = QLabel()
        self.live.setStyleSheet("color: gray;")
        self.elapsed = QLabel()
        row.addWidget(self.now)
        row.addWidget(self.bar, 1)
        row.addWidget(self.elapsed)
        lay.addLayout(row)
        lay.addWidget(self.live)
        self.log = LogView()
        lay.addWidget(self.log, 1)
        return w

    # ---------------------------------------------------------------- wiring
    def _wire(self) -> None:
        q, ws = self.queue, self.ws
        self.act_run.triggered.connect(q.start)
        self.act_pause.toggled.connect(lambda on: setattr(q, "pause_after", on))
        self.act_stop.triggered.connect(q.stop)
        self.act_kill.triggered.connect(self._force_kill)
        self.act_validate.triggered.connect(self.validate)
        self.act_save.triggered.connect(self.save_all)
        self.act_settings.triggered.connect(self._settings)
        q.line.connect(self.log.add)
        q.progress.connect(self._progress)
        q.state.connect(lambda _: self._refresh_state())
        q.changed.connect(self._refresh_state)
        q.stuck.connect(lambda jid: self.log.add(jid, "error", "The job has not exited 60 s after the interrupt. Wait for the supplies to ramp down, or use Force kill."))
        self.log.sendInput.connect(q.send_input)
        ws.dirtyChanged.connect(self._dirty)
        self.quick.customize.connect(lambda: self.tabs.setCurrentIndex(1))
        self.quick.showInConfigs.connect(self._show_in_configs)
        self.clock = QTimer(self, interval=1000)
        self.clock.timeout.connect(self._tick)
        self.clock.start()
        self.log.sync_jobs(q.jobs)
        q.changed.connect(lambda: self.log.sync_jobs(q.jobs))

    def _apply_settings(self) -> None:
        self.queue.on_error = self.settings["on_error"]
        self.queue.gap_s = self.settings["gap_s"]

    def _settings(self) -> None:
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec():
            self.settings.update(dlg.values())
            save_settings(self.settings)
            self._apply_settings()

    def _watch(self) -> None:
        self.watcher = QFileSystemWatcher([str(f.path) for f in self.ws.files.values()])
        self._debounce = QTimer(self, singleShot=True, interval=400)
        self._debounce.timeout.connect(self._disk_changed)
        self.watcher.fileChanged.connect(lambda _: self._debounce.start())

    def _disk_changed(self) -> None:
        for fid, f in self.ws.files.items():
            if str(f.path) not in self.watcher.files():
                self.watcher.addPath(str(f.path))
            if f.path.is_file() and self.ws.changed_on_disk(fid):
                if f.dirty:
                    self.log.add("", "warn", f"{f.path.name} changed on disk while it has unsaved edits here. Save overwrites it, Revert loads it.")
                else:
                    self.ws.revert(fid)
                    self.log.add("", "gui", f"{f.path.name} changed on disk: reloaded")

    # --------------------------------------------------------------- actions
    @property
    def mode(self) -> str:
        return self.quick.mode.currentText()

    def _build_job(self, overrides: dict | None = None) -> Job | None:
        mode, script, py = self.mode, self.ws.script_for(self.mode), self.settings["python"]
        job = Job(title=mode, cmd=[], cwd=str(PY_DIR), mode=mode)
        snap = JOBS_DIR / job.id / "configs"
        data = self.ws.snapshot(snap, mode, overrides)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            ok, message = preflight(py, script, job.cwd, snap)
        finally:
            QApplication.restoreOverrideCursor()
        if not ok:
            self.log.add("", "error", f"Config check failed for {mode}:")
            for line in message.splitlines():
                self.log.add("", "error", line)
            if QMessageBox.question(self, "Config problems", f"{message}\n\nQueue this job anyway?") != QMessageBox.Yes:
                shutil.rmtree(JOBS_DIR / job.id, ignore_errors=True)
                return None
        run, pixels = data["run"]["run"], data["run"].get("pixels", {})
        spad, volts = run.get("spad_supply"), run.get("supply_V") or {}
        meas = data["run"]["tcr"]["meas_time_s"] if mode == "tcr" else run.get("meas_time_s")
        try:
            job.run_folder = run_folder_name(self.ws.config(mode, data))
        except ValueError:
            job.run_folder = str(run.get("run_folder") or "")
        job.summary = " · ".join(x for x in (f"head {run.get('head_id')}", f"{spad} {volts.get(spad)} V" if spad else "", f"{meas} s") if x)
        diff = self.ws.diff_vs_saved(data)
        job.details = ("Differs from the saved files:\n" + "\n".join(diff)) if diff else "Same as the saved files"
        job.snapshot = str(snap)
        job.cmd = [py, script] + (["--batch"] if self.settings["unattended"] else []) + ["--config-dir", str(snap)]
        return job

    def add_current(self) -> None:
        job = self._build_job()
        if job:
            self.queue.add(job)
            self.log.add(job.id, "gui", f"Queued {job.title}: {job.run_folder}")

    def add_sweep(self) -> None:
        dlg = SweepDialog(self.ws, self.mode, self)
        if not dlg.exec():
            return
        made = 0
        for overrides, folder in dlg.jobs():
            job = self._build_job(overrides)
            if job is None:
                break
            sweep = ", ".join(f"{k}={v}" for k, v in overrides.items() if k != "run.run_folder")
            job.summary = f"{sweep} · {job.summary}"
            self.queue.add(job)
            made += 1
        self.log.add("", "gui", f"Queued {made} sweep job(s)")

    def add_custom(self) -> None:
        dlg = CustomJobDialog(PY_DIR, self)
        if dlg.exec() and dlg.command()[0]:
            cmd = dlg.command()
            self.queue.add(Job(title=Path(cmd[0]).stem, cmd=[self.settings["python"], *cmd], cwd=str(PY_DIR), summary=" ".join(cmd[1:])))

    def validate(self) -> None:
        job = self._build_job()
        if job:
            self.log.add("", "gui", f"Config check passed for {self.mode}")
            shutil.rmtree(JOBS_DIR / job.id, ignore_errors=True)

    def save_all(self) -> None:
        ids = self.ws.save_all()
        self.log.add("", "gui", f"Saved: {', '.join(self.ws.files[i].path.name for i in ids)}" if ids else "No unsaved changes")

    def _selected_ids(self) -> list[str]:
        return [self.queue.jobs[i.row()].id for i in self.table.selectionModel().selectedRows()]

    def _select(self, job_id: str) -> None:
        row = self.queue.index(job_id)
        self.table.selectRow(row)

    def _move(self, delta: int) -> None:
        ids = self._selected_ids()
        if len(ids) == 1:
            self.queue.move(ids[0], delta)
            self._select(ids[0])

    def _duplicate(self) -> None:
        for jid in self._selected_ids()[:1]:
            self.queue.duplicate(jid)

    def _requeue(self) -> None:
        for jid in self._selected_ids():
            self.queue.requeue(jid)

    def _remove(self) -> None:
        self.queue.remove(self._selected_ids())

    def _load_job(self) -> None:
        for jid in self._selected_ids()[:1]:
            job = self.queue.job(jid)
            if job.snapshot and Path(job.snapshot).is_dir():
                if self.ws.is_dirty() and QMessageBox.question(self, "Load settings", "Replace the unsaved settings on screen?") != QMessageBox.Yes:
                    return
                self.ws.adopt(Path(job.snapshot))
                if job.mode in self.ws.modes:
                    self.quick.mode.setCurrentText(job.mode)
                self.log.add(jid, "gui", "Settings of this job loaded on screen (not saved to the files)")

    def _force_kill(self) -> None:
        if self.queue.running and QMessageBox.warning(
                self, "Force kill", "The script gets no chance to ramp the supplies down.\nCheck the supplies yourself afterwards.\n\nKill the job?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
            self.queue.kill()

    def _show_in_configs(self, fid: str, path: tuple) -> None:
        self.tabs.setCurrentIndex(1)
        self.file_list.setCurrentRow(list(self.ws.files).index(fid))
        self.editors[fid].select(path)

    # ---------------------------------------------------------------- state
    def _selection_changed(self) -> None:
        ids = self._selected_ids()
        if len(ids) == 1:
            i = self.log.job.findData(ids[0])
            if i >= 0 and self.log.job.currentIndex() > 0:
                self.log.job.setCurrentIndex(i)

    def _progress(self, job_id: str, percent: int, text: str) -> None:
        if self.queue.current and self.queue.current.id == job_id:
            self.bar.setRange(0, 100 if percent >= 0 else 0)
            self.bar.setValue(max(percent, 0))
            self.live.setText(text[:200])

    def _dirty(self) -> None:
        dirty = self.ws.dirty_ids()
        self.setWindowTitle("PDCv2 Control" + (" *" if dirty else ""))
        for i, (fid, f) in enumerate(self.ws.files.items()):
            self.file_list.item(i).setText(("● " if fid in dirty else "") + f.label)
        self.act_save.setEnabled(bool(dirty))

    def _refresh_state(self) -> None:
        q = self.queue
        running = q.running
        todo = len(q.pending())
        self.act_run.setEnabled(not running and todo > 0)
        self.act_stop.setEnabled(running)
        self.act_kill.setEnabled(running)
        self.act_pause.setEnabled(running)
        if not running:
            self.act_pause.setChecked(False)
        self.log.set_running(running)
        cur = q.current
        self.now.setText(f"<b>Running</b> {cur.id}  {cur.title}  {cur.run_folder}" if cur else "Idle")
        if not cur:
            self.bar.setRange(0, 100)
            self.bar.setValue(0)
            self.live.setText("")
            self.elapsed.setText("")
        counts = {s: sum(j.status == s for j in q.jobs) for s in ("queued", "running", "done", "failed", "stopped")}
        self.queue_info.setText("  ·  ".join(f"{n} {s}" for s, n in counts.items() if n) or "Queue is empty")
        self._dirty()

    def _tick(self) -> None:
        cur = self.queue.current
        if cur:
            self.elapsed.setText(fmt_time(cur.duration))
            self.model.refresh()

    def closeEvent(self, event) -> None:
        if self.queue.running and QMessageBox.question(self, "Quit", "A job is running. Closing the window leaves it running without a log here.\n\nQuit anyway?") != QMessageBox.Yes:
            return event.ignore()
        if self.ws.is_dirty():
            box = QMessageBox.question(self, "Unsaved settings", "Save the edited config files before quitting?",
                                       QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
            if box == QMessageBox.Cancel:
                return event.ignore()
            if box == QMessageBox.Save:
                self.ws.save_all()
        event.accept()
