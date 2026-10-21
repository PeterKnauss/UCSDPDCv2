"""
DsumMode: DSum Acquisition Mode

Order of one run:
    prepare_data_path   Zynq NFS, clean data path, start dataReader, start hexRead, save the config
    session.initialize  (session.py)
    configure           enable SPADs from the TCR file -> MODE_ACQ -> streamManager, interfaces, coincidence, apps
    power_up            (base.py)
    run                 start the FSM, wait meas_time_s seconds, stop the FSM, wait until the data is in the csv
    finish              ramp down, "stop", stop dataReader/hexRead, remove empty files

The FSM is stopped before the supplies ramp down, so the file holds only the measurement and none of the ramp down.
"""
from __future__ import annotations
import os
import time
from pathlib import Path
from ..config import dump
from ..paths import dsum_file_name, run_dir
from ..pixels import apply_dsum_pixels
from ..session import section
from .base import Mode

# After the FSM is stopped, wait this long on top of the streamManager timeout (it sends the last partial packet when
# it times out), then wait for hexRead to parse the remaining .hex files, for at most FLUSH_TIMEOUT_S
FLUSH_MARGIN_S = 0.5
FLUSH_TIMEOUT_S = 30.0


class DsumMode(Mode):
    def __init__(self, session):
        super().__init__(session)
        self.run_dir: Path | None = None
        self.csv_file: Path | None = None
        self.stats_file: Path | None = None
        self.analog_only = bool(self.cfg["run"]["analog_only"])
        self.test_stop_time: float | None = None
        self._fsm_started = False
        self._acq_stopped = False

    def prepare_data_path(self) -> None:
        """Prepare the config file and dumps it to the ZCU"""
        s, cfg = self.session, self.cfg
        b, d = cfg["behavior"], cfg["dsum"]
        zynq = s.zynq

        section("prepare the data path")
        zynq.initNfs()
        zynq.cleanDataPath()
        zynq.initDataReader(dataReaderLaunch=True)

        self.run_dir = run_dir(cfg, s.paths)
        file_name = dsum_file_name(cfg)
        self.csv_file = self.run_dir / file_name
        self.stats_file = self.csv_file.with_suffix(".txt")
        os.makedirs(self.run_dir, exist_ok=True)
        # hexRead has two output paths: the general one (-o, used for the h5) and the dsum module one (-o after -M dsum,
        # used for the csv). Both point at the run folder so the csv and h5 end up together.
        zynq.hexAppOutPathDefault = str(self.run_dir)
        print(f"Writing CSV to {self.csv_file}")

        # Start digital return from the zynq
        if not self.analog_only:
            zynq.initHex(autoStart=True, archive=False, printParsed=False, exportH5=bool(b["export_h5"]),
                         hexReadExtraArgs=f"-M dsum -o {self.run_dir} -f {file_name} "
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
        # Actually start data acquisition. The clock starts before the FSM does, so the time sending the command takes
        # counts toward meas_time_s
        section("start Controller FSM acquisition")
        self.test_start_time = time.time()
        if not self.analog_only:
            s.send("start_fsm")
            self._fsm_started = True
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

        # End of the measurement: stop the FSM and write the data before anything else happens (also after Ctrl-C)
        self.test_stop_time = time.time()
        self.stop_acquisition()

    def stop_acquisition(self) -> None:
        """Stops the FSM and waits until the frames already taken are in the csv. Safe to call twice"""
        if not self._fsm_started or self._acq_stopped:
            return
        self._acq_stopped = True
        section("stop Controller FSM acquisition and write the data")
        self.session.send("stop_fsm")
        self._flush_data()

    def _flush_data(self) -> None:
        """Waits for the last packet to leave streamManager, then for hexRead to parse every .hex file"""
        z = self.session.zynq
        if z is None:
            return
        apps = self.cfg["controller"].get("apps", {})
        timeout_s = float(apps.get("stream_manager", {}).get("timeout_s", 1))
        print(f"Waiting {timeout_s + FLUSH_MARGIN_S:g} s for the last packet")
        time.sleep(timeout_s + FLUSH_MARGIN_S)
        t_end = time.time() + FLUSH_TIMEOUT_S
        while not z.doneParsingHex():
            if time.time() > t_end:
                print(f"WARNING: hexRead was still parsing after {FLUSH_TIMEOUT_S:g} s. The end of the data may be missing")
                return
            time.sleep(0.2)
        time.sleep(FLUSH_MARGIN_S)
        print("Data written")

    def finish(self) -> None:
        """Finish the test"""
        s = self.session
        if self.test_stop_time is None:
            self.test_stop_time = time.time()
        # run() normally stopped the FSM already. This catches an error or Ctrl-C before that. The ramp down always follows
        try:
            self.stop_acquisition()
        except Exception as ex:
            print(f"WARNING: could not stop the acquisition before the ramp down: {ex}")
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
