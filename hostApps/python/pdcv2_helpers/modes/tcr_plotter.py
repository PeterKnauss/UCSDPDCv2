"""tcr_plotter.py -- the live TCR figure and its data."""
from __future__ import annotations

import datetime
import os
import statistics
import warnings
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

from pdcv2_modules.fgColors import fgColors


class TcrPlotter:
    def __init__(self, figName, nPdcMax, nSpad, data_path, meas_time_s, head_str="", bias_str="", name="",
                 doSavePlot=False, doSaveGif=False):

        """
        create an empty object with no data, but with figure properly formatted
        """
        self.figName = figName
        self.nPdcMax = nPdcMax
        self.nSpad = nSpad

        self.pdcValid = [False]*self.nPdcMax

        self.current_pixel_index = -1
        self.done_test_all_pixels = False
        self.run = True

        self.pdcTcrAll = [0]*self.nPdcMax
        self.pdcTcrNS = [0]*self.nPdcMax
        self.spadIdx = range(0, self.nSpad)
        self.spadTcr = [[0]*self.nSpad for iPdc in range(self.nPdcMax)]
        self.spad100 = [[] for iPdc in range(self.nPdcMax)]
        self.spadPop = [[] for iPdc in range(self.nPdcMax)]

        self.spadCumul100 = []
        self.spadCumulPop = []

        self.spadEn  = [[0]*self.nSpad for iPdc in range(self.nPdcMax)]
        self.spadValid = [[False]*self.nSpad for iPdc in range(self.nPdcMax)]

        self.axTcr = 0
        self.axPop = 1

        self.dataFileName = ""
        self.doSavePlot = doSavePlot
        self.doSaveGif = doSaveGif

        self.plotIdx = 0
        self.fig = None
        self.dateStrPlot = datetime.datetime.now().strftime("%Y%m%d_%Hh%Mm%S")
        self.name = f"_{name}" if name else ""
        self.measTime = meas_time_s
        self.headStr = head_str
        self.spadBiasStr = bias_str
        self.saveTime = None

        self.dataPath = Path(data_path)

        self.plotPath = Path(os.path.join(self.dataPath, 'PNG'))
        self.plotGifPath = Path(os.path.join(self.plotPath, self.dateStrPlot))

        self.initPlot()

    def initPlot(self):
        """
        create properly formatted plot
        """
        plt.close('all')
        plt.ion()
        self.fig, self.axes = plt.subplots(nrows=1, ncols=2,
                                           figsize=(16,9), constrained_layout=True,
                                           num=self.figName)
        self.fig.get_layout_engine().set(w_pad=0.1, h_pad=0.1, hspace=0.05, wspace=0.05)

        self.colors = plt.rcParams['axes.prop_cycle'].by_key()['color']

        self.hscatterTcr = [None]*self.nPdcMax
        self.linePopu = [None]*(self.nPdcMax+1)
        self.label = [""]*self.nPdcMax
        for iPdc in range(self.nPdcMax):
            self.label[iPdc] = f"PDC{iPdc}"
            self.hscatterTcr[iPdc] = self.axes.flat[self.axTcr].scatter(self.spadIdx,
                                                                        self.spadTcr[iPdc],
                                                                        facecolors='none',
                                                                        edgecolors=self.colors[iPdc],
                                                                        linewidth=1.5,
                                                                        label=self.label[iPdc])
            self.linePopu[iPdc] = (self.axes.flat[self.axPop].plot(self.spad100[iPdc],
                                                                   self.spadPop[iPdc],
                                                                   label=self.label[iPdc]))[0]
        self.lineCumulLabel = f"All PDCs"
        self.lineCumul = (self.axes.flat[self.axPop].plot(self.spadCumul100,
                                                          self.spadCumulPop,
                                                          label=self.lineCumulLabel,
                                                          linewidth=2.0))[0]
        self.lineCumulAvgLabel = f"{'All PDCs': <12} {'avg': <14}"
        self.lineCumulAvg = (self.axes.flat[self.axPop].plot([-1, 101], [0, 0], '--',
                                                             label=self.lineCumulAvgLabel,
                                                             linewidth=2.0))[0]
        self.lineCumulMedLabel = f"{'All PDCs': <12} {'': <17} {'med': <14}"
        self.lineCumulMed = (self.axes.flat[self.axPop].plot([-1, 101], [0, 0], '--',
                                                             label=self.lineCumulMedLabel,
                                                             linewidth=2.0))[0]

        self.axes.flat[self.axTcr].title.set_text("TCR as a function of the SPAD index")
        self.axes.flat[self.axTcr].set_xlabel("PDC Index")
        self.axes.flat[self.axTcr].set_ylabel(f"TCR over {self.measTime}s")
        self.axes.flat[self.axPop].title.set_text("Histogram of TCR")
        self.axes.flat[self.axPop].set_xlabel("Percent of SPADS with TCR < y value")
        self.axes.flat[self.axPop].set_ylabel(f"TCR over {self.measTime}s")

        self.updateLegend()

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self.axes.flat[self.axTcr].set_yscale('log')
            self.axes.flat[self.axPop].set_yscale('log')

        if self.nSpad <= 64:
            self.axes.flat[self.axTcr].set_xticks(np.arange(0, 65, 8))
            self.axes.flat[self.axTcr].xaxis.set_minor_locator(mticker.MultipleLocator(1))
        else:
            self.axes.flat[self.axTcr].set_xticks(np.arange(0, 4097, 500))
            self.axes.flat[self.axTcr].set_xlim(-100, 4200)
            self.axes.flat[self.axTcr].xaxis.set_minor_locator(mticker.MultipleLocator(100))
        self.axes.flat[self.axTcr].tick_params(which="both", direction="in", top=True, right=True)

        self.axes.flat[self.axPop].set_xticks(np.arange(0, 101, 10))
        self.axes.flat[self.axPop].set_xlim(-5, 105)
        self.axes.flat[self.axPop].xaxis.set_minor_locator(mticker.MultipleLocator(5))
        self.axes.flat[self.axPop].tick_params(which="both", direction="in", top=True, right=True)
        self.axes.flat[self.axPop].grid(visible=True, which="both", alpha=0.2)
        self.axes.flat[self.axPop].set_axisbelow(True)

        set_lim(self.axes.flat[self.axTcr], self.spadTcr)
        set_lim(self.axes.flat[self.axPop], self.spadPop)

    def closePlot(self):
        plt.close()

    def updateLegend(self):
        """
        show/update legends with proper parameters
        """
        self.axes.flat[self.axTcr].legend()
        self.axes.flat[self.axPop].legend(loc="upper left", title=f"{'': <26} {'avg': <14} {'med': <14}")

    def updatePlot(self, iPdc=None):
        """
        set new data on the plot without stealing the focus
        """
        if self.current_pixel_index >= 0:
            if iPdc == None:
                pdcRange = range(self.nPdcMax)
            else:
                pdcRange = [iPdc]

            for iPdc in pdcRange:
                if not self.pdcValid[iPdc]:
                    self.hscatterTcr[iPdc].set_label(s='')
                    self.linePopu[iPdc].set_label(s='')

                else:
                    self.hscatterTcr[iPdc].set_label(s=self.label[iPdc])
                    scatterMax = min(len(self.spadIdx), len(self.spadTcr[iPdc]))
                    self.hscatterTcr[iPdc].set_offsets(np.c_[self.spadIdx[:scatterMax], self.spadTcr[iPdc][:scatterMax]])

                    avg = np.mean(self.spadPop[iPdc])
                    med = statistics.median(self.spadPop[iPdc])
                    self.linePopu[iPdc].set_label(s=f"{self.label[iPdc]: <12} {avg: <12.1f} {med: <12.1f}")
                    popMax = min(len(self.spad100[iPdc]), len(self.spadPop[iPdc]))
                    self.linePopu[iPdc].set_data(np.array(self.spad100[iPdc][:popMax]),
                                                np.array(self.spadPop[iPdc][:popMax]))

            avg = np.mean(self.spadCumulPop)
            med = statistics.median(self.spadCumulPop)
            self.lineCumul.set_label(s=f"{self.lineCumulLabel: <12} {avg: <12.1f} {med: <12.1f}")
            cumulIdx = min(len(self.spadCumul100), len(self.spadCumulPop))
            self.lineCumul.set_data(np.array(self.spadCumul100[:cumulIdx]),
                                    np.array(self.spadCumulPop[:cumulIdx]))
            avgCumul = np.mean(self.spadCumulPop)
            self.lineCumulAvg.set_ydata([avgCumul, avgCumul])
            medCumul = statistics.median(self.spadCumulPop)
            self.lineCumulMed.set_ydata([medCumul, medCumul])

            set_lim(self.axes.flat[self.axTcr], self.spadTcr)
            set_lim(self.axes.flat[self.axPop], self.spadPop)

        self.updateLegend()
        self.pausePlot(pauseTime=0.001)
        if self.doSavePlot:
            self.savePlot(iPdc=iPdc)
        if self.doSaveGif:
            self.savePlot(iPdc=iPdc, doSaveGif=True)
        self.checkExit()


    def newData(self, iPdc, iSpad, avg):
        """
        add new data to the class
        """
        if avg < 0:
            self.pdcValid[iPdc] = False
            return
        self.pdcValid[iPdc] = True
        self.spadValid[iPdc][iSpad] = True

        self.pdcTcrAll[iPdc] += avg
        self.spadTcr[iPdc][iSpad] = avg
        self.spadPop[iPdc].append(avg)
        self.spadPop[iPdc].sort()
        self.spad100[iPdc] = np.linspace(0, 100.0, len(self.spadPop[iPdc]))

        self.spadCumulPop.append(avg)
        self.spadCumulPop.sort()
        self.spadCumul100 = np.linspace(0, 100.0, len(self.spadCumulPop))


    def countValidSpads(self, iPdc):
        """
        count the number of valid SPADs for a given PDC.
        To be valid, a SPAD must have a ZPP packet associated to it.
        """
        return self.spadValid[iPdc].count(True)

    def countEnabledSpads(self, iPdc):
        """
        return the number of enabled SPADs
        """
        return self.spadEn[iPdc].count(1)

    def getPerSpadAvgTcr(self, iPdc, screamersEnabled=True):
        """
        get the average TCR per SPAD using total TCR
        divided by the number of valid/enabled SPADs
        """
        if not self.pdcValid[iPdc]:
            return 0
        if screamersEnabled:
            return self.pdcTcrAll[iPdc]/(1.0*self.countValidSpads(iPdc))
        else:
            return self.pdcTcrNS[iPdc]/(1.0*self.countEnabledSpads(iPdc))

    def getSpadMedTcr(self, iPdc):
        """
        get the median TCR value
        """
        return statistics.median(self.spadTcr[iPdc])

    def getClosestPctPop(self, iPdc, percent):
        """
        get the TCR value closest to the specified percentage in the population
        """
        lst = self.spad100[iPdc]
        return self.spadPop[iPdc][min(range(len(lst)), key = lambda i: abs(lst[i]-percent))]

    def getSpadEnFromThreshold(self, iPdc, threshold, methodStr="",
                               doPrint=True, addToScatter=False):
        """
        From a given count rate threshold, detect if a SPAD must be enabled or not
        """
        self.pdcTcrNS[iPdc] = 0
        for iSpad in range(0, self.nSpad):
            if self.spadValid[iPdc][iSpad] and self.spadTcr[iPdc][iSpad] <= threshold:
                self.spadEn[iPdc][iSpad] = 1
                self.pdcTcrNS[iPdc] += self.spadTcr[iPdc][iSpad]
            else:
                self.spadEn[iPdc][iSpad] = 0

        nSpadEnabled = self.countEnabledSpads(iPdc=iPdc)
        nSpadDisabled = self.nSpad - nSpadEnabled
        if doPrint:
            print(f"  PDC {iPdc} disabled {nSpadDisabled} SPAD with threshold of {threshold:.01f} {methodStr}")

        if addToScatter:
            self.axes.flat[self.axTcr].plot((min(self.spadIdx), max(self.spadIdx)),
                                             (threshold, threshold), "--",
                                             color=self.colors[iPdc],
                                             label=f"PDC{iPdc} th ({threshold})")

        return nSpadEnabled, self.spadEn[iPdc]

    def getSpadPattern(self, iPdc):
        """
        get an hexadecimal pattern to enable SPADs.
        Works only for less then 64 SPADs with app pdcSpad.
        """
        pattern = 0;
        if self.nSpad <= 64 and self.pdcValid[iPdc]:
            for iSpad in range(0, self.nSpad):
                if self.spadEn[iPdc][iSpad]:
                    pattern += (0x1<<iSpad)
        return pattern


    def getSpadRegister(self, iPdc):
        """
        get a list of registers to enable SPADs.
        """
        registerList = [0]*256
        if self.pdcValid[iPdc]:
            for iSpad in range(0, self.nSpad):
                if self.spadEn[iPdc][iSpad]:
                    addr = int(np.floor(iSpad/16))
                    registerList[addr] += (0x1<<(iSpad-16*addr))

        return registerList


    def getFileName(self):
        if self.dataFileName == "":
            dateStr=datetime.datetime.now().strftime("%Y%m%d_%Hh%Mm%S")
            self.dataFileName = f"{dateStr}_TCR_{self.headStr}{int(self.measTime*1000):d}ms{self.spadBiasStr}"
        return self.dataFileName


    def saveData(self):
        """
        save data to a CSV file
        """

        dateStr=datetime.datetime.now().strftime("%Y%m%d_%Hh%Mm%S")
        if self.saveTime == None:
            self.saveTime = dateStr
        pdcStr=""
        df = pd.DataFrame()
        for iPdc in range(0, self.nPdcMax):
            if self.pdcValid[iPdc]:
                pdcStr+=f"_PDC{iPdc}"

                dfNew = pd.DataFrame(data=self.spadIdx, columns=[f"SPAD_idx{iPdc}"])
                df = pd.concat([df, dfNew], axis=1)
                dfNew = pd.DataFrame(data=self.spadTcr[iPdc], columns=[f"SPAD_TCR{iPdc}"])
                df = pd.concat([df, dfNew], axis=1)
                dfNew = pd.DataFrame(data=self.spad100[iPdc], columns=[f"SPAD_percent{iPdc}"])
                df = pd.concat([df, dfNew], axis=1)
                dfNew = pd.DataFrame(data=self.spadPop[iPdc], columns=[f"SPAD_distribution{iPdc}"])
                df = pd.concat([df, dfNew], axis=1)

        if df.size > 0:
            filename = f"{self.getFileName()}{pdcStr}{self.name}.csv"
            self.dataPath.mkdir(parents=True, exist_ok=True)
            datafile = os.path.join(self.dataPath, filename)
            print(f"{fgColors.green}Saving data to file {datafile}{fgColors.endc}")
            df.to_csv(datafile, sep=';', index=False, float_format="%.3E")

    def savePlot(self, iPdc=None, doSaveGif=False):
        """
        save plot to a png file
        """
        if (self.fig):
            if iPdc == None or self.pdcValid[iPdc]:
                filename = f"TCR_{self.plotIdx:06d}{self.name}.png"
                self.plotPath.mkdir(parents=True, exist_ok=True)
                datafile = os.path.join(self.plotPath, filename)
                print(f"{fgColors.green}Saving plot to file {datafile}{fgColors.endc}")

            if iPdc == None:
                pdcStr = ""
                for iPdc in range(0, self.nPdcMax):
                    if self.pdcValid[iPdc]:
                        pdcStr+=f"_PDC{iPdc}"
            else:
                pdcStr=f"_PDC{iPdc}"
            filename = f"{self.getFileName()}{pdcStr}_{self.plotIdx:06d}{self.name}.png"
            self.plotPath.mkdir(parents=True, exist_ok=True)
            if doSaveGif:
                datafile = os.path.join(self.plotPathGif, filename)
            else:
                datafile = os.path.join(self.plotPath, filename)
            print(f"saving plot to file {datafile}")
            self.fig.savefig(datafile)
            self.plotIdx += 1

    def checkExit(self):
        """
        check figure by name if it still exists
        """
        if not plt.fignum_exists(self.figName):
            print("\nFigure closed...")
            raise SystemExit


    def pausePlot(self, pauseTime=0.001):
        """
        let user interact with a plot while waiting for new data
        """
        self.fig.canvas.draw_idle()
        self.fig.canvas.start_event_loop(pauseTime)


def set_lim(ax, data):
    """
    set the limit on ax based on the values
    """
    dataFlatValid = [val for data1D in data for val in data1D if val > 0]
    if len(dataFlatValid) == 0:
        return

    yMin = min(dataFlatValid)/2.0
    yMax = max(dataFlatValid)*2.0
    if (yMin != yMax):
        ax.set_ylim(yMin, yMax)

