"""
tcr.py -- TcrMode: per-SPAD total count rate (TCR).

For every SPAD of every enabled PDC: enable only that SPAD, reset the Controller ZPP module, wait tcr.meas_time_s,
ask for one data packet, read the ZPP average from the HDF5 file. Then identify screamers, save a CSV, and leave only
the PDC configuration (all SPADs off) behind. The CSV is what the DSUM modes read through pixels.tcr_file.

With behavior.ucr_ccr (mode tcr_ucr_ccr) every SPAD is measured with the Zero Photon Probability (ZPP) method instead:
a short measurement sets the ZPP period from the SPAD's own count rate, then a measurement of ucr_ccr.n_zpp_cycles
periods gives the total (TCR), uncorrelated (UCR) and correlated (CCR) count rates. TCR goes through the same screamer
identification and the same CSV (with the UCR, CCR and ZPP columns added), so the file is used by DSUM like any TCR file.

If the scan thread fails, it stops and the error is re-raised in the main thread.
"""
from __future__ import annotations
import datetime
import threading
import time
from enum import IntEnum
import numpy as np
from ..config import dump
from ..paths import bias_str, head_str, run_dir, tag_voltage
from ..session import section
from ..zpp import cycles_for, optimal_period, set_zpp_module, zpp_items
from .base import Mode
from .tcr_plotter import TcrPlotter, TcrUcrCcrPlotter

# Enumerators to make comparing statuses easier
class ScreamerMethod(IntEnum):
    threshold = 0
    average = 1
    percent = 2
    medianFactor = 3
    medianToMin = 4

class LoopingMethod(IntEnum):
    rows_cols = 1
    index = 2


class TcrMode(Mode):
    def __init__(self, session):
        super().__init__(session)
        self.tp: TcrPlotter | None = None
        self.scan_error: BaseException | None = None
        self.meas_time = float(self.cfg["tcr"]["meas_time_s"])
        self.ucr_ccr = bool(self.cfg["behavior"].get("ucr_ccr"))
        self.test_stop_time: float | None = None
        self.tmp_h5: Path | None = None

    def prepare_data_path(self) -> None:
        """Start the Zynq platform. The per-SPAD HDF5 files are read and deleted right away, so they go in a hidden folder inside the run folder"""
        s = self.session
        section("prepare Zynq platform")
        self.tmp_h5 = run_dir(self.cfg, s.paths) / ".tmp_h5"
        self.tmp_h5.mkdir(parents=True, exist_ok=True)
        s.zynq.hexAppOutPathDefault = str(self.tmp_h5)
        s.zynq.init()

    def configure(self) -> None:
        """Start the Zynq Apps"""
        self.stage_send("Configure Controller ZPP module", "zynq_apps")

    def _wait_for_h5(self, timeout_s: float = 10.0):
        """Wait for a new HDF5 file from the Zynq"""
        from pdcv2_modules.h5Reader import h5Reader
        t0 = datetime.datetime.now()
        while True:
            db = h5Reader(deleteAfter=True, hfAbsPath=self.session.zynq.h5Path, hfFile="")
            if db.newFileReady():
                return db
            if datetime.datetime.now() - t0 > datetime.timedelta(seconds=timeout_s):
                raise TimeoutError(f"timeout while waiting for HDF5 data ({timeout_s} seconds)")

    def _select_spad(self, spad_row=None, spad_col=None, spad_index=None) -> None:
        """Enable only this SPAD, by row and column (4096 SPADs) or by index"""
        client = self.session.client
        # Choose which command to run based off what was fed into the function
        if spad_row is not None and spad_col is not None:
            client.runPrint(f"pdcPix --dis --row {spad_row} --col {spad_col} --mode NONE")
        elif spad_index is not None:
            client.runPrint(f"pdcPix --dis --index {spad_index} --mode NONE")
        else:
            print("pixel/SPAD not specified")

    def measure(self, n_pdc, spad_row=None, spad_col=None, spad_index=None) -> list[float]:
        """Measure a single SPAD, reset ZPP, wait, average over each PDC"""
        client = self.session.client
        self._select_spad(spad_row, spad_col, spad_index)

        client.runPrint("ctlCmd -c MODE_ACQ; ctlCmd -c RSTN_ZPP; "
                        f"sleep {self.meas_time:.06f}; ctlCmd -c PACK_TRG_A; ")

        from pdcv2_modules.h5Reader import PDC_ZPP_ITEM
        db = self._wait_for_h5()
        db.h5Open()
        avg = [-1] * n_pdc
        # For each PDC get the ZPP and average over measurement time
        for i_pdc in range(n_pdc):
            zpp = db.getPdcZPP(iPdc=i_pdc, zppSingle=PDC_ZPP_ITEM.AVG)
            if zpp is not None and zpp.AVG != -1:
                avg[i_pdc] = zpp.AVG / self.meas_time
                print(f"  PDC {i_pdc} TCR = {avg[i_pdc]}")
        db.h5Close()
        return avg

    def measure_zpp(self, n_pdc, wait_s: float) -> list:
        """Reset ZPP, wait, read the ZPP values of each PDC and calculate TCR, UCR and CCR. None for a PDC without data"""
        self.session.client.runPrint("ctlCmd -c MODE_ACQ; ctlCmd -c RSTN_ZPP; "
                                     f"sleep {wait_s:.06f}; ctlCmd -c PACK_TRG_A; ")
        db = self._wait_for_h5()
        db.h5Open()
        zpp = [None] * n_pdc
        for i_pdc in range(n_pdc):
            z = db.getPdcZPP(iPdc=i_pdc, zppList=zpp_items())
            if z is not None and z.AVG != -1:
                z.process()
                zpp[i_pdc] = z
        db.h5Close()
        return zpp

    def measure_ucr_ccr(self, n_pdc, spad_row=None, spad_col=None, spad_index=None) -> tuple[list[float], list]:
        """
        Measure a single SPAD with the ZPP method. Returns the TCR of each PDC (-1 without data) and its ZPP values.
        ZPP period = ucr_ccr.zpp_period_s, or when empty 1 / (5 * TCR) of this SPAD from a first tcr.meas_time_s measurement.
        The measurement is n_zpp_cycles periods long, shortened to ucr_ccr.max_meas_time_s. A SPAD with no counts, or too
        slow for MIN_ZPP_BINS periods to fit, keeps the TCR of the first measurement and has no UCR or CCR.
        """
        u = self.cfg["ucr_ccr"]
        clk = self.session.icp.sysClkPrd
        self._select_spad(spad_row, spad_col, spad_index)

        first = None
        if u["zpp_period_s"] is None:
            set_zpp_module(self.session.client, self.meas_time, clk)
            first = self.measure_zpp(n_pdc, self.meas_time)
            period = optimal_period(first, clk)
        else:
            period = float(u["zpp_period_s"])

        n_cycles = cycles_for(period, int(u["n_zpp_cycles"]), u["max_meas_time_s"]) if period else 0
        if n_cycles:
            if n_cycles < int(u["n_zpp_cycles"]):
                print(f"  measuring {n_cycles} ZPP bins instead of {int(u['n_zpp_cycles'])} (ucr_ccr.max_meas_time_s)")
            set_zpp_module(self.session.client, period, clk)
            zpp = self.measure_zpp(n_pdc, period * n_cycles)
        elif first is not None:
            zpp = first
            print("  no UCR/CCR for this SPAD: " + ("no counts" if period is None else
                  f"ZPP period of {period:.3E} s is too long for ucr_ccr.max_meas_time_s"))
        else:
            zpp = [None] * n_pdc
            print("  no UCR/CCR for this SPAD: ucr_ccr.zpp_period_s is too long for ucr_ccr.max_meas_time_s")

        tcr = [z.TCR if z is not None else -1 for z in zpp]
        for i_pdc, z in enumerate(zpp):
            if z is not None:
                ucr = f"{z.UCR:.1f}" if z.UCR >= 0 else "n/a"
                ccr = f"{100 * z.CCR:.2f}%" if z.CCR >= 0 else "n/a"
                print(f"  PDC {i_pdc} TCR = {z.TCR:<10.1f} UCR = {ucr:<10} CCR = {ccr:<8} "
                      f"(NUL = {z.NUL:.0f} BIN = {z.BIN:.0f} PRD = {z.PRD:.0f})")
        return tcr, zpp

    def scan_all_pixels(self, tp: TcrPlotter, update: bool = False) -> None:
        """Iterate over all pixels and run a measurement"""
        import pdcv2_modules.pixMap as pixMap
        icp = self.session.icp
        try:
            # Choose which mapping to run based on 3D vs 2D vs single
            if icp.nSpad == 4096:
                rows, cols, method = range(0, 64), range(0, 64), LoopingMethod.rows_cols
            elif icp.nSpad == 64:
                rows, cols, method = [63], range(0, icp.nSpad), LoopingMethod.rows_cols
            else:
                rows, cols, method = [0], range(0, icp.nSpad), LoopingMethod.index

            for i_row in rows:
                for i_col in cols:
                    if not tp.run:
                        return
                    if method == LoopingMethod.index:
                        idx, row, col, i_spad = i_col, None, None, i_col
                    else:
                        idx, row, col = None, i_row, i_col
                        i_spad = pixMap.idx_map(y=row, x=col) if icp.nSpad == 4096 else i_col
                    if self.ucr_ccr:
                        avg, zpp = self.measure_ucr_ccr(tp.nPdcMax, spad_index=idx, spad_row=row, spad_col=col)
                    else:
                        avg, zpp = self.measure(tp.nPdcMax, spad_index=idx, spad_row=row, spad_col=col), [None] * tp.nPdcMax
                    for i_pdc in range(tp.nPdcMax):
                        tp.newData(iPdc=i_pdc, iSpad=i_spad, avg=avg[i_pdc], zpp=zpp[i_pdc])
                    tp.current_pixel_index = i_spad
                    if update:
                        tp.updatePlot()
        except BaseException as ex:
            self.scan_error = ex
            tp.run = False
        finally:
            tp.done_test_all_pixels = True

    def _thresholds(self, tp: TcrPlotter, sc: dict) -> np.ndarray:
        """Establish thresholds based on screamer settings"""
        icp = self.session.icp
        table = np.zeros((len(ScreamerMethod), icp.nPdcMax))
        for i_pdc in range(icp.nPdcMax):
            if not tp.pdcValid[i_pdc]:
                continue
            table[ScreamerMethod.threshold][i_pdc] = float(sc["threshold"])
            tp.getSpadEnFromThreshold(i_pdc, threshold=table[ScreamerMethod.threshold][i_pdc], methodStr="(fixed)")
            table[ScreamerMethod.average][i_pdc] = tp.getPerSpadAvgTcr(i_pdc)
            tp.getSpadEnFromThreshold(i_pdc, threshold=table[ScreamerMethod.average][i_pdc], methodStr="(average)")
            pct = float(sc["percent"])
            table[ScreamerMethod.percent][i_pdc] = tp.getClosestPctPop(i_pdc, percent=pct)
            tp.getSpadEnFromThreshold(i_pdc, threshold=table[ScreamerMethod.percent][i_pdc], methodStr=f"({pct}%)")
            factor = float(sc["factor"])
            table[ScreamerMethod.medianFactor][i_pdc] = tp.getSpadMedTcr(i_pdc) * factor
            tp.getSpadEnFromThreshold(i_pdc, threshold=table[ScreamerMethod.medianFactor][i_pdc],
                                      methodStr="(factor to median)")
            median = tp.getSpadMedTcr(i_pdc)
            table[ScreamerMethod.medianToMin][i_pdc] = 2.0 * median - min(tp.spadTcr[i_pdc])
            tp.getSpadEnFromThreshold(i_pdc, threshold=table[ScreamerMethod.medianToMin][i_pdc],
                                      methodStr="(distance from median to min)")
            print("")
        return table

    def run(self) -> None:
        """Actually run the test"""
        import matplotlib.pyplot as plt
        s, cfg = self.session, self.cfg
        icp, client = s.icp, s.client
        r = cfg["run"]
        self.test_start_time = time.time()

        # Start the acquisition
        section("start the FSM (command triggered)")
        s.send("fsm_command")

        data_dir = run_dir(cfg, s.paths)
        plotter = TcrUcrCcrPlotter if self.ucr_ccr else TcrPlotter
        self.tp = tp = plotter(figName="TCR PLOTTER", nPdcMax=icp.nPdcMax, nSpad=icp.nSpad,
                               data_path=data_dir, meas_time_s=self.meas_time,
                               head_str=head_str(r.get("head_id")), bias_str=bias_str(tag_voltage(r)),
                               name=r.get("name") or "", doSavePlot=False)
        try:
            section("Loop for each SPAD to measure its TCR")
            thread = threading.Thread(target=self.scan_all_pixels, args=[tp])
            thread.start()
            while not tp.done_test_all_pixels:
                tp.updatePlot()
            thread.join()
            if self.scan_error is not None:
                raise self.scan_error
            tp.updatePlot()

            if r["save_plot"]:
                tp.savePlot()

            section("Estimate the TCR of the array (all pixels)")
            for i_pdc in range(icp.nPdcMax):
                if tp.pdcValid[i_pdc]:
                    n = tp.countValidSpads(i_pdc)
                    print(f"  PDC {i_pdc} total TCR = {tp.pdcTcrAll[i_pdc]: <8} "
                          f"({tp.getPerSpadAvgTcr(i_pdc): <8.01f} per SPAD for {n} SPADs)")

            if self.ucr_ccr:
                section("Median TCR, UCR and CCR of the SPADs")
                for i_pdc in range(icp.nPdcMax):
                    if tp.pdcValid[i_pdc]:
                        print(f"  PDC {i_pdc} {tp.summary(i_pdc)}")

            section("Identify the screamer pixels")
            sc = cfg["tcr"]["screamer"]
            table = self._thresholds(tp, sc)

            section("Estimate the TCR of the array (no screamers)")
            name = "threshold" if sc["method"] == "constant" else sc["method"]
            method = getattr(ScreamerMethod, name)
            print(f"selected method is {method.name}")
            for i_pdc in range(icp.nPdcMax):
                if not tp.pdcValid[i_pdc]:
                    continue
                th = table[method][i_pdc]
                tp.getSpadEnFromThreshold(i_pdc, threshold=th, methodStr=method.name, addToScatter=True, doPrint=False)
                n = tp.countEnabledSpads(i_pdc)
                print(f"  PDC {i_pdc} total TCR = {tp.pdcTcrNS[i_pdc]: <8} "
                      f"({tp.getPerSpadAvgTcr(i_pdc, False): <8.01f} per SPAD for {n} SPADs at threshold = {th})")

            tp.updateLegend()
            tp.pausePlot(pauseTime=0.001)
            tp.saveData()

            section("Enable the selected SPADs")
            for i_pdc in range(icp.nPdcMax):
                if not tp.pdcValid[i_pdc]:
                    continue
                if tp.nSpad <= 64:
                    client.runPrint(f"pdcSpad --dis --pattern 0x{tp.getSpadPattern(i_pdc):016x} "
                                    f"--spdc {i_pdc} --mode NONE")
                else:
                    client.runPrint(f"pdcPix --dis --spdc {i_pdc} --mode NONE")
            client.runPrint("ctlCfg -a CFGS -r 0x0000 -g")

            self.test_stop_time = time.time()
            print(f"Test took {self.test_stop_time - self.test_start_time:.3f} seconds")
            if not r["batch_mode"]:
                print("Test completed, to exit, close figure")
                plt.show(block=True)
                print("\nFigure closed... exit program")
        except (KeyboardInterrupt, SystemExit) as ex:
            tp.run = False
            if "thread" in locals():
                thread.join()
            print("\nKeyboard Interrupt: exit program" if isinstance(ex, KeyboardInterrupt)
                  else "\nProgram interrupted: exit program")

    def finish(self) -> None:
        """Finish the run"""
        s, cfg = self.session, self.cfg
        if self.tp is not None:
            self.tp.closePlot()
        super().finish()
        s.close()
        if self.tmp_h5 is not None:
            try:
                self.tmp_h5.rmdir()   # only removes it when empty, leftover files are kept
            except OSError:
                pass
        if self.tp is not None:
            section("Save configuration values")
            out = self.tp.dataPath / f"{self.tp.getFileName()}{self.tp.name}_config.yaml"
            print(f"config saved to {dump(cfg, out)}")
        if self.test_stop_time is None:
            self.test_stop_time = time.time()
            print(f"Test took {self.test_stop_time - self.test_start_time:.3f} seconds")
