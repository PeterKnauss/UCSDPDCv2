"""
Commands used in the Command Line Interface

    overrides     - positional arguments are overrides to config files. Fed in like "section.key=value"
    --set         - same as positional overrides
    --run         - sets custom run config file
    --config-dir  - sets custom config directory
    --batch       - runs batch mode (run.batch_mode)
    --show-config - creates and prints the config then exits without running a test
"""
from __future__ import annotations
import argparse
import sys
import yaml
from .config import ConfigError, load_config


def parse_args(mode: str, argv=None) -> argparse.Namespace:
    """Parses input arguments"""
    p = argparse.ArgumentParser(description=f"PDC run: {mode}", epilog=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("overrides", nargs="*", metavar="section.key=value", help="override one config value for this run")
    p.add_argument("--set", action="append", default=[], metavar="section.key=value", help="same as a positional override")
    p.add_argument("--run", metavar="FILE", help="use this run file instead of configs/run.yaml")
    p.add_argument("--config-dir", metavar="DIR", help="use this folder instead of the package's configs/")
    p.add_argument("--batch", action="store_true", help="no prompts and no figure window (run.batch_mode)")
    p.add_argument("--show-config", action="store_true", help="print the resolved config and exit")
    return p.parse_args(argv)

def build_config(mode: str, args: argparse.Namespace):
    """
    Builds the config by stacking individual configs and applying overrides

    Individual configs go (in order of stacking) hardware < mode < run < overrides
    """
    overrides = list(args.overrides) + list(args.set)
    if args.batch:
        overrides.append("run.batch_mode=true")
    try:
        cfg = load_config(mode, overrides=overrides, run_file=args.run, config_dir=args.config_dir)
    except ConfigError as ex:
        sys.exit(f"ERROR: {ex}")
    if args.show_config:
        print(f"# sources: {', '.join(cfg.sources)}")
        print(yaml.safe_dump(yaml.safe_load(yaml.safe_dump(dict(cfg))), sort_keys=False))
        sys.exit(0)
    return cfg
