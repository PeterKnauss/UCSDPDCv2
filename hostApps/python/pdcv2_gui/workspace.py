"""
Working copy of the config files.

Edits happen on an in-memory copy of the YAML files. Saving writes them to disk. A queued job takes a snapshot of the
working copy (a full configs folder passed to the script with --config-dir), so a job always runs with the values that
were on screen when it was queued, whatever is edited or saved afterwards.
"""
from __future__ import annotations
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
import yaml
from PySide6.QtCore import QObject, Signal
from pdcv2_helpers.config import Config, ConfigError, deep_merge, validate
from . import yamlio as Y

RUN_SECTIONS = ("run", "pixels", "tcr", "dsum")
_KEY = re.compile(r"^'?((?:run|pixels|tcr|dsum|hardware|behavior|pdc|controller)(?:\.\w+)+)")   # the key a validate() problem starts with
MODE_ORDER = ("tcr", "dsum_rad", "dsum_coincidence")
DEFAULT_PINS = [
    ("run", "run.run_folder", "Run folder"),
    ("run", "run.head_id", "Head ID"),
    ("run", "run.supply_V.keysight", "Keysight V"),
    ("run", "run.supply_V.bk", "BK V"),
    ("run", "run.meas_time_s", "DSUM meas time (s)"),
    ("run", "run.pdc_enable", "PDC enable mask"),
    ("run", "run.n_spad", "SPADs per PDC"),
    ("run", "run.name", "Name suffix"),
    ("run", "run.save_plot", "Save plot"),
    ("run", "pixels.source", "Pixel source"),
    ("run", "pixels.tcr_file", "TCR file"),
    ("run", "tcr.meas_time_s", "TCR meas time (s)"),
    ("mode:*", "behavior.power_supplies", "Ramp supplies automatically"),
]


@dataclass
class ConfigFile:
    id: str
    label: str
    group: str
    path: Path
    data: object = None
    saved_text: str = ""

    @property
    def dirty(self) -> bool:
        return Y.dumps(self.data) != self.saved_text

    def read(self) -> None:
        text = self.path.read_text()
        self.data = Y.loads(text)
        self.saved_text = Y.dumps(self.data)


@dataclass
class Pin:
    file: str
    path: str
    label: str = ""


class Workspace(QObject):
    valueChanged = Signal(str, tuple)
    fileReloaded = Signal(str)
    dirtyChanged = Signal()
    pinsChanged = Signal()

    def __init__(self, config_dir: Path):
        super().__init__()
        self.dir = Path(config_dir)
        self.files: dict[str, ConfigFile] = {}
        self.pins: list[Pin] = []
        self._discover()
        self._load_pins()

    # ---------------------------------------------------------------- files
    def _discover(self) -> None:
        def add(fid, label, group, rel):
            p = self.dir / rel
            if p.is_file():
                f = ConfigFile(fid, label, group, p)
                f.read()
                self.files[fid] = f
        add("run", "Run", "run", "run.yaml")
        add("hardware", "Hardware", "hardware", "hardware.yaml")
        for p in sorted((self.dir / "modes").glob("*.yaml")):
            add(f"mode:{p.stem}", f"Mode: {p.stem}", "mode", f"modes/{p.name}")
        for p in sorted((self.dir / "supplies").glob("*.yaml")):
            add(f"supply:{p.stem}", f"Supply: {p.stem}", "supply", f"supplies/{p.name}")

    @property
    def modes(self) -> list[str]:
        found = [f[5:] for f in self.files if f.startswith("mode:")]
        return sorted(found, key=lambda m: (MODE_ORDER.index(m) if m in MODE_ORDER else len(MODE_ORDER), m))

    def script_for(self, mode: str) -> str:
        return f"run_{mode}.py"

    def is_dirty(self, fid: str | None = None) -> bool:
        return any(f.dirty for f in self.files.values()) if fid is None else self.files[fid].dirty

    def dirty_ids(self) -> list[str]:
        return [fid for fid, f in self.files.items() if f.dirty]

    def save(self, fid: str) -> None:
        f = self.files[fid]
        Y.save(f.data, f.path)
        f.saved_text = Y.dumps(f.data)
        self.dirtyChanged.emit()

    def save_all(self) -> list[str]:
        ids = self.dirty_ids()
        for fid in ids:
            self.save(fid)
        return ids

    def revert(self, fid: str) -> None:
        self.files[fid].read()
        self.fileReloaded.emit(fid)
        self.dirtyChanged.emit()

    def set_text(self, fid: str, text: str) -> None:
        """Replaces a whole file with parsed text. Raises on a YAML error"""
        self.files[fid].data = Y.loads(text)
        self.fileReloaded.emit(fid)
        self.dirtyChanged.emit()

    def changed_on_disk(self, fid: str) -> bool:
        f = self.files[fid]
        return f.path.is_file() and Y.dumps(Y.loads(f.path.read_text())) != f.saved_text

    # --------------------------------------------------------------- values
    def get(self, fid: str, path: tuple):
        return Y.get_in(self.files[fid].data, path)

    def parent_and_key(self, fid: str, path: tuple):
        return Y.get_in(self.files[fid].data, path[:-1]), path[-1]

    def set(self, fid: str, path: tuple, value) -> bool:
        parent, key = self.parent_and_key(fid, path)
        old = parent[key]
        if old == value and isinstance(old, bool) == isinstance(value, bool):
            return False
        parent[key] = Y.assign(old, value)
        self.valueChanged.emit(fid, path)
        self.dirtyChanged.emit()
        return True

    def hint(self, fid: str, path: tuple) -> tuple[str, list[str] | None, str]:
        parent, key = self.parent_and_key(fid, path)
        return Y.parse_hint(Y.comment_of(parent, key))

    def display_key(self, fid: str, path: tuple) -> str:
        return ("hardware." if fid == "hardware" else "") + Y.path_str(path)

    def leaves(self, fid: str):
        return list(Y.walk(self.files[fid].data))

    def config(self, mode: str, data: dict | None = None) -> Config:
        """The config the script loads from these files: the working copy, or the files in data (by file id)"""
        def plain(fid):
            node = (data or {}).get(fid, self.files[fid].data) if fid in self.files else None
            return (yaml.safe_load(Y.dumps(node)) or {}) if node is not None else {}
        merged = deep_merge(deep_merge({"hardware": plain("hardware")}, plain(f"mode:{mode}")), plain("run"))
        for c in merged["hardware"].get("supplies", {}).values():
            if f"supply:{c.get('model')}" in self.files:
                c["profile"] = plain(f"supply:{c.get('model')}")
        cfg = Config(merged)
        cfg.mode = mode
        return cfg

    def problems(self, mode: str) -> dict[tuple[str, str], str]:
        """The script's own validate() on the settings on screen. Returns the problem of each key, by (file id, key)"""
        try:
            validate(self.config(mode))
        except ConfigError as ex:
            found = ex.problems
        else:
            return {}
        out = {}
        for text in found:
            m = _KEY.match(text)
            if m:
                fid, path = self.target_of(m[1], mode)
                out.setdefault((fid, self.display_key(fid, path)), text)
        return out

    # ------------------------------------------------------------ snapshots
    def target_of(self, key: str, mode: str) -> tuple[str, tuple]:
        """Which file holds an override-style key such as run.supply_V.keysight or pdc.STHL.low"""
        parts = key.split(".")
        if parts[0] == "hardware":
            return "hardware", tuple(parts[1:])
        if parts[0] in RUN_SECTIONS:
            return "run", tuple(parts)
        return f"mode:{mode}", tuple(parts)

    def override_keys(self, mode: str) -> list[str]:
        """Every editable leaf as an override-style key, for the sweep builder"""
        keys = []
        for fid in ("run", "hardware", f"mode:{mode}"):
            keys += [self.display_key(fid, p) for p, v in self.leaves(fid) if isinstance(v, (int, float, str)) or v is None]
        return keys

    def snapshot(self, dest: Path, mode: str, overrides: dict | None = None) -> dict:
        """Writes a full configs folder with the working values and overrides. Returns the edited copies by file id"""
        dest = Path(dest)
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(self.dir, dest, ignore=shutil.ignore_patterns("__pycache__", "gui.yaml"))
        data = {fid: Y.clone(f.data) for fid, f in self.files.items()}
        for key, value in (overrides or {}).items():
            fid, path = self.target_of(key, mode)
            parent = Y.get_in(data[fid], path[:-1])
            real = Y.resolve_key(parent, path[-1])
            parent[real] = Y.coerce_like(parent[real], value)
        for fid, f in self.files.items():
            Y.save(data[fid], dest / f.path.relative_to(self.dir))
        return data

    def adopt(self, snapshot_dir: Path) -> None:
        """Loads the files of a job snapshot into the working copy"""
        for fid, f in self.files.items():
            p = Path(snapshot_dir) / f.path.relative_to(self.dir)
            if p.is_file():
                f.data = Y.loads(p.read_text())
                self.fileReloaded.emit(fid)
        self.dirtyChanged.emit()

    def diff_vs_saved(self, data: dict | None = None) -> list[str]:
        """Lines 'file: key  old -> new' for every value that differs from the files on disk"""
        lines = []
        for fid, f in self.files.items():
            disk = dict(Y.walk(Y.loads(f.path.read_text())))
            now = dict(Y.walk((data or {}).get(fid, f.data)))
            for path, v in now.items():
                if path in disk and disk[path] != v:
                    lines.append(f"{self.display_key(fid, path)}:  {disk[path]!r} -> {v!r}")
        return lines

    # ----------------------------------------------------------------- pins
    @property
    def pin_file(self) -> Path:
        return self.dir / "gui.yaml"

    def _load_pins(self) -> None:
        if self.pin_file.is_file():
            entries = Y.load(self.pin_file).get("pins") or []
            self.pins = [Pin(e["file"], str(e["path"]), e.get("label", "")) for e in entries]
        else:
            self.pins = []
            for fid, path, label in DEFAULT_PINS:
                targets = [f"mode:{m}" for m in self.modes] if fid == "mode:*" else [fid]
                self.pins += [Pin(t, path, label) for t in targets if t in self.files]
        self.pins = [p for p in self.pins if self.resolve(p) is not None]

    def save_pins(self) -> None:
        data = Y.loads("pins: []\n")
        data["pins"] = [{"file": p.file, "path": p.path, "label": p.label} for p in self.pins]
        Y.save(data, self.pin_file)

    def resolve(self, pin: Pin) -> tuple | None:
        if pin.file not in self.files:
            return None
        try:
            return Y.parse_path(self.files[pin.file].data, pin.path)
        except (KeyError, TypeError):
            return None

    def find_pin(self, fid: str, path: tuple) -> Pin | None:
        text = Y.path_str(path)
        return next((p for p in self.pins if p.file == fid and p.path == text), None)

    def set_pinned(self, fid: str, path: tuple, pinned: bool, label: str = "") -> None:
        pin = self.find_pin(fid, path)
        if pinned and pin is None:
            self.pins.append(Pin(fid, Y.path_str(path), label))
        elif not pinned and pin is not None:
            self.pins.remove(pin)
        else:
            return
        self.save_pins()
        self.pinsChanged.emit()

    def move_pin(self, pin: Pin, delta: int) -> None:
        i = self.pins.index(pin)
        j = max(0, min(len(self.pins) - 1, i + delta))
        self.pins.insert(j, self.pins.pop(i))
        self.save_pins()
        self.pinsChanged.emit()
