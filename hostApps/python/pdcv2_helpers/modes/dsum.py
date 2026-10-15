"""
DsumMode: DSum Acquisition Mode

Order of one run:
    prepare_data_path   Zynq NFS, clean data path, start dataReader, start hexRead, save the config
    session.initialize  (session.py)
    configure           enable SPADs from the TCR file -> MODE_ACQ -> streamManager, interfaces, coincidence, apps
    power_up            (base.py)
    run                 start the FSM, wait meas_time_s seconds
    finish              ramp down, "stop", stop dataReader/hexRead, remove empty files
"""
from __future__ import annotations
import os
import time
from pathlib import Path
from ..config import dump
from ..paths import dsum_csv_dir, dsum_file_name
from ..pixels import apply_dsum_pixels
from ..session import section
from .base import Mode


class DsumMode(Mode):
    def __init__(self, session):
        super().__init__(session)
        self.csv_dir: Path | None = None
        self.csv_file: Path | None = None
        self.stats_file: Path | None = None
        self.analog_only = bool(self.cfg["run"]["analog_only"])
        self.test_stop_time: float | None = None

    def prepare_data_path(self) -> None:
        """Prepare the config file and dumps it to the ZCU"""
        s, cfg = self.session, self.cfg
        b, d = cfg["behavior"], cfg["dsum"]
        zynq = s.zynq

        section("prepare the data path")
        zynq.initNfs()
        zynq.cleanDataPath()
        zynq.initDataReader(dataReaderLaunch=True)

        self.csv_dir = dsum_csv_dir(cfg, s.paths)
        file_name = dsum_file_name(cfg)
        self.csv_file = self.csv_dir / file_name
        self.stats_file = self.csv_file.with_suffix(".txt")
        os.makedirs(self.csv_dir, exist_ok=True)
        print(f"Writing CSV to {self.csv_file}")

        # Start digital return from the zynq
        if not self.analog_only:
            zynq.initHex(autoStart=True, archive=False, printParsed=False, exportH5=bool(b["export_h5"]),
                         hexReadExtraArgs=f"-M dsum -o {self.csv_dir} -f {file_name} "
                                          f"-b {d['bin_idx_mode']} -t {d['data_type']} ")

        section("save configuration values")
        out = dump(cfg, self.csv_file.with_name(self.csv_file.stem + "_config.yaml"))
        print(f"config saved to {out}")

    def configure(self) -> None:
        """Configures the Controller and PDC correctly for DSum"""
        s = self.session
        section("enable PDC SPADs")
        # Deep function that reads in a TCR output file and creates the filemasks and writes them
        apply_dsum_pixels(s, stats_file=self.stats_file,
                          plot_prefix=str(self.csv_file.with_suffix("")))

        section("return PDCs to acquisition mode")
        s.ctl_cmd("MODE_ACQ")

        # Each configuration requires passing a certain group of the plan
        self.stage_send("Configure streamManager to maximize bandwidth", "stream")
        self.stage_send("Configure the Controller interfaces", "interfaces")
        self.stage_send("Configure the Controller coincidence module", "coincidence")
        self.stage_send("Configure the auxiliary inputs and outputs", "zynq_apps")
        self.stage_send("Configure the external outputs", "external")
        self.stage_send("Configure the trigger generators", "trigger_gen")

    def run(self) -> None:
        """Actually run the test"""
        s = self.session
        # Actually start data acquisition
        section("start Controller FSM acquisition")
        if not self.analog_only:
            s.send("start_fsm")

        self.test_start_time = time.time()
        print("\n=== READY TO OPERATE ===")
        meas = int(self.cfg["run"]["meas_time_s"])
        print(f"Measuring for {meas}s")

        # DSum tests collect data for a certain amount of time
        from tqdm import tqdm
        try:
            for _ in tqdm(range(meas)):
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nKeyboard Interrupt: exit program")

    def finish(self) -> None:
        """Finish the test"""
        s = self.session
        self.test_stop_time = time.time()
        super().finish()
        if s.client is not None:
            s.client.runPrint("stop")
        s.close()

        dur = self.test_stop_time - self.test_start_time
        print(f"Test duration:\n  {dur:.3f} seconds \n  {dur / 60:.3f} min \n  {dur / 3600:.3f} hours")

        if self.csv_file is not None and self.csv_file.exists() and self.csv_file.stat().st_size == 0:
            self.csv_file.unlink()
            if self.stats_file is not None and self.stats_file.exists():
                self.stats_file.unlink()
