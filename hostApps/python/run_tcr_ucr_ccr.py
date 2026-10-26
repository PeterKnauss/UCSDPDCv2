#!/usr/bin/env python3
"""TCR, UCR and CCR scan of every SPAD (ZPP method).   python run_tcr_ucr_ccr.py [section.key=value ...]"""
from pdcv2_helpers.cli import build_config, parse_args
from pdcv2_helpers.modes.tcr import TcrMode
from pdcv2_helpers.session import PdcSession

cfg = build_config("tcr_ucr_ccr", parse_args("tcr_ucr_ccr"))
with PdcSession(cfg) as session:
    TcrMode(session).execute()
