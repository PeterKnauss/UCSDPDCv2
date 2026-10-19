"""Lots of path management"""
from __future__ import annotations
import datetime
import string
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

def run_folder_name(cfg) -> str:
    """
    run.run_folder with its {section.key} fields filled in from the config, such as tcr_H{run.head_id}_{run.supply_V.keysight}V
    {mode} is the mode name, {{ and }} are literal braces, and a format can follow a colon like {run.supply_V.keysight:05.1f}
    """
    out = []
    for text, field, spec, conv in string.Formatter().parse(cfg["run"]["run_folder"]):
        out.append(text)
        if field is None:
            continue
        if conv:
            raise ValueError(f"{{{field}!{conv}}}: conversions with ! are not supported")
        if field == "run.run_folder":
            raise ValueError("{run.run_folder} cannot be used inside run_folder")
        node = getattr(cfg, "mode", "") if field == "mode" else cfg
        for part in ([] if field == "mode" else field.split(".")):
            key = next((k for k in node if str(k) == part), None) if isinstance(node, dict) else None
            if key is None:
                raise ValueError(f"{{{field}}}: no key '{part}' in the config")
            node = node[key]
        if isinstance(node, (dict, list)):
            raise ValueError(f"{{{field}}} is a section or a list, not a single value")
        out.append(format(node, spec) if spec else _num(node) if isinstance(node, float) else "" if node is None else str(node))
    return "".join(out).strip()

def run_dir(cfg, paths: RunPaths) -> Path:
    """<user_data_dir>/<run_folder>, or run_folder itself when it is a full path. Every file a run writes goes in this folder"""
    return paths.user_data / Path(run_folder_name(cfg)).expanduser()

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