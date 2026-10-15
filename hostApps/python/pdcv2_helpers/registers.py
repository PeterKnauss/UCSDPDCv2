"""
registers.py -- declarative register map for the PDC chips and the Controller (FPGA).

Every register is described once as a list of named bit fields. `Reg.pack()` turns named fields into the 16-bit
value and `Reg.unpack()` goes back the other way.

    PIXL.pack(active_qc_en=1, flag_en=1, edge_lvln=1, dis_mem=1)   -> 0x3102
    PIXL.unpack(0x3102)                                            -> {'active_qc_en': 1, ...}

Registers without a defined layout are 'raw': one 16-bit field called `value`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from pdcv2_modules.pdcHelper import OUT_MUX


@dataclass(frozen=True)
class Field:
    name: str
    lsb: int
    width: int = 1
    enum: Optional[type] = None

    @property
    def mask(self) -> int:
        return (1 << self.width) - 1


@dataclass(frozen=True)
class Reg:
    target: str
    name: str
    addr: int
    fields: tuple = ()
    note: str = ""

    def pack(self, strict: bool = True, **values) -> int:
        """named fields -> register value. Unspecified fields are 0."""
        known = {f.name: f for f in self.fields}
        unknown = set(values) - set(known)
        if unknown:
            raise KeyError(f"{self.name}: unknown field(s) {sorted(unknown)}; valid fields: {sorted(known)}")
        word = 0
        for f in self.fields:
            v = values.get(f.name, 0)
            if isinstance(v, str):
                if f.enum is None:
                    raise TypeError(f"{self.name}.{f.name}: got string {v!r} but this field takes a number")
                v = int(f.enum[v])
            v = int(v)
            if strict and not (0 <= v <= f.mask):
                raise ValueError(f"{self.name}.{f.name}={v} does not fit in {f.width} bit(s) (max {f.mask})")
            word |= (v & f.mask) << f.lsb
        return word

    def unpack(self, word: int) -> dict:
        """register value -> named fields (use it to decode what `pdcTime -g` or a status read returns)."""
        return {f.name: (word >> f.lsb) & f.mask for f in self.fields}

    def command(self, value: int) -> str:
        tool = "pdcCfg" if self.target == "pdc" else "ctlCfg"
        return f"{tool} -a {self.name} -r 0x{value:04x} -g"

    def describe(self, value: int) -> str:
        parts = ", ".join(f"{k}={v}" for k, v in self.unpack(value).items())
        return f"{self.name}=0x{value:04x} [{parts}]"


@dataclass(frozen=True)
class RegWrite:
    """one register write that is planned but not sent yet"""
    reg: Reg
    value: int
    note: str = ""

    @property
    def command(self) -> str:
        return self.reg.command(self.value)


def _f(name, lsb, width=1, enum=None):
    return Field(name, lsb, width, enum)

_RAW = (Field("value", 0, 16),)


_PDC_LIST = [
    Reg("pdc", "PIXL", 1, (_f("active_qc_en", 1), _f("trg_dgtl_fen", 4), _f("flag_en", 8),
                           _f("edge_lvln", 12), _f("dis_mem", 13)),
        "pixel front end: active quenching, trigger source, flag output, synchronizer options"),
    Reg("pdc", "TIME", 2, (_f("hold", 0, 6), _f("rech", 6, 5), _f("flag", 11, 5)), "hold / recharge / flag time"),
    Reg("pdc", "ANLG", 3, _RAW, "analog monitor, 0x0000 = off"),
    Reg("pdc", "STHH", 4, _RAW, "sum threshold high"),
    Reg("pdc", "STHL", 5, (_f("low", 0, 13), _f("enable", 15)), "sum threshold low; enable bit enables STHH and STHL"),
    Reg("pdc", "ACQA", 6, _RAW), Reg("pdc", "ACQB", 7, _RAW), Reg("pdc", "DBGC", 8, _RAW),
    Reg("pdc", "FIFO", 9, (_f("depth", 0, 7), _f("sel_in", 8, 2), _f("enable", 12), _f("overwrite_dis", 13)),
        "depth = bins - 1; sel_in 0=digital sum, 1=debug counter, 2=debug register, 3=zeros"),
    Reg("pdc", "DTXC", 10, _RAW),
    Reg("pdc", "OUTD", 11, (_f("lo", 0, 5, OUT_MUX), _f("hi", 6, 5, OUT_MUX)), "data pin function"),
    Reg("pdc", "OUTF", 12, (_f("lo", 0, 5, OUT_MUX), _f("hi", 6, 5, OUT_MUX)), "flag pin function"),
    Reg("pdc", "OUTC", 13, (_f("data", 0, 5, OUT_MUX), _f("flag", 6, 5, OUT_MUX)), "config pins; written last"),
    Reg("pdc", "TRGC", 14, _RAW, "trigger command, 0x0000 = disabled"),
]

_FSM_CANCEL = (_f("n", 0, 8), _f("cancel_mode", 8, 7), _f("cancel_send_rstn", 15))
_FSM_STATE = (_f("delay", 0, 8), _f("mode", 8, 3), _f("enable", 15))

_CTL_LIST = [
    Reg("ctl", "RSVD", 0, ()),
    Reg("ctl", "PDC0", 1, _RAW, "enable IOs of PDCs 0-15"), Reg("ctl", "PDC1", 2, _RAW), Reg("ctl", "PDC2", 3, _RAW), Reg("ctl", "PDC3", 4, _RAW),
    Reg("ctl", "CFG0", 5, _RAW, "PDCs 0-15 that receive configuration"), Reg("ctl", "CFG1", 6, _RAW), Reg("ctl", "CFG2", 7, _RAW), Reg("ctl", "CFG3", 8, _RAW),
    Reg("ctl", "CFGS", 9, _RAW, "single-PDC configuration select; 0 = off"),
    Reg("ctl", "RTN0", 10, _RAW), Reg("ctl", "RTN1", 11, _RAW), Reg("ctl", "RTN2", 12, _RAW), Reg("ctl", "RTN3", 13, _RAW),
    Reg("ctl", "ITF0", 14, _RAW), Reg("ctl", "ITF1", 15, _RAW),
    Reg("ctl", "ITF2", 16, tuple(
            _f(f"sum_th_{n}", i) for i, n in enumerate(["acq", "tx", "atx", "else", "cfg", "inv", "dfn"])) + tuple(
            _f(f"clk_tx_{n}", 8 + i) for i, n in enumerate(["acq", "tx", "atx", "else", "cfg", "inv", "dfn"])),
        "input interface for SUM_TH and CLK_TX"),
    Reg("ctl", "ITF3", 17, _RAW), Reg("ctl", "ITF4", 18, _RAW), Reg("ctl", "ITF5", 19, _RAW), Reg("ctl", "ITF6", 20, _RAW),
    Reg("ctl", "COI0", 21, _RAW, "PDCs 0-15 in the coincidence"), Reg("ctl", "COI1", 22, _RAW), Reg("ctl", "COI2", 23, _RAW), Reg("ctl", "COI3", 24, _RAW),
    Reg("ctl", "COTH", 25, (_f("num_bank", 0, 3), _f("nch_th", 8, 7)), "coincidence thresholds: hits per PDC, number of PDCs"),
    Reg("ctl", "COIW", 26, (_f("window", 0, 10),), "coincidence window in clock cycles"),
    Reg("ctl", "FSMM", 27, (_f("start_mode", 0, 2), _f("acq_all_pdc", 4), _f("tx_all_pdc", 8)),
        "start_mode 0=disabled, 1=command, 2=timer, 3=bypass (start now)"),
    Reg("ctl", "FACQ", 28, (_f("cmd_mode", 0, 3), _f("overlap", 4, 4), _f("cancel_mode", 8, 7), _f("cancel_send_rstn", 15))),
    Reg("ctl", "FST0", 29, _FSM_STATE, "fast acquisition state"),
    Reg("ctl", "FST1", 30, (_f("n", 0, 8),)),
    Reg("ctl", "SLW0", 31, _FSM_STATE, "slow acquisition state"),
    Reg("ctl", "SLW1", 32, (_f("n", 0, 8), _f("period", 8, 8))),
    Reg("ctl", "ATX0", 33, (_f("cmd_delay", 0, 8), _f("cmd_mode", 8, 3), _f("mode", 11, 2), _f("enable", 15))),
    Reg("ctl", "ATX1", 34, _FSM_CANCEL),
    Reg("ctl", "FTX0", 35, (_f("cmd_delay", 0, 8), _f("mode", 8, 2), _f("cmd_mode", 10), _f("enable", 15))),
    Reg("ctl", "FTX1", 36, _FSM_CANCEL),
    Reg("ctl", "FEND", 37, (_f("delay", 0, 8), _f("mode", 8, 2), _f("enable", 15))),
    Reg("ctl", "TOUT", 38, (_f("period", 0, 10), _f("retry", 12, 2), _f("all_pdc", 14), _f("auto", 15))),
    Reg("ctl", "TRG0", 39, _RAW, "trigger generator: PDCs 0-15"), Reg("ctl", "TRG1", 40, _RAW), Reg("ctl", "TRG2", 41, _RAW), Reg("ctl", "TRG3", 42, _RAW),
    Reg("ctl", "TRGS", 43, (_f("pdc_select", 0, 6), _f("single", 15))),
    Reg("ctl", "TRGH", 44, _RAW, "trigger high period, clock cycles"),
    Reg("ctl", "TRGL", 45, _RAW, "trigger low period, clock cycles"),
    Reg("ctl", "TRGN", 46, (_f("n_cycles", 0, 15), _f("enable", 15)), "bit 15 starts the trigger train"),
    Reg("ctl", "MISC", 47, (_f("pwr_good_byp", 0), _f("pwr_dis", 3), _f("pdc_force_clk", 8), _f("pdc_force_cfg_clk", 9),
                            _f("fen_cfg_clk", 12), _f("fpol_cfg_clk", 13), _f("fen_cfg_data", 14), _f("fpol_cfg_data", 15))),
    Reg("ctl", "PPHS", 48, _RAW), Reg("ctl", "PPHT", 49, _RAW), Reg("ctl", "BPHS", 50, _RAW), Reg("ctl", "BPHT", 51, _RAW),
    Reg("ctl", "PRST", 52, _RAW, "PDC reset lines"),
    Reg("ctl", "AUXI", 53, (_f("ch_sel", 0, 4), _f("rev_pol", 8), _f("func_sel", 12, 4)), "aux input routing"),
    Reg("ctl", "AUXO", 54, _RAW, "aux output; normally set with the `auxOut` app"),
    Reg("ctl", "SCDA", 55, (_f("gbl_ctl_tdc", 0), _f("psd_nfast", 1), _f("psd_ntotal", 2), _f("dgtl_sum_peak", 3),
                            _f("dgtl_sum", 8), _f("flag_cnt", 9), _f("coinc_zpp", 10), _f("flag_zpp", 11)), "controller data in packet A"),
    Reg("ctl", "SPDA", 56, (_f("last", 0), _f("min", 1), _f("max", 2), _f("bin", 3, 2), _f("nul", 5), _f("tot", 6), _f("prd", 7),
                            _f("dgtl_sum", 8), _f("tdc0", 9), _f("tdc1", 10), _f("time_diff", 11), _f("flag_cnt", 12), _f("missed_flag", 13)),
        "PDC data in packet A: dgtl_sum=0x0100 (DSUM), 0x00F7 = ZPP items"),
    Reg("ctl", "SCSA", 57, (_f("ctl_status", 0, 3), _f("pdc_status_all", 12), _f("pdc_status", 13), _f("ctl_cfg", 14), _f("pdc_cfg", 15)),
        "config/status in packet A. ALWAYS written first so the other registers are stored in the HDF5"),
    Reg("ctl", "SCDB", 58, (_f("gbl_ctl_tdc", 0), _f("psd_nfast", 1), _f("psd_ntotal", 2), _f("dgtl_sum_peak", 3),
                            _f("dgtl_sum", 8), _f("flag_cnt", 9), _f("coinc_zpp", 10), _f("flag_zpp", 11))),
    Reg("ctl", "SPDB", 59, (_f("last", 0), _f("min", 1), _f("max", 2), _f("bin", 3, 2), _f("nul", 5), _f("tot", 6), _f("prd", 7),
                            _f("dgtl_sum", 8), _f("tdc0", 9), _f("tdc1", 10), _f("time_diff", 11), _f("flag_cnt", 12), _f("missed_flag", 13))),
    Reg("ctl", "SCSB", 60, (_f("ctl_status", 0, 3), _f("pdc_status_all", 12), _f("pdc_status", 13), _f("ctl_cfg", 14), _f("pdc_cfg", 15))),
    Reg("ctl", "ZPH0", 61, _RAW, "ZPP high period, low 16 bits"), Reg("ctl", "ZPH1", 62, _RAW),
    Reg("ctl", "ZPL0", 63, _RAW, "ZPP low period, low 16 bits"), Reg("ctl", "ZPL1", 64, (_f("high_bits", 0, 15), _f("enable", 15))),
    Reg("ctl", "TMR0", 65, _RAW, "strobe timer, low 16 bits"), Reg("ctl", "TMR1", 66, (_f("high_bits", 0, 15), _f("enable", 15))),
]

REGS: dict[str, Reg] = {r.name: r for r in _PDC_LIST + _CTL_LIST}
PDC_REGS = {r.name: r for r in _PDC_LIST}
CTL_REGS = {r.name: r for r in _CTL_LIST}
assert len(REGS) == len(_PDC_LIST) + len(_CTL_LIST), "register names must be unique"


SPDA_PRESETS = {
    "dsum": dict(dgtl_sum=1),
    "zpp":  dict(last=1, min=1, max=1, bin=2, nul=1, tot=1, prd=1),
}


def pack_reg(name: str, spec) -> int:
    """spec is an int (raw value) or a mapping of field -> value. Handles the OUTD/OUTF `func` shorthand."""
    reg = REGS[name]
    if isinstance(spec, int):
        return spec
    spec = dict(spec)
    if "preset" in spec:
        spec = {**SPDA_PRESETS[spec.pop("preset")], **spec}
    if name in ("OUTD", "OUTF") and "func" in spec:
        f = spec.pop("func")
        spec = {"lo": f, "hi": f, **spec}
    return reg.pack(**spec)


def split_enable_mask(mask: int) -> tuple[int, int]:
    """PDC enable mask -> (low 16 bits, high 16 bits) for PDC0/PDC1, CFG0/CFG1, COI0/COI1, TRG0/TRG1."""
    return mask & 0xFFFF, (mask >> 16) & 0xFFFF


def split_32bit(value: int, enable: bool = True) -> tuple[int, int]:
    """32-bit period -> (low register, high register). Used by ZPH/ZPL and TMR0/TMR1.
    low = value & 0xFFFF, high = (value >> 16) & 0xFFFF, with | 0x8000 on the high register to enable."""
    return value & 0xFFFF, ((value >> 16) & 0xFFFF) | (0x8000 if enable else 0)
