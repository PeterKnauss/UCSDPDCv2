"""
pdcv2_helpers -- one initializer for the PDCv2 scripts.

    from pdcv2_helpers import load_config, PdcSession
    from pdcv2_helpers.modes.dsum import DsumMode

    cfg = load_config("dsum_rad", overrides=["run.head_id=48"])
    with PdcSession(cfg) as session:
        DsumMode(session).execute()
"""
from .config import ConfigError, load_config, plan_cfg
from .session import PdcSession

__all__ = ["ConfigError", "load_config", "plan_cfg", "PdcSession"]
