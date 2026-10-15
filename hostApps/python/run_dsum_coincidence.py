#!/usr/bin/env python3
"""DSUM on coincidence.   python run_dsum_coincidence.py [section.key=value ...]"""
from pdcv2_helpers.cli import build_config, parse_args
from pdcv2_helpers.modes.dsum import DsumMode
from pdcv2_helpers.session import PdcSession

cfg = build_config("dsum_coincidence", parse_args("dsum_coincidence"))
with PdcSession(cfg) as session:
    DsumMode(session).execute()
