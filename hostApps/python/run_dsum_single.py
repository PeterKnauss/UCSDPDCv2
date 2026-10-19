#!/usr/bin/env python3
"""DSUM triggered by a single photon on any PDC.   python run_dsum_single.py [section.key=value ...]"""
from pdcv2_helpers.cli import build_config, parse_args
from pdcv2_helpers.modes.dsum import DsumMode
from pdcv2_helpers.session import PdcSession

cfg = build_config("dsum_single", parse_args("dsum_single"))
with PdcSession(cfg) as session:
    DsumMode(session).execute()
