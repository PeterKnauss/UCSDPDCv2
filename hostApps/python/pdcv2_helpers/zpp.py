"""
zpp.py -- Zero Photon Probability (ZPP) helpers for the UCR/CCR scan of TcrMode.

For one SPAD the Controller ZPP module cuts time into bins of one ZPP period and counts the empty ones (NUL) and the
counts (TOT) over BIN bins. From those:

    TCR = (TOT / BIN) / period                  total count rate, every count
    UCR = -ln(NUL / BIN) / period               uncorrelated count rate (dark counts), from the chance of an empty bin
    CCR = (TCR - UCR) / TCR                     correlated fraction (afterpulsing when one SPAD is on)

Computed by pdcv2_modules.h5Reader.PDC_ZPP.process(). The period has to fit the SPAD: much longer than 1 / TCR and
every bin is hit (NUL = 0, no UCR), much shorter and nearly every bin is empty. period = 1 / (5 * TCR) is used, so a
bin holds 0.2 counts on average.

Method: Frederic Vachon et al. 2021 Meas. Sci. Technol. 32 025105,
"Measuring count rates free from correlated noise in digital silicon photomultipliers"
"""
from __future__ import annotations
import math
from .plan import cmd_set_zpp_prd

# Fewer bins than this cannot give a UCR
MIN_ZPP_BINS = 10
# One bin holds this many counts on average at the optimal period
COUNTS_PER_BIN = 0.2


def zpp_items() -> list:
    """The ZPP values that UCR and CCR are computed from"""
    from pdcv2_modules.h5Reader import PDC_ZPP_ITEM as Z
    return [Z.AVG, Z.BIN, Z.NUL, Z.PRD, Z.TOT]

def set_zpp_module(client, on_s: float, off_s: float) -> None:
    """Sets the ZPP period (bin width) and the low time between bins on the Controller"""
    client.runPrint(cmd_set_zpp_prd(on_s, off_s))

def optimal_period(zpp_list, clk_s: float, n_spad: int = 1) -> float | None:
    """
    ZPP period from a first measurement of the SPAD: the mean TCR of the PDCs that gave data sets the period.
    The period is kept at one clock period or more. None when no PDC counted anything.
    """
    rates = [z.TCR for z in zpp_list if z is not None and z.TCR != -1]
    avg_tcr = sum(rates) / len(rates) if rates else 0
    if avg_tcr <= 0:
        return None
    print(f"  Average total count rate over {len(rates)} PDCs is {avg_tcr:.1f} for {n_spad} SPADs.")
    period = max((1.0 / avg_tcr) * n_spad * COUNTS_PER_BIN, clk_s)
    print(f"  Using ZPP period of {period:.3E} s")
    return period

def cycles_for(period_s: float, n_cycles: int, max_meas_time_s: float | None) -> int:
    """
    Number of ZPP bins to measure: n_cycles, or fewer when n_cycles * period is longer than max_meas_time_s.
    0 when even MIN_ZPP_BINS bins do not fit, which means this SPAD is too slow to measure.
    """
    if max_meas_time_s and period_s * n_cycles > max_meas_time_s:
        n_cycles = int(max_meas_time_s / period_s)
    return n_cycles if n_cycles >= MIN_ZPP_BINS else 0

def clean(value: float) -> float:
    """ZPP values are -1 when they could not be calculated. NaN is what is stored and plotted for those"""
    return float("nan") if value is None or math.isnan(value) or value < 0 else float(value) + 0.0
