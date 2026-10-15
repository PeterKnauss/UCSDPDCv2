"""Lots of path management"""
from __future__ import annotations
import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class RunPaths:
    user_data: Path


def resolve_paths(cfg) -> RunPaths:
    """hardware.paths.user_data_dir if set, else the folder the repo's zynqEnvHelper resolves (env var USER_DATA_DIR or default)."""
    user = cfg["hardware"]["paths"].get("user_data_dir")
    if user is None:
        from pdcv2_modules.zynqEnvHelper import USER_DATA_DIR
        user = USER_DATA_DIR
    return RunPaths(user_data=Path(user).expanduser())

def run_dir(cfg, paths: RunPaths) -> Path:
    """<user_data_dir>/<run.run_folder>. Every file a run writes goes in this folder"""
    return paths.user_data / cfg["run"]["run_folder"]

def _num(v) -> str:
    """25 -> '25', 25.0 -> '25', 25.5 -> '25.5'"""
    return format(v, "g") if isinstance(v, float) else str(v)

def bias_str(volts) -> str:
    """'_25V' for 25, '_25V5' for 25.5 (the decimal point becomes 'V')"""
    if volts is None:
        return ""
    s = _num(volts).replace(".", "V").replace(",", "V")
    return "_" + (s if "V" in s else s + "V")

def tag_voltage(run: dict):
    """Voltage of the supply in run.spad_supply for the filename. None if it is empty"""
    name = run.get("spad_supply")
    return run["supply_V"][name] if name else None

def head_str(head_id) -> str:
    return f"H{head_id}_" if head_id not in (None, "") else ""

def name_str(name) -> str:
    return f"_{name}" if name else ""

def meas_str(meas_time_s) -> str:
    return _num(meas_time_s)

def date_str(now: Optional[datetime.datetime] = None) -> str:
    return (now or datetime.datetime.now()).strftime("%Y%m%d_%Hh%Mm%S")

def dsum_file_name(cfg, date: Optional[str] = None) -> str:
    r, d = cfg["run"], cfg["dsum"]
    return (f"{date or date_str()}_{cfg.mode}_{head_str(r.get('head_id'))}{d['data_type']}_{d['bin_idx_mode']}"
            f"{bias_str(tag_voltage(r))}_{meas_str(r['meas_time_s'])}s{name_str(r.get('name'))}.csv")

def resolve_tcr_file(value) -> Path:
    """The TCR csv used for screamer masking"""
    if not value:
        raise FileNotFoundError("no TCR file specified (set pixels.tcr_file in run.yaml to the full path, or pixels.source: all)")
    p = Path(str(value)).expanduser()
    if not p.is_absolute():
        raise FileNotFoundError(f"pixels.tcr_file = {value!r} is not a full path. Give the full path to the TCR csv")
    if not p.is_file():
        raise FileNotFoundError(f"TCR file not found: {p}")
    return p