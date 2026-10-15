"""
session.py -- PdcSession: the connection plus the init sequence shared by all modes.

    with PdcSession(cfg) as session:        # opens the ssh connection to the ZCU102
        DsumMode(session).execute()

What it owns
  client   the ssh client (sshClientFromCfg)
  zynq     zynqDataTransfer       (the data path is started by the mode, see Mode.prepare_data_path)
  icp      initCtlPdcFromClient   (created in initialize())
  plan     build_plan(plan_cfg(cfg)): the ordered register writes, grouped by when they are sent

What initialize() does (the plan groups are named in capitals):
  icp.setSysClkPrd, icp.resetCtl, PACKET, FSM, icp.setDelay, icp.checkPowerGood, icp.setCfgRtnEn,
  icp.preparePDC, icp.nSpad, MODE_CFG, PDC registers, pdcPix --dis, icp.validPdcCfg, PDC_FINAL (OUTC)
The icp.* helpers do the work; the register values come from the plan.
"""
from __future__ import annotations

import time
from .config import Config, plan_cfg
from .paths import RunPaths, resolve_paths
from .plan import build_plan


def section(msg: str) -> None:
    """print a section header"""
    print("")
    print("-" * 50)
    print(f"{msg}")
    print("-" * 50)


class PdcSession:
    def __init__(self, cfg: Config, client=None, icp=None, zynq=None):
        self.cfg = cfg
        self.paths: RunPaths = resolve_paths(cfg)
        self.plan = build_plan(plan_cfg(cfg))
        self.client, self.icp, self.zynq = client, icp, zynq
        self.pdc_setting = None
        self.start_time = time.time()

    def open(self) -> "PdcSession":
        """open a connection with the ZCU102 board"""
        section("open a connection with the ZCU102 board")
        from pdcv2_modules.zynqDataTransfer import zynqDataTransfer, clearHexRead
        import pdcv2_modules.sshClientHelper as sshClientHelper
        if self.cfg["behavior"].get("clear_hexread"):
            clearHexRead()
        self.client = self.client or sshClientHelper.sshClientFromCfg(hostCfgName=self.cfg["hardware"]["zynq"]["ssh_host"])
        section("prepare Zynq platform")
        self.zynq = self.zynq or zynqDataTransfer(sshClientZynq=self.client)
        return self

    def close(self) -> None:
        """stop dataReader and hexRead started by this session"""
        if self.zynq is not None:
            self.zynq.close()
            self.zynq = None

    def __enter__(self) -> "PdcSession":
        return self.open()

    def __exit__(self, *exc) -> bool:
        self.close()
        return False

    def ctl_cmd(self, cmd: str) -> None:
        self.client.runPrint(f"ctlCmd -c {cmd}")

    def prompt(self, message: str) -> None:
        """ask the user to do something by hand. Batch mode only prints it."""
        if self.cfg["run"]["batch_mode"]:
            print(f"(batch mode, not waiting) {message}")
        else:
            input(message)

    @property
    def n_spad(self) -> int:
        n = int(self.cfg["run"]["n_spad"])
        return n if 0 < n <= 4096 else 4096

    def send(self, group: str) -> None:
        """send one group of the plan, in order. Keeps the helper objects in step:
        icp.PACK_A / PACK_B after a packet write, and pdc_setting after a PDC register write."""
        for item in self.plan[group]:
            if isinstance(item, str):
                self.client.runPrint(item)
                if item.startswith("pdcTime") and self.pdc_setting is not None:
                    self.pdc_setting.TIME = self.client.runReturnSplitInt("pdcTime -g")
                continue
            self.client.runPrint(item.command)
            name = item.reg.name
            if item.reg.target == "pdc" and self.pdc_setting is not None and hasattr(self.pdc_setting, name):
                setattr(self.pdc_setting, name, item.value)
            elif name in ("SCSA", "SCDA", "SPDA", "SCSB", "SCDB", "SPDB") and self.icp is not None:
                pack = self.icp.PACK_A if name.endswith("A") else self.icp.PACK_B
                setattr(pack, {"SCS": "SCS", "SCD": "SCD", "SPD": "SPD"}[name[:3]], item.value)

    def initialize(self) -> None:
        cfg = self.cfg
        pdc_en = int(cfg["run"]["pdc_enable"])
        clk = float(cfg["hardware"]["zynq"]["sys_clk_period_ns"]) * 1e-9

        from pdcv2_modules.zynqCtlPdcRoutines import initCtlPdcFromClient
        self.icp = self.icp or initCtlPdcFromClient(client=self.client, sysClkPrd=clk, pdcEn=pdc_en)
        icp = self.icp

        section("set system clock period and reset the controller")
        icp.setSysClkPrd()
        icp.resetCtl()

        section("configure controller packet")
        self.send("packet")

        if self.plan["fsm"]:
            section("configure the Controller FSM")
            self.send("fsm")

        icp.setDelay(signal="CFG_DATA", delay=cfg["hardware"]["zynq"]["cfg_data_delay"])
        icp.checkPowerGood()
        icp.setCfgRtnEn()
        icp.preparePDC()
        icp.nSpad = self.n_spad

        section("configure the PDCs")
        from pdcv2_modules.pdcHelper import pdc_setting
        self.pdc_setting = pdc_setting()
        self.client.runPrint("ctlCmd -c MODE_CFG")
        self.send("pdc")
        self.client.runPrint(f"pdcPix --dis {cfg['behavior'].get('pdc_pix_dis_args', '')}".strip())
        icp.validPdcCfg()
        self.send("pdc_final")
        print("\n=== PDC SETTINGS ===")
        self.pdc_setting.print()
