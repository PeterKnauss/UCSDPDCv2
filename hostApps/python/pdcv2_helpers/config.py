"""
Load the YAML files into one Config object.

Three files, each key lives in exactly one of them:

    configs/hardware.yaml        the bench: ssh host, supplies, folders           (rarely edited)
    configs/modes/<mode>.yaml    every register value and Zynq command of a mode  (edited when the experiment changes)
    configs/run.yaml             head, bias, meas time, pixels, name              (edited between runs)

then command-line overrides ("pdc.STHL.low=8") on top, for one run only. Later layers win. Nothing is
merged between mode files.

Each supply in hardware.yaml also gets the commands of its model from configs/supplies/<model>.yaml

    cfg = load_config("dsum_rad", overrides=["run.head_id=48", "pdc.STHL.low=8"])
    cfg.run.head_id            # attribute access
    cfg["run"]["head_id"]      # dict access works too
    plan_cfg(cfg)              # the dict that plan.build_plan() wants
"""
from __future__ import annotations
import copy
import os
from pathlib import Path
from typing import Iterable, Optional
import yaml
from .paths import run_folder_name
from .power import check_addresses, check_profile

CONFIG_DIR = Path(__file__).resolve().parent.parent / "configs"
MODES = ("tcr", "dsum_coincidence", "dsum_rad", "dsum_single")


class ConfigError(ValueError):
    """Error call for keeping track of errors in the config. From validate() it has the list of problems in .problems"""
    problems: list = []

class AttrDict(dict):
    """Dictionary whos keys can also be read as attributes. Nested dicts wrapped on access"""
    def __getattr__(self, name):
        try:
            v = self[name]
        except KeyError:
            raise AttributeError(name) from None
        return AttrDict(v) if isinstance(v, dict) and not isinstance(v, AttrDict) else v

class Config(AttrDict):
    """Fully merged config. Merged like hardware < mode < run < overrides"""
    mode: str = ""
    sources: tuple = ()


def deep_merge(base: dict, over: dict) -> dict:
    """Dicts are merged key by key with 'over' replacing the key in 'base'"""
    out = dict(base)
    for k, v in over.items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else copy.deepcopy(v)
    return out

def _read(path: Path) -> dict:
    """Reads in the yaml safely"""
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    data = yaml.safe_load(path.read_text())
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: top level must be a mapping of keys, got {type(data).__name__}")
    return data

def apply_overrides(data: dict, overrides: Iterable[str]) -> dict:
    """Applies requested overrides. Value parsed as YAML. Key must already exist. Prefix with '+' to specifically add a key (+key.name=value)"""
    data = copy.deepcopy(data)
    for item in overrides:
        if "=" not in item:
            raise ConfigError(f"override '{item}' must look like section.key=value")
        key, text = item.split("=", 1)
        add_new = key.startswith("+")
        key = key.lstrip("+")
        parts = key.split(".")
        node = data
        for p in parts[:-1]:
            if not isinstance(node, dict) or p not in node:
                raise ConfigError(f"override '{item}': no key '{p}' in the config (path {key})")
            node = node[p]
        if not isinstance(node, dict):
            raise ConfigError(f"override '{item}': '{'.'.join(parts[:-1])}' is not a section")
        if parts[-1] not in node and not add_new:
            raise ConfigError(f"override '{item}': no key '{parts[-1]}' under '{'.'.join(parts[:-1])}' "
                              f"(valid: {sorted(node)}). Use +{key}=... to add a new key.")
        try:
            node[parts[-1]] = yaml.safe_load(text)
        except yaml.YAMLError as ex:
            raise ConfigError(f"override '{item}': the value is not valid YAML ({str(ex).splitlines()[0]}). "
                              f"Put quotes around text that starts with {{ or [, like {key}=\"{{run.head_id}}_x\"") from ex
    return data

def attach_profiles(data: dict, cdir: Path) -> None:
    """Adds the commands of each supply model to the supply as profile so they are saved with the run"""
    for name, c in data.get("hardware", {}).get("supplies", {}).items():
        model = c.get("model")
        if not model:
            raise ConfigError(f"hardware.supplies.{name}: missing key 'model' (the name of a file in {cdir / 'supplies'})")
        c["profile"] = _read(cdir / "supplies" / f"{model}.yaml")

def load_config(mode: str,
                overrides: Iterable[str] = (),
                run_file: Optional[str | Path] = None,
                config_dir: Optional[str | Path] = None,
                check: bool = True) -> Config:
    """Loads all configs and merges them. Merges like hardware < mode < run < overrides"""
    if mode not in MODES:
        raise ConfigError(f"unknown mode '{mode}', expected one of {MODES}")
    cdir = Path(config_dir) if config_dir else CONFIG_DIR
    hw, md, rn = cdir / "hardware.yaml", cdir / "modes" / f"{mode}.yaml", Path(run_file) if run_file else cdir / "run.yaml"
    data = deep_merge(deep_merge({"hardware": _read(hw)}, _read(md)), _read(rn))
    data = apply_overrides(data, overrides)
    # After the overrides so hardware.supplies.<name>.model can be set on the command line
    attach_profiles(data, cdir)
    cfg = Config(data)
    cfg.mode = mode
    cfg.sources = (str(hw), str(md), str(rn))
    if check:
        validate(cfg)
    return cfg


_PIXEL_SOURCES = ("all", "tcr_file")
_SCREAMER = ("constant", "average", "percent", "medianFactor", "medianToMin")
_DSUM_DATA = ("all", "NZ", "NZKF", "dt", "max")
_BIN_IDX = ("time", "continuous", "frame")


def validate(cfg: dict) -> None:
    """Check all the different things"""
    problems: list[str] = []

    def need(path: str):
        node = cfg
        for p in path.split("."):
            if not isinstance(node, dict) or p not in node:
                problems.append(f"missing key '{path}'")
                return None
            node = node[p]
        return node

    def check(path, ok, expect):
        v = need(path)
        if v is not None and not ok(v):
            problems.append(f"'{path}' = {v!r}: expected {expect}")

    check("run.pdc_enable", lambda v: isinstance(v, int) and 0 < v < 2**32, "an integer mask such as 0xF")
    check("run.n_spad", lambda v: isinstance(v, int) and 0 < v <= 4096, "an integer from 1 to 4096")
    check("run.head_id", lambda v: v is None or isinstance(v, (int, str)), "an integer or empty")
    supplies, volts = need("hardware.supplies"), need("run.supply_V")
    if isinstance(supplies, dict) and isinstance(volts, dict):
        for name, c in supplies.items():
            problems += check_profile(name, c)
            v = volts.get(name)
            if not isinstance(v, (int, float)) or not 0 <= v <= c.get("max_V", 0):
                problems.append(f"run.supply_V.{name} = {v!r}: expected a number from 0 to {c.get('max_V')} V (hardware.supplies.{name}.max_V)")
        problems += [f"run.supply_V.{n}: no supply with that name in hardware.supplies" for n in volts if n not in supplies]
        problems += check_addresses(supplies)
        tag = cfg["run"].get("spad_supply")
        if tag and tag not in supplies:
            problems.append(f"run.spad_supply = {tag!r}: expected a name from hardware.supplies or empty")
    for flag in ("run.batch_mode", "run.analog_only", "run.save_plot"):
        check(flag, lambda v: isinstance(v, bool), "true or false")
    check("run.meas_time_s", lambda v: isinstance(v, (int, float)) and v > 0, "a positive number of seconds")
    check("tcr.meas_time_s", lambda v: isinstance(v, (int, float)) and v > 0, "a positive number of seconds")
    check("pixels.source", lambda v: v in _PIXEL_SOURCES, f"one of {_PIXEL_SOURCES}")
    check("pixels.screamer.method", lambda v: v in _SCREAMER, f"one of {_SCREAMER}")
    check("tcr.screamer.method",
          lambda v: v in _SCREAMER + ("threshold",), f"one of {_SCREAMER}")
    check("dsum.data_type", lambda v: v in _DSUM_DATA, f"one of {_DSUM_DATA}")
    check("dsum.bin_idx_mode", lambda v: v in _BIN_IDX, f"one of {_BIN_IDX}")
    check("hardware.zynq.ssh_host", lambda v: isinstance(v, str) and v, "the host name from ~/.ssh/config")
    check("hardware.zynq.sys_clk_period_ns", lambda v: isinstance(v, (int, float)) and v > 0, "a positive number")
    # run_folder is a path (relative is inside hardware.paths.user_data_dir, a full path is used as it is) that can have {section.key} fields
    need("run.run_folder")
    if isinstance(cfg.get("run"), dict) and "run_folder" in cfg["run"]:
        raw, example = cfg["run"]["run_folder"], "such as tcr_10152026 or path/to/tcr_H{run.head_id}"
        folder = None
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            problems.append(f"'run.run_folder' is empty: set the folder for this run, {example}")
        elif not isinstance(raw, str):
            problems.append(f"'run.run_folder' = {raw!r}: expected text, {example}")
        else:
            try:
                folder = run_folder_name(cfg)
            except ValueError as ex:
                problems.append(f"'run.run_folder' = {raw!r}: {ex}")
        if folder is not None:
            shown = f"{raw!r}" + (f" (is {folder!r})" if folder != raw else "")
            if not folder:
                problems.append(f"'run.run_folder' = {shown}: is empty once its fields are filled in")
            elif any(ch < " " or ch == "\x7f" for ch in folder):
                problems.append(f"'run.run_folder' = {shown}: has a control character (a newline or tab) in it")
            else:
                try:
                    path = Path(folder).expanduser()
                    if os.path.normpath(path) in (".", "..") or path == Path(path.anchor):
                        problems.append(f"'run.run_folder' = {shown}: must name a folder for this run, not the data folder itself or its parent")
                except RuntimeError as ex:
                    problems.append(f"'run.run_folder' = {shown}: cannot expand the ~ in it: {ex}")
    check("pdc", lambda v: isinstance(v, dict), "a section of PDC register values")
    check("controller", lambda v: isinstance(v, dict), "a section of controller register values")

    # Check that tcr file is a full filename
    if cfg.mode.startswith("dsum") and cfg.get("pixels", {}).get("source") == "tcr_file":
        f = cfg["pixels"].get("tcr_file")
        if not f:
            problems.append("'pixels.tcr_file' is empty: set the full path to the TCR csv, or set pixels.source to 'all'")
        else:
            tcr = Path(str(f)).expanduser()
            if not tcr.is_absolute():
                problems.append(f"'pixels.tcr_file' = {f!r}: expected a full path")
            elif not tcr.is_file():
                problems.append(f"'pixels.tcr_file' = {str(tcr)!r}: file not found")

    if cfg.get("run", {}).get("analog_only") and not cfg.get("behavior", {}).get("allow_analog_only"):
        problems.append("'run.analog_only' is true, but this mode does not support it (behavior.allow_analog_only is false)")

    if problems:
        error = ConfigError("config problems:\n  - " + "\n  - ".join(problems))
        error.problems = problems
        raise error

def plan_cfg(cfg: dict) -> dict:
    """
    Creates a config that plan.build_plan() can read to make the startup plan. Adds a few values that aren't input elsewhere
        enable_mask       <- run.pdc_enable
        sys_clk_period_s  <- hardware.zynq.sys_clk_period_ns
        OUTF function     <- FLAG when run.analog_only (flag pin carries the flag, not the sum threshold)
        ZPP period        <- tcr.meas_time_s when behavior.zpp_period_from_meas_time (TCR)
    """
    out = {
        "enable_mask": int(cfg["run"]["pdc_enable"]),
        "sys_clk_period_s": float(cfg["hardware"]["zynq"]["sys_clk_period_ns"]) * 1e-9,
        "pdc": copy.deepcopy(dict(cfg["pdc"])),
        "controller": copy.deepcopy(dict(cfg["controller"])),
    }
    if cfg["run"].get("analog_only") and cfg.get("behavior", {}).get("allow_analog_only"):
        out["pdc"]["OUTF"] = {"func": "FLAG"}
    if cfg.get("behavior", {}).get("zpp_period_from_meas_time"):
        out["controller"].setdefault("apps", {})["zpp_period_s"] = cfg["tcr"]["meas_time_s"]
    return out

def dump(cfg: dict, path: str | Path) -> Path:
    """Saves the fully resolved config printout"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    plain = yaml.safe_load(yaml.safe_dump(dict(cfg), sort_keys=False))
    header = "# resolved config (hardware < mode < run < command line)\n"
    if getattr(cfg, "sources", None):
        header += "".join(f"#   {s}\n" for s in cfg.sources)
    path.write_text(header + yaml.safe_dump(plain, sort_keys=False))
    return path
