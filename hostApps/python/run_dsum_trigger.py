#!/usr/bin/env python3
"""DSUM triggered by an external input.   python run_dsum_triggered.py [section.key=value ...]"""
from pdcv2_helpers.cli import build_config, parse_args
from pdcv2_helpers.modes.dsum import DsumMode
from pdcv2_helpers.session import PdcSession

cfg = build_config("dsum_triggered", parse_args("dsum_triggered"))
with PdcSession(cfg) as session:
    DsumMode(session).execute()