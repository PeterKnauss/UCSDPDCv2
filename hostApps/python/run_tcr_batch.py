#!/usr/bin/env python3
"""Batch run of TCR script. Doesnt use CLI"""
from pdcv2_helpers.modes.tcr import TcrMode
from pdcv2_helpers.session import PdcSession
from pdcv2_helpers.config import load_config

for spad_bias in [21, 21.5, 22, 22.5]:
    overrides = [
        "run.batch_mode=true",
        f"run.supply_V.keysight={spad_bias}",
        f"run.run_folder=TCR_101626_{spad_bias}_RT"] 
    cfg = load_config("tcr", overrides=overrides)
    with PdcSession(cfg) as session:
        TcrMode(session).execute()
