"""Lots of path management"""
from __future__ import annotations
import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class RunPaths:
    user_data: Path
    hdf5: Path


def resolve_paths(cfg) -> RunPaths:
    """hardware.paths.* if set, else the folders the repo's zynqEnvHelper resolves (env var USER_DATA_DIR or default)."""
    p = cfg["hardware"]["paths"]
    user, h5 = p.get("user_data_dir"), p.get("hdf5_dir")
    if user is None or h5 is None:
        from pdcv2_modules.zynqEnvHelper import USER_DATA_DIR, HDF5_DATA_DIR
        user = user or USER_DATA_DIR
        h5 = h5 or HDF5_DATA_DIR
    return RunPaths(user_data=Path(user).expanduser(), hdf5=Path(h5).expanduser())

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

def dsum_csv_dir(cfg, paths: RunPaths) -> Path:
    """behavior.csv_dir may contain {rad_source}"""
    return paths.user_data / cfg["behavior"]["csv_dir"].format(rad_source=cfg["run"].get("rad_source", ""))

def dsum_file_name(cfg, date: Optional[str] = None) -> str:
    r, d, b = cfg["run"], cfg["dsum"], cfg["behavior"]
    return (f"{date or date_str()}_{b['script_tag']}_{head_str(r.get('head_id'))}{d['data_type']}_{d['bin_idx_mode']}"
            f"{bias_str(tag_voltage(r))}_{meas_str(r['meas_time_s'])}s{name_str(r.get('name'))}.csv")

def tcr_data_dir(cfg, paths: RunPaths) -> Path:
    """where the TCR mode writes its CSV: <user_data>/TCR/<script_tag>"""
    return paths.user_data / "TCR" / cfg["behavior"]["script_tag"]

def resolve_tcr_file(value, paths: RunPaths) -> Path:
    """a TCR csv given as a full path, or as a file name searched in <user_data>/TCR/*/"""
    if not value:
        raise FileNotFoundError("no TCR file specified (set pixels.tcr_file in run.yaml, or pixels.source: all)")
    p = Path(str(value)).expanduser()
    if p.is_file():
        return p
    matches = sorted((paths.user_data / "TCR").glob(f"*/{value}"))
    if matches:
        return matches[-1]
    raise FileNotFoundError(f"could not find TCR file '{value}' (looked for {p} and {paths.user_data / 'TCR'}/*/{value})")
