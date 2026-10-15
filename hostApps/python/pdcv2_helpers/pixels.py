"""
Which SPADs get enabled in the DSUM mode

The mask size, per-PDC disabled areas, checker pattern, screamer method and its threshold are keys of run.yaml
under `pixels`. The mask is rebuilt for every PDC, so a disabled area of one PDC never carries over to the next.
"""
from __future__ import annotations
import sys
from pathlib import Path
from typing import Optional
import numpy as np
from .paths import resolve_tcr_file


class Tee:
    """print to the terminal and to a file at the same time (pdcv2_modules.systemHelper.Tee does the same)"""
    def __init__(self, *files):
        self.files = files

    def write(self, obj):
        for f in self.files:
            f.write(obj)
            f.flush()

    def flush(self):
        for f in self.files:
            f.flush()


def _span(rng):
    "Establishes span [start, stop] with null for an open end"
    if rng is None:
        return slice(None)
    start, stop = rng
    return slice(start, stop)

def make_enable_mask(pix_cfg: dict, i_pdc: int, use_per_pdc_off: bool, shape: tuple[int, int]) -> np.ndarray:
    """1 = Enabled, 0 = Forced off"""
    m = pix_cfg["mask"]
    mask = np.zeros(shape, dtype=int)
    cx, cy, w, h = m["cx"], m["cy"], m["width"], m["height"]
    mask[cx - w // 2:cx + w // 2, cy - h // 2:cy + h // 2] = 1
    if m.get("checker"):
        checker = np.zeros(shape, dtype=int)
        pitch = 2
        checker[pitch // 2::pitch, ::pitch] = 1
        checker[::pitch, pitch // 2::pitch] = 1
        mask = np.logical_and(mask, checker).astype(int)
    if use_per_pdc_off:
        off = {int(k): v for k, v in (pix_cfg.get("per_pdc_off") or {}).items()}
        for rect in off.get(i_pdc, []):
            mask[_span(rect.get("x")), _span(rect.get("y"))] = 0
    return mask

def screamer_kwargs(sc: dict) -> dict:
    """Grabs screamer config values"""
    method = sc["method"]
    if method == "constant":
        return {"thConst": float(sc["threshold"])}
    if method == "percent":
        return {"thPct": float(sc["percent"])}
    if method == "medianFactor":
        return {"thMedFactor": float(sc["factor"])}
    return {}

def load_tcr(cfg: dict, paths):
    """Loads the TCR output file for DSUM. Returns None if source is all"""
    import pandas as pd
    px = cfg["pixels"]
    if px["source"] == "all":
        return None
    path = resolve_tcr_file(px.get("tcr_file"))
    print(f"TCR file: {path}")
    return pd.read_csv(path, header=0, sep=";")

def apply_dsum_pixels(session, stats_file: Optional[Path] = None, plot_prefix: Optional[str] = None) -> None:
    """Actually enable the SPADs. TCR file -> screamer threshold -> mask -> pixel registers"""
    import pdcv2_modules.pixMap as pixMap
    import pdcv2_modules.pdcSpadFunctions as pdcSpadFunctions
    cfg, icp, client = session.cfg, session.icp, session.client
    px = cfg["pixels"]
    use_off = bool(cfg["behavior"].get("per_pdc_pixel_off"))
    shape = (pixMap.TOP_NX_PIX, pixMap.TOP_NY_PIX)

    df = load_tcr(cfg, session.paths)
    method = px["screamer"]["method"]
    kwargs = screamer_kwargs(px["screamer"])

    stats = open(stats_file, "w") if stats_file else None
    stdout = sys.stdout
    if stats:
        sys.stdout = Tee(stdout, stats)
    try:
        for i_pdc in range(icp.nPdcMax):
            if ((icp.pdcEnUser >> i_pdc) & 0x1) != 0x1:
                continue
            print(f"PDC{i_pdc}:")
            mask = make_enable_mask(px, i_pdc, use_off, shape)
            pix_array = np.ones(pixMap.TOP_N_PIX) if df is None else None
            try:
                if df is not None:
                    pix_array = df[f"SPAD_TCR{i_pdc}"]
                th_method = getattr(pdcSpadFunctions.ThreshMethod, "constant" if df is None else method)
                kw = {"thConst": 1.0} if df is None else kwargs
                plot = f"{plot_prefix}_pixelMap_{i_pdc}.png" if (plot_prefix and cfg["run"]["save_plot"]) else ""
                regs = pdcSpadFunctions.convertPixArrayToReg(
                    pixArray=pix_array, thMethod=th_method, thOp=pdcSpadFunctions.ThreshOp.le,
                    pixEnMask=mask, returnAnalysis=False, log=False, plot=plot, **kw)
                if px.get("show_mask") and not cfg["run"]["batch_mode"]:
                    _show_mask(mask, i_pdc)
                icp.cfgAllPixRegs(regs, i_pdc)
            except KeyError:
                print(f"ERROR: no data found for PDC {i_pdc}.")
                client.runPrint(f"pdcSpad --dis --spdc {i_pdc} --mode NONE", printCmd=False)
    finally:
        sys.stdout = stdout
        if stats:
            stats.close()
    client.runPrint("ctlCfg -a CFGS -r 0x0000 -g")

def _show_mask(mask: np.ndarray, i_pdc: int | None = None) -> None:
    """Shows the enable mask before a run starts"""
    import matplotlib.colors as mcolors
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots()
    cmap = mcolors.LinearSegmentedColormap.from_list("BlackWhite", [(0, "black"), (1, "white")])
    ax.imshow(mask.T, cmap=cmap, vmin=0, vmax=1, origin="lower", aspect="equal")
    ax.set_title(f"PDC{i_pdc} enable mask")
    plt.show(block=False)
    fig.canvas.draw()
    fig.canvas.flush_events()
    fig.canvas.start_event_loop(0.1)