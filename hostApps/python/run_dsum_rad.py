#!/usr/bin/env python3
"""DSUM with a radiation source and the bench supplies.   python run_dsum_rad.py [section.key=value ...]"""
from pdcv2_helpers.cli import build_config, parse_args
from pdcv2_helpers.modes.dsum import DsumMode
from pdcv2_helpers.session import PdcSession

cfg = build_config("dsum_rad", parse_args("dsum_rad"))
with PdcSession(cfg) as session:
    DsumMode(session).execute()
