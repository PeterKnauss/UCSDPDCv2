"""Dialogs: parameter sweep, custom script job, settings"""
from __future__ import annotations
import itertools
import json
import re
import shlex
import sys
from pathlib import Path
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout,
)
from .jobs import HOME
from .workspace import Workspace

SETTINGS_FILE = HOME / "settings.json"
DEFAULT_SETTINGS = {"python": sys.executable, "on_error": "stop", "gap_s": 0.0, "unattended": True}
_RANGE = re.compile(r"^\s*([-+]?[\d.eE+-]+)\s*:\s*([-+]?[\d.eE+-]+)\s*:\s*([-+]?[\d.eE+-]+)\s*$")


def load_settings() -> dict:
    try:
        return {**DEFAULT_SETTINGS, **json.loads(SETTINGS_FILE.read_text())}
    except (OSError, ValueError):
        return dict(DEFAULT_SETTINGS)

def save_settings(settings: dict) -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(settings, indent=1))


def scalar(text: str):
    t = text.strip()
    for cast in (int, float):
        try:
            return cast(t)
        except ValueError:
            pass
    return {"true": True, "false": False, "null": None, "none": None}.get(t.lower(), t)

def _num(v) -> str:
    return f"{v:g}" if isinstance(v, float) else str(v)

def parse_values(text: str) -> list:
    """'21, 21.5, 22' or a range 'start:stop:step' (stop included). Anything else is text"""
    out = []
    for tok in (t for t in text.split(",") if t.strip()):
        m = _RANGE.match(tok)
        if m:
            a, b, step = (float(x) for x in m.groups())
            if step == 0 or (b - a) * step < 0:
                raise ValueError(f"bad range {tok.strip()!r}")
            n = int((b - a) / step + 1e-9) + 1
            ints = not any(c in tok for c in ".eE")
            out += [int(a + i * step) if ints else round(a + i * step, 10) for i in range(n)]
        else:
            out.append(scalar(tok))
    return out


class SweepDialog(QDialog):
    """Builds one job per value (or per combination of values of two keys) of a setting. Replaces hand-written batch loops"""
    def __init__(self, ws: Workspace, mode: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add sweep")
        self.resize(640, 520)
        base = str(ws.files["run"].data.get("run", {}).get("run_folder") or "run")
        keys = ws.override_keys(mode)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("One job is queued for every value. Each job runs with the settings now on screen plus these overrides."))
        form = QFormLayout()
        self.k1, self.v1 = self._key_combo(keys, "run.supply_V.keysight"), QLineEdit("21, 21.5, 22")
        self.k2, self.v2 = self._key_combo(["(none)"] + keys, "(none)"), QLineEdit()
        self.template = QLineEdit("{base}_{k1}")
        self.base = base
        self.v1.setToolTip("Comma separated values, or start:stop:step (stop included), such as 21:22.5:0.5")
        form.addRow("Setting", self.k1)
        form.addRow("Values", self.v1)
        form.addRow("Second setting (grid)", self.k2)
        form.addRow("Values", self.v2)
        form.addRow("Run folder", self.template)
        lay.addLayout(form)
        lay.addWidget(QLabel("Run folder tokens: {base} current run folder, {k1} {k2} the values, {i} job number"))
        self.preview = QPlainTextEdit(readOnly=True)
        lay.addWidget(self.preview, 1)
        self.box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.box.accepted.connect(self.accept)
        self.box.rejected.connect(self.reject)
        lay.addWidget(self.box)
        for w in (self.v1, self.v2, self.template):
            w.textChanged.connect(self._update)
        for w in (self.k1, self.k2):
            w.currentTextChanged.connect(self._update)
        self._update()

    @staticmethod
    def _key_combo(keys, current):
        c = QComboBox(editable=True)
        c.addItems(keys)
        c.setCurrentText(current)
        c.setInsertPolicy(QComboBox.NoInsert)
        return c

    def jobs(self) -> list[tuple[dict, str]]:
        """List of (overrides, run folder)"""
        k1, k2 = self.k1.currentText().strip(), self.k2.currentText().strip()
        vals1 = parse_values(self.v1.text())
        vals2 = parse_values(self.v2.text()) if k2 not in ("", "(none)") else [None]
        out = []
        for i, (a, b) in enumerate(itertools.product(vals1, vals2), 1):
            folder = self.template.text().replace("{base}", self.base).replace("{k1}", _num(a)).replace("{k2}", _num(b)).replace("{i}", str(i))
            over = {k1: a, "run.run_folder": folder}
            if b is not None:
                over[k2] = b
            out.append((over, folder))
        return out

    def _update(self) -> None:
        try:
            jobs = self.jobs()
            names = [f for _, f in jobs]
            problem = "" if len(set(names)) == len(names) else "Run folders repeat: add {k1} (and {k2}) or {i} to the template.\n\n"
            self.preview.setPlainText(problem + f"{len(jobs)} job(s)\n\n" + "\n".join(
                f"{i}. {f}   " + ", ".join(f"{k}={v}" for k, v in o.items() if k != "run.run_folder") for i, (o, f) in enumerate(jobs, 1)))
            self.box.button(QDialogButtonBox.Ok).setEnabled(bool(jobs) and not problem)
        except ValueError as ex:
            self.preview.setPlainText(str(ex))
            self.box.button(QDialogButtonBox.Ok).setEnabled(False)


class CustomJobDialog(QDialog):
    """A job that runs any script of the python folder with arguments, such as validatePDCCommunication.py or run_tcr_batch.py"""
    def __init__(self, folder: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add script job")
        self.resize(520, 160)
        form = QFormLayout(self)
        self.script = QComboBox(editable=True)
        self.script.addItems(sorted(p.name for p in folder.glob("*.py")))
        browse = QPushButton("Browse…")
        browse.clicked.connect(lambda: (lambda p: p and self.script.setCurrentText(p))(QFileDialog.getOpenFileName(self, "Script", str(folder), "Python (*.py)")[0]))
        row = QHBoxLayout()
        row.addWidget(self.script, 1)
        row.addWidget(browse)
        self.args = QLineEdit()
        self.args.setPlaceholderText("arguments, e.g. run.head_id=48 --batch")
        form.addRow("Script", row)
        form.addRow("Arguments", self.args)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        form.addRow(box)

    def command(self) -> list[str]:
        return [self.script.currentText().strip(), *shlex.split(self.args.text())]


class SettingsDialog(QDialog):
    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(560, 220)
        form = QFormLayout(self)
        self.python = QLineEdit(settings["python"])
        self.python.setToolTip("Interpreter that runs the scripts, such as ~/venv_pdcv2/bin/python")
        self.on_error = QComboBox()
        self.on_error.addItems(["stop", "continue"])
        self.on_error.setCurrentText(settings["on_error"])
        self.gap = QDoubleSpinBox(maximum=3600, suffix=" s", value=settings["gap_s"])
        self.unattended = QCheckBox("Add --batch to queued mode jobs (no prompts, no figure windows)")
        self.unattended.setChecked(settings["unattended"])
        form.addRow("Python interpreter", self.python)
        form.addRow("When a job fails", self.on_error)
        form.addRow("Pause between jobs", self.gap)
        form.addRow("", self.unattended)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        form.addRow(box)

    def values(self) -> dict:
        return {"python": self.python.text().strip() or sys.executable, "on_error": self.on_error.currentText(),
                "gap_s": self.gap.value(), "unattended": self.unattended.isChecked()}
