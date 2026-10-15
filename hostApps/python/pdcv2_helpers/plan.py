"""
Creates a plan based on config inputs that can be used to turn on the Controller and PDCs in the correct 
order by using different groupings

    plan = build_plan(cfg)
    plan["packet"]       # SCSA, SCDA, SPDA            (right after resetCtl)
    plan["fsm"]          # TOUT ... FSMM               (DSUM modes only)
    plan["pdc"]          # pdcTime, PIXL ... TRGC      (between MODE_CFG and `pdcPix --dis`)
    plan["pdc_final"]    # OUTC                        (after validPdcCfg)
    plan["stream"]       # streamManager (bandwidth; first thing sent after MODE_ACQ)
    plan["interfaces"]   # ITF2 ...                    (DSUM rad)
    plan["coincidence"]  # COI0/1, COIW, COTH
    plan["zynq_apps"]    # auxOut / auxIn / set-ctl-tmr-prd / set-ctl-zpp-prd commands
    plan["fsm_command"]  # FSMM start_mode = 1 (TCR: FSM triggered by a command, after HV)
    plan["start_fsm"]    # FSMM with start_mode = 3    (after HV is applied)

A stage function sends one group at the right moment; this file only decides WHAT is sent.
"""
from __future__ import annotations
from typing import Mapping
from .registers import REGS, RegWrite, pack_reg, split_32bit, split_enable_mask


def cmd_pdc_time(hold_ns, rech_ns, flag_ns) -> str:
    return f"pdcTime --hold {hold_ns} --rech {rech_ns} --flag {flag_ns} -g"

def cmd_aux_out(channel, func, n=None) -> str:
    return f"auxOut --ch {channel} --func {func}" + (f" -n {n}" if n is not None else "") + " -g"

def cmd_aux_in(func, channel) -> str:
    return f"auxIn --func {func} --channel {channel} -g"

def cmd_set_zpp_prd(seconds) -> str:
    return f"set-ctl-zpp-prd {seconds}"

def cmd_set_tmr_prd(freq) -> str:
    return f"set-ctl-tmr-prd FREQ={freq}"

def cmd_stream_manager(tlast_threshold=500, timeout_s=1) -> str:
    return f"streamManager --thresh {tlast_threshold} -T {timeout_s} --sec"

def derive_fsm(f: Mapping) -> list[tuple[str, dict]]:
    """FSM block:
       - FTX1.n = total samples, FIFO depth = total - 1
       - slow state takes the trigger when there is no fast state
       - delays are masked with 0xFF (e.g. fast delay 0 - 28 = 0xE4)
    """
    n_fast, n_slow, n_hist = f["samples"]["n_fast"], f["samples"]["n_slow"], f["samples"]["n_history"]
    n_total = n_fast + n_slow
    trg = f["trigger_mode"]
    t, e, tx, atx, acq, misc = f["timeout"], f["end"], f["tx"], f["atx"], f["acq"], f["misc"]
    return [
        ("TOUT", dict(auto=t["auto"], all_pdc=t["all_pdc"], retry=t["retry"], period=t["period"])),
        ("FEND", dict(enable=e["enable"], mode=e["mode"], delay=e["delay"])),
        ("FTX1", dict(cancel_send_rstn=tx["cancel_send_rstn"], cancel_mode=tx["cancel_mode"], n=n_total)),
        ("FTX0", dict(enable=tx["enable"], cmd_mode=tx["cmd_mode"], mode=tx["mode"], cmd_delay=tx["cmd_delay"])),
        ("ATX1", dict(cancel_send_rstn=atx["cancel_send_rstn"], cancel_mode=atx["cancel_mode"], n=atx["n"])),
        ("ATX0", dict(enable=atx["enable"], mode=atx["mode"], cmd_mode=atx["cmd_mode"], cmd_delay=atx["cmd_delay"])),
        ("SLW1", dict(period=f["slow_period"], n=n_slow)),
        ("SLW0", dict(enable=int(n_slow > 0),
                      mode=trg if n_fast == 0 else 0,
                      delay=((n_slow - n_hist) if n_fast == 0 else 0) & 0xFF)),
        ("FST1", dict(n=n_fast)),
        ("FST0", dict(enable=int(n_fast > 0), mode=trg, delay=(n_fast - n_hist) & 0xFF)),
        ("FACQ", dict(cancel_send_rstn=acq["cancel_send_rstn"], cancel_mode=acq["cancel_mode"],
                      overlap=acq["overlap"], cmd_mode=acq["cmd_mode"])),
        ("FSMM", dict(tx_all_pdc=misc["tx_all_pdc"], acq_all_pdc=misc["acq_all_pdc"], start_mode=0)),
    ]

def fifo_depth_auto(f: Mapping) -> int:
    n_total = f["samples"]["n_fast"] + f["samples"]["n_slow"]
    return n_total - 1 if n_total > 0 else 127

def derive_trigger_generator(tg: Mapping, enable_mask: int, clk_prd_s: float) -> list[tuple[str, int]]:
    """testPixQcUsingTrigger.py: N_TRG_ON = int(on / clk), N_TRG_OFF = int(prd / clk) - N_TRG_ON"""
    n_cyc = int(tg["period_s"] / clk_prd_s)
    n_on = int(tg["on_s"] / clk_prd_s)
    lo, hi = split_enable_mask(enable_mask)
    return [("TRGN", 0), ("TRG0", lo), ("TRG1", hi), ("TRG2", 0), ("TRG3", 0), ("TRGS", 0),
            ("TRGH", n_on), ("TRGL", n_cyc - n_on)]

def _w(name: str, value: int, note: str = "") -> RegWrite:
    return RegWrite(REGS[name], value, note)

def build_plan(cfg: Mapping) -> dict[str, list]:
    plan: dict[str, list] = {k: [] for k in
        ("packet", "fsm", "pdc", "pdc_final", "stream", "interfaces", "coincidence", "zynq_apps", "external", "trigger_gen", "fsm_command", "start_fsm")}
    mask = cfg.get("enable_mask", 0xF)
    ctl = cfg.get("controller", {})
    pdc = cfg.get("pdc", {})
    fsm_cfg = ctl.get("fsm")

    for name in ("SCSA", "SCDA", "SPDA", "SCSB", "SCDB", "SPDB"):
        if name in ctl.get("packet", {}):
            plan["packet"].append(_w(name, pack_reg(name, ctl["packet"][name])))

    if fsm_cfg:
        for name, fields in derive_fsm(fsm_cfg):
            plan["fsm"].append(_w(name, REGS[name].pack(**fields)))

    for name in ("PIXL", "TIME", "ANLG", "STHH", "STHL", "FIFO", "OUTD", "OUTF", "TRGC"):
        if name == "TIME":
            if "time" in pdc:
                t = pdc["time"]
                plan["pdc"].append(cmd_pdc_time(t["hold_ns"], t["rech_ns"], t["flag_ns"]))
            continue
        if name in pdc:
            spec = pdc[name]
            if name == "FIFO" and isinstance(spec, dict) and spec.get("depth") == "auto":
                spec = {**spec, "depth": fifo_depth_auto(fsm_cfg) if fsm_cfg else 127}
            plan["pdc"].append(_w(name, pack_reg(name, spec)))
    if "OUTC" in pdc:
        plan["pdc_final"].append(_w("OUTC", pack_reg("OUTC", pdc["OUTC"])))

    for name, spec in ctl.get("interfaces", {}).items():
        plan["interfaces"].append(_w(name, pack_reg(name, spec)))

    co = ctl.get("coincidence")
    if co:
        lo, hi = split_enable_mask(mask)
        plan["coincidence"] += [_w("COI0", lo), _w("COI1", hi),
                                _w("COIW", REGS["COIW"].pack(window=co["window"])),
                                _w("COTH", REGS["COTH"].pack(nch_th=co["nch_th"], num_bank=co["num_bank"]))]

    apps = ctl.get("apps", {})
    if "zpp_period_s" in apps:
        plan["zynq_apps"].append(cmd_set_zpp_prd(apps["zpp_period_s"]))
    if "strobe_timer_freq" in apps:
        plan["zynq_apps"].append(cmd_set_tmr_prd(apps["strobe_timer_freq"]))
    for a in apps.get("aux_out", []):
        plan["zynq_apps"].append(cmd_aux_out(a["channel"], a["func"], a.get("n")))
    for a in apps.get("aux_in", []):
        plan["zynq_apps"].append(cmd_aux_in(a["func"], a["channel"]))
    if "stream_manager" in apps:
        plan["stream"].append(cmd_stream_manager(**apps["stream_manager"]))

    ext = ctl.get("external")
    if ext:
        plan["external"].append(_w("AUXI", REGS["AUXI"].pack(**ext["auxi"])))
        lo, hi = split_32bit(ext["strobe_timer_cycles"], enable=True)
        plan["external"] += [_w("TMR0", lo), _w("TMR1", hi)]

    if "trigger_generator" in ctl:
        for name, v in derive_trigger_generator(ctl["trigger_generator"], mask, cfg["sys_clk_period_s"]):
            plan["trigger_gen"].append(_w(name, v))

    if "fsm_command" in ctl:
        plan["fsm_command"].append(_w("FSMM", REGS["FSMM"].pack(**ctl["fsm_command"])))

    if fsm_cfg:
        misc = fsm_cfg["misc"]
        plan["start_fsm"].append(_w("FSMM", REGS["FSMM"].pack(tx_all_pdc=misc["tx_all_pdc"],
                                                              acq_all_pdc=misc["acq_all_pdc"], start_mode=3)))
    return plan

def commands(group: list) -> list[str]:
    """turn a plan group into the command strings that would be sent"""
    return [g if isinstance(g, str) else g.command for g in group]
