#!/usr/bin/env python3
"""TCR scan of every SPAD.   python run_tcr.py [section.key=value ...]"""
from pdcv2_helpers.cli import build_config, parse_args
from pdcv2_helpers.modes.tcr import TcrMode
from pdcv2_helpers.session import PdcSession

cfg = build_config("tcr", parse_args("tcr"))
with PdcSession(cfg) as session:
    TcrMode(session).execute()
