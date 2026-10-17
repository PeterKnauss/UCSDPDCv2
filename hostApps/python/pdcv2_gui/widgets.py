"""Reusable widgets: value editors, the main-page quick settings, the per-file config editor, the log view, the queue table"""
from __future__ import annotations
import re
import time
from pathlib import Path
from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMenu,
    QPlainTextEdit, QPushButton, QScrollArea, QTabWidget, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from . import yamlio as Y
from .jobs import ANSI, Job, JobQueue
from .workspace import Workspace

SCREAMER_METHODS = ["constant", "average", "percent", "medianFactor", "medianToMin"]
BAD_STYLE = "border: 1px solid #d9534f; background: rgba(217, 83, 79, 0.12);"


def options_for(ws: Workspace, fid: str, path: tuple) -> list[str] | None:
    """Choices for a text value: from its 'Type - a | b' comment, with fallbacks for keys that have no comment of their own"""
    if path[-1] == "spad_supply":
        return [""] + list(ws.files["hardware"].data.get("supplies", {}))
    if len(path) > 1 and path[-2] == "screamer" and path[-1] == "method":
        return SCREAMER_METHODS
    return ws.hint(fid, path)[1]


class ValueEditor(QWidget):
    """One editor for one config value. The widget follows the value's type: checkbox, choice, number, hex, text or YAML"""
    edited = Signal(object)

    def __init__(self, value, options: list[str] | None = None, browse: bool = False):
        super().__init__()
        self.kind = self._kind(value, options)
        self._orig = value
        self._busy = False
        self.base_tip = ""
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        if self.kind == "bool":
            self.w = QCheckBox()
            self.w.toggled.connect(lambda v: self._emit(bool(v)))
        elif self.kind == "enum":
            self.w = QComboBox()
            items = list(options)
            if str(value or "") not in items:
                items.append(str(value or ""))
            self.w.addItems(items)
            self.w.currentTextChanged.connect(lambda t: self._emit(t))
        else:
            self.w = QLineEdit()
            self.w.setPlaceholderText("(empty)" if value is None or value == "" else "")
            self.w.textEdited.connect(self._typed)
        lay.addWidget(self.w, 1)
        if browse:
            b = QToolButton(text="…")
            b.clicked.connect(self._browse)
            lay.addWidget(b)
        self.set_value(value)

    @staticmethod
    def _kind(value, options) -> str:
        if isinstance(value, bool):
            return "bool"
        if options and (value is None or isinstance(value, str)):
            return "enum"
        if Y.is_hex(value):
            return "hex"
        if isinstance(value, (int, float)):
            return "number"
        if value is None or isinstance(value, str):
            return "str"
        return "yaml"

    def set_value(self, value) -> None:
        self._busy = True
        if self.kind == "bool":
            self.w.setChecked(bool(value))
        elif self.kind == "enum":
            self.w.setCurrentText("" if value is None else str(value))
        else:
            text = self._show(value)
            if self.w.text() != text and not (self.w.hasFocus() and self._parse(self.w.text()) == (True, value)):
                self.w.setText(text)
        self._busy = False

    def _show(self, v) -> str:
        if self.kind == "hex":
            return f"0x{int(v):X}"
        if self.kind == "number":
            return repr(float(v)) if isinstance(v, float) else str(v)
        if self.kind == "yaml":
            return Y.flow_text(v)
        return "" if v is None else Y.escape_text(str(v))

    def _parse(self, text: str):
        try:
            if self.kind == "hex":
                return True, int(text, 0)
            if self.kind == "number":
                try:
                    return True, int(text)
                except ValueError:
                    v = float(text)
                    return (v == v and abs(v) != float("inf")), v
            if self.kind == "yaml":
                v = Y.loads(text)
                return isinstance(v, (CommentedMap, CommentedSeq)), v
            if self.kind == "str":
                if text == "":
                    return True, (None if self._orig is None else "")
                return True, (Y.loads(text) if self._orig is None and not isinstance(self._orig, str) else Y.unescape_text(text))
        except Exception:
            return False, None
        return False, None

    def _typed(self, text: str) -> None:
        ok, value = self._parse(text)
        self.w.setStyleSheet("" if ok else BAD_STYLE)
        if ok and not self._busy:
            self.edited.emit(value)

    def _emit(self, value) -> None:
        if not self._busy:
            self.edited.emit(value)

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose file", str(Path(self.w.text()).parent) if self.w.text() else "")
        if path:
            self.w.setText(path)
            self._typed(path)

    def set_problem(self, message: str | None) -> None:
        self.w.setStyleSheet(BAD_STYLE if message else "")
        self.setToolTip(f"{message}\n\n{self.base_tip}" if message else self.base_tip)


def is_path_key(key) -> bool:
    return str(key).endswith(("_file", "_dir")) or str(key) in ("tcr_file", "user_data_dir")


class QuickPanel(QWidget):
    """The main page's pinned settings. Pins are chosen in the Configs tab or removed from here with a right click"""
    modeChanged = Signal(str)
    customize = Signal()
    showInConfigs = Signal(str, tuple)

    def __init__(self, ws: Workspace):
        super().__init__()
        self.ws = ws
        self.editors: dict[tuple[str, str], ValueEditor] = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        top.addWidget(QLabel("Mode"))
        self.mode = QComboBox()
        self.mode.addItems(ws.modes)
        self.mode.currentTextChanged.connect(self._mode_changed)
        top.addWidget(self.mode, 1)
        outer.addLayout(top)
        self.scroll = QScrollArea(widgetResizable=True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        outer.addWidget(self.scroll, 1)
        self.footer = QPushButton("Choose pinned settings…")
        self.footer.clicked.connect(self.customize)
        outer.addWidget(self.footer)
        ws.valueChanged.connect(self._value_changed)
        ws.pinsChanged.connect(self.rebuild)
        ws.fileReloaded.connect(lambda _: self.rebuild())
        ws.dirtyChanged.connect(self.refresh_problems)
        self.rebuild()

    def _mode_changed(self, mode: str) -> None:
        self.rebuild()
        self.modeChanged.emit(mode)

    def rebuild(self) -> None:
        ws = self.ws
        self.editors.clear()
        body = QWidget()
        lay = QVBoxLayout(body)
        groups: dict[str, QFormLayout] = {}
        active = f"mode:{self.mode.currentText()}"
        for pin in ws.pins:
            path = ws.resolve(pin)
            if path is None or (pin.file.startswith("mode:") and pin.file != active):
                continue
            if pin.file not in groups:
                title = ws.files[pin.file].label + (" (active mode)" if pin.file.startswith("mode:") else "")
                box = QGroupBox(title)
                groups[pin.file] = QFormLayout(box)
                lay.addWidget(box)
            _, options, desc = ws.hint(pin.file, path)
            ed = ValueEditor(ws.get(pin.file, path), options_for(ws, pin.file, path), browse=is_path_key(path[-1]))
            ed.edited.connect(lambda v, f=pin.file, p=path: ws.set(f, p, v))
            key = ws.display_key(pin.file, path)
            label = QLabel(pin.label or key)
            tip = f"{key}\n{desc}" if desc else key
            ed.base_tip = tip
            for w in (label, ed):
                w.setToolTip(tip)
                w.setContextMenuPolicy(Qt.CustomContextMenu)
                w.customContextMenuRequested.connect(lambda pos, w=w, f=pin.file, p=path: self._menu(w, pos, f, p))
            groups[pin.file].addRow(label, ed)
            self.editors[(pin.file, Y.path_str(path))] = ed
        if not groups:
            lay.addWidget(QLabel("Nothing pinned yet. Tick 'Main' next to a setting in the Configs tab."))
        lay.addStretch(1)
        self.scroll.setWidget(body)
        self.refresh_problems()

    def _menu(self, widget, pos, fid: str, path: tuple) -> None:
        menu = QMenu(self)
        menu.addAction("Show in Configs tab", lambda: self.showInConfigs.emit(fid, path))
        pin = self.ws.find_pin(fid, path)
        menu.addAction("Move up", lambda: self.ws.move_pin(pin, -1))
        menu.addAction("Move down", lambda: self.ws.move_pin(pin, 1))
        menu.addSeparator()
        menu.addAction("Unpin from main page", lambda: self.ws.set_pinned(fid, path, False))
        menu.exec(widget.mapToGlobal(pos))

    def _value_changed(self, fid: str, path: tuple) -> None:
        ed = self.editors.get((fid, Y.path_str(path)))
        if ed:
            ed.set_value(self.ws.get(fid, path))
        self.refresh_problems()

    def refresh_problems(self) -> None:
        problems = self.ws.problems()
        for (fid, ptext), ed in self.editors.items():
            key = self.ws.display_key(fid, tuple(ptext.split(".")))
            ed.set_problem(problems.get((fid, key)))


class FileEditor(QWidget):
    """Form and raw-YAML editor for one config file"""
    def __init__(self, ws: Workspace, fid: str):
        super().__init__()
        self.ws, self.fid = ws, fid
        self.editors: dict[tuple, ValueEditor] = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self.tree = QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["Key", "Value", "Main", "Description"])
        self.tree.setUniformRowHeights(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.itemChanged.connect(self._pin_toggled)
        self.raw = QPlainTextEdit()
        self.raw.setFont(QFont("monospace"))
        self.raw.setLineWrapMode(QPlainTextEdit.NoWrap)
        raw_box = QWidget()
        rl = QVBoxLayout(raw_box)
        rl.addWidget(self.raw)
        row = QHBoxLayout()
        self.raw_msg = QLabel()
        apply = QPushButton("Apply raw text")
        apply.clicked.connect(self._apply_raw)
        row.addWidget(self.raw_msg, 1)
        row.addWidget(apply)
        rl.addLayout(row)
        self.tabs.addTab(self.tree, "Form")
        self.tabs.addTab(raw_box, "Raw YAML")
        self.tabs.currentChanged.connect(lambda i: self._load_raw() if i == 1 else None)
        lay.addWidget(self.tabs, 1)
        bar = QHBoxLayout()
        self.state = QLabel()
        save = QPushButton("Save file")
        save.clicked.connect(lambda: ws.save(fid))
        revert = QPushButton("Revert to saved")
        revert.clicked.connect(lambda: ws.revert(fid))
        bar.addWidget(QLabel(str(ws.files[fid].path)))
        bar.addStretch(1)
        bar.addWidget(self.state)
        bar.addWidget(revert)
        bar.addWidget(save)
        lay.addLayout(bar)
        ws.valueChanged.connect(self._value_changed)
        ws.fileReloaded.connect(lambda f: f == fid and self.build())
        ws.dirtyChanged.connect(self._dirty)
        ws.pinsChanged.connect(self._refresh_pins)
        self.build()

    def build(self) -> None:
        self.tree.blockSignals(True)
        self.tree.clear()
        self.editors.clear()
        self._fill(self.tree, self.ws.files[self.fid].data, ())
        self.tree.expandAll()
        self.tree.setColumnWidth(0, 250)
        self.tree.setColumnWidth(1, 300)
        self.tree.setColumnWidth(2, 50)
        self.tree.blockSignals(False)
        self._dirty()
        if self.tabs.currentIndex() == 1:
            self._load_raw()

    def _fill(self, parent, node, path: tuple) -> None:
        ws = self.ws
        for key, val in node.items():
            p = path + (key,)
            _, _, desc = Y.parse_hint(Y.comment_of(node, key))
            item = QTreeWidgetItem(parent, [str(key), "", "", desc])
            item.setData(0, Qt.UserRole, p)
            item.setToolTip(3, desc)
            item.setToolTip(0, ws.display_key(self.fid, p))
            if isinstance(val, CommentedMap):
                f = item.font(0)
                f.setBold(True)
                item.setFont(0, f)
                self._fill(item, val, p)
                continue
            ed = ValueEditor(val, options_for(ws, self.fid, p), browse=is_path_key(key))
            ed.edited.connect(lambda v, p=p: ws.set(self.fid, p, v))
            ed.setToolTip(desc)
            self.tree.setItemWidget(item, 1, ed)
            item.setSizeHint(1, QSize(0, 26))
            self.editors[p] = ed
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(2, Qt.Checked if ws.find_pin(self.fid, p) else Qt.Unchecked)

    def _pin_toggled(self, item: QTreeWidgetItem, col: int) -> None:
        if col == 2:
            self.ws.set_pinned(self.fid, item.data(0, Qt.UserRole), item.checkState(2) == Qt.Checked)

    def _refresh_pins(self) -> None:
        self.tree.blockSignals(True)
        for item in self._items():
            if item.childCount() == 0:
                p = item.data(0, Qt.UserRole)
                item.setCheckState(2, Qt.Checked if self.ws.find_pin(self.fid, p) else Qt.Unchecked)
        self.tree.blockSignals(False)

    def _items(self):
        stack = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        while stack:
            it = stack.pop()
            yield it
            stack += [it.child(i) for i in range(it.childCount())]

    def select(self, path: tuple) -> None:
        self.tabs.setCurrentIndex(0)
        for item in self._items():
            if item.data(0, Qt.UserRole) == path:
                self.tree.setCurrentItem(item)
                self.tree.scrollToItem(item)

    def _value_changed(self, fid: str, path: tuple) -> None:
        if fid == self.fid and path in self.editors:
            self.editors[path].set_value(self.ws.get(fid, path))

    def _dirty(self) -> None:
        self.state.setText("● unsaved changes" if self.ws.is_dirty(self.fid) else "saved")

    def _load_raw(self) -> None:
        self.raw.setPlainText(Y.dumps(self.ws.files[self.fid].data))
        self.raw_msg.setText("")

    def _apply_raw(self) -> None:
        try:
            self.ws.set_text(self.fid, self.raw.toPlainText())
            self.raw_msg.setText("Applied")
        except Exception as ex:
            self.raw_msg.setText(f"YAML error: {str(ex).splitlines()[0] if str(ex) else ex}")


# ------------------------------------------------------------------------ log
ANSI_COLORS = {30: "#6c757d", 31: "#ff6b6b", 32: "#6fd36f", 33: "#f0c05a", 34: "#6ea8fe", 35: "#d68cf0", 36: "#5fd3d3", 37: "#d8d8d8",
               90: "#8a8f94", 91: "#ff8787", 92: "#8ce68c", 93: "#ffd780", 94: "#8fbaff", 95: "#e0a9f5", 96: "#85e3e3", 97: "#ffffff"}
LEVEL_COLORS = {"info": "#d4d4d4", "warn": "#f0c05a", "error": "#ff6b6b", "gui": "#6ea8fe", "prompt": "#ffffff"}


class LogView(QWidget):
    """Combined log of every job and of the GUI, with level, job and text filters"""
    sendInput = Signal(str)

    def __init__(self):
        super().__init__()
        self.entries: list[tuple[float, str, str, str]] = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self.level = QComboBox()
        self.level.addItems(["All lines", "Warnings + errors", "Errors only"])
        self.job = QComboBox()
        self.job.addItem("All jobs", "")
        self.text = QLineEdit(placeholderText="Filter text")
        self.text.setClearButtonEnabled(True)
        self.follow = QCheckBox("Follow")
        self.follow.setChecked(True)
        clear = QPushButton("Clear")
        save = QPushButton("Save…")
        for w in (self.level, self.job):
            w.currentIndexChanged.connect(self.render)
        self.text.textChanged.connect(self.render)
        clear.clicked.connect(self._clear)
        save.clicked.connect(self._save)
        self.counts = QLabel()
        for w, s in ((QLabel("Log"), 0), (self.level, 0), (self.job, 0), (self.text, 1), (self.counts, 0), (self.follow, 0), (clear, 0), (save, 0)):
            bar.addWidget(w, s)
        lay.addLayout(bar)
        self.view = QPlainTextEdit(readOnly=True)
        self.view.setFont(QFont("monospace", 9))
        self.view.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.view.setMaximumBlockCount(60000)
        self.view.setStyleSheet("QPlainTextEdit { background: #1e1e1e; color: #d4d4d4; }")
        lay.addWidget(self.view, 1)
        row = QHBoxLayout()
        self.input = QLineEdit(placeholderText="Reply to a prompt from the running job (Enter sends)")
        self.input.setEnabled(False)
        self.input.returnPressed.connect(self._send)
        row.addWidget(self.input)
        lay.addLayout(row)
        self.n_err = self.n_warn = 0

    def set_running(self, running: bool) -> None:
        self.input.setEnabled(running)

    def add_job(self, job_id: str, label: str) -> None:
        if self.job.findData(job_id) < 0:
            self.job.addItem(label, job_id)

    def sync_jobs(self, jobs: list[Job]) -> None:
        keep = {j.id for j in jobs}
        for i in range(self.job.count() - 1, 0, -1):
            if self.job.itemData(i) not in keep:
                self.job.removeItem(i)
        for j in jobs:
            self.add_job(j.id, f"{j.id}  {j.run_folder or j.title}")

    def add(self, job_id: str, level: str, text: str) -> None:
        entry = (time.time(), job_id, level, text)
        self.entries.append(entry)
        self.n_err += level == "error"
        self.n_warn += level == "warn"
        self._counts()
        if self._passes(entry):
            self._write(entry)
            if level == "prompt":
                self.input.setFocus()

    def _counts(self) -> None:
        self.counts.setText(f"<span style='color:#d9534f'>{self.n_err} errors</span> · <span style='color:#c99a2e'>{self.n_warn} warnings</span>")

    def _passes(self, e) -> bool:
        _, job_id, level, text = e
        want = self.job.currentData()
        if want and job_id not in (want, ""):
            return False
        mode = self.level.currentIndex()
        if mode == 1 and level not in ("warn", "error", "gui", "prompt"):
            return False
        if mode == 2 and level not in ("error", "prompt"):
            return False
        q = self.text.text().lower()
        return not q or q in ANSI.sub("", text).lower()

    def render(self) -> None:
        self.view.clear()
        for e in self.entries:
            if self._passes(e):
                self._write(e, scroll=False)
        self.view.moveCursor(QTextCursor.End)

    def _write(self, entry, scroll: bool = True) -> None:
        t, job_id, level, text = entry
        cur = self.view.textCursor()
        cur.movePosition(QTextCursor.End)
        stamp = QTextCharFormat()
        stamp.setForeground(QColor("#7f848e"))
        cur.insertText(f"{time.strftime('%H:%M:%S', time.localtime(t))} {job_id or '--------'}  ", stamp)
        base = QColor(LEVEL_COLORS[level])
        fmt = QTextCharFormat()
        fmt.setForeground(base)
        if level in ("error", "prompt"):
            fmt.setFontWeight(QFont.Bold)
        pos = 0
        for m in ANSI.finditer(text):
            if m.start() > pos:
                cur.insertText(text[pos:m.start()], fmt)
            pos = m.end()
            if level == "info" and m[0].endswith("m"):
                for code in (int(c) for c in m[0][2:-1].split(";") if c.isdigit()):
                    if code == 0:
                        fmt.setForeground(base)
                    elif code in ANSI_COLORS:
                        fmt.setForeground(QColor(ANSI_COLORS[code]))
        cur.insertText(text[pos:] + "\n", fmt)
        if scroll and self.follow.isChecked():
            self.view.moveCursor(QTextCursor.End)

    def _send(self) -> None:
        self.sendInput.emit(self.input.text())
        self.input.clear()

    def _clear(self) -> None:
        self.entries.clear()
        self.n_err = self.n_warn = 0
        self._counts()
        self.view.clear()

    def _save(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save log", "pdc_log.txt")
        if path:
            lines = [f"{time.strftime('%H:%M:%S', time.localtime(t))} {j or '--------'} [{lv}] {ANSI.sub('', tx)}" for t, j, lv, tx in self.entries if self._passes((t, j, lv, tx))]
            Path(path).write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------- queue
STATUS_COLORS = {"queued": "#8a8f94", "running": "#2f7de1", "done": "#2e9e5b", "failed": "#d9534f", "stopped": "#d98a2b", "skipped": "#8a8f94"}
COLUMNS = ["", "#", "Status", "Mode", "Run folder", "Settings", "Time", "Issues"]


def fmt_time(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


class QueueModel(QAbstractTableModel):
    def __init__(self, queue: JobQueue):
        super().__init__()
        self.q = queue
        self._ids: list[str] = []
        queue.changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        ids = [j.id for j in self.q.jobs]
        if ids != self._ids:
            self.beginResetModel()
            self._ids = ids
            self.endResetModel()
        elif ids:
            self.dataChanged.emit(self.index(0, 0), self.index(len(ids) - 1, len(COLUMNS) - 1))

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.q.jobs)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return COLUMNS[section]

    def flags(self, index):
        f = super().flags(index)
        return f | Qt.ItemIsUserCheckable if index.column() == 0 else f

    def data(self, index, role=Qt.DisplayRole):
        j = self.q.jobs[index.row()]
        c = index.column()
        if role == Qt.CheckStateRole and c == 0:
            return Qt.Checked if j.enabled else Qt.Unchecked
        if role == Qt.DisplayRole:
            if c == 1:
                return index.row() + 1
            if c == 2:
                return j.status + (f" {j.progress}%" if j.status == "running" and j.progress >= 0 else "")
            if c == 3:
                return j.title
            if c == 4:
                return j.run_folder
            if c == 5:
                return j.summary
            if c == 6:
                return fmt_time(j.duration) if j.started else ""
            if c == 7:
                return " ".join(x for x in (f"{j.errors} err" if j.errors else "", f"{j.warnings} warn" if j.warnings else "") if x)
        if role == Qt.ForegroundRole:
            if c == 2:
                return QBrush(QColor(STATUS_COLORS.get(j.status, "#888")))
            if c == 7 and j.errors:
                return QBrush(QColor("#d9534f"))
            if not j.enabled:
                return QBrush(QColor("#999"))
        if role == Qt.FontRole and c == 2 and j.status == "running":
            f = QFont()
            f.setBold(True)
            return f
        if role == Qt.ToolTipRole:
            return f"{j.command_text}\n\n{j.details}".strip()

    def setData(self, index, value, role=Qt.EditRole) -> bool:
        if role == Qt.CheckStateRole and index.column() == 0:
            self.q.set_enabled(self.q.jobs[index.row()].id, value == Qt.Checked or value == 2)
            return True
        return False
