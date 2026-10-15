#----------------------------------------------------------------------------------
#-- Company: GRAMS
#-- Designer: Tommy Rossignol
#--
#-- Create Date: 2025-09-11
#-- Description:
#--     module with functions to enable/disable the SPAD
#--
#-- Dependencies:
#-- Revision:
#-- Revision 1.0 - File Created
#-- Additional Comments:
#----------------------------------------------------------------------------------
import os
import numpy as np
from enum import IntEnum
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors

import pdcv2_modules.pixMap as pixMap



# class to define the different methods to find which pixels to enable
class ThreshMethod(IntEnum):
    constant=0,
    average=1,
    percent=2,
    medianFactor=3,
    medianToMin=4
    # TBD implement extra methods


# class to define the threshold operator
class ThreshOp(IntEnum):
    lt = 0, # less than
    le = 1, # less or equal to
    eq = 2, # equal to
    ge = 3, # greater or equal to
    gt = 4  # greater than


class EnabledPixelAnalysis():
    # method parameters
    hMethod: ThreshMethod
    thOp: ThreshOp
    thConst : float
    thPct : float
    thMedFactor : float
    thresh : float

    # pixels to enable
    pixToEnable : np.ndarray

    # number of pixels to enable
    numPixToEnable : int = 0
    pctPixToEnable : float = 0.0

    # statistics
    totalAllPix : float = 0.0
    totalDisabled : float = 0.0

    @property
    def pctEnabled(self):
        return self.numPixToEnable/pixMap.TOP_N_PIX

    @property
    def totalAllPixPerPix(self):
        return self.totalAllPix/pixMap.TOP_N_PIX

    @property
    def totalDisabledPerPix(self):
        return self.totalDisabled/self.numPixToEnable

    @property
    def pctTotal(self):
        return self.totalDisabled/self.totalAllPix

    @property
    def pctPerPix(self):
        return self.totalDisabledPerPix/self.totalAllPixPerPix

def getScreamerValue(method):
    if method == "constant":
        value = float(os.getenv("SCREAMER_THRESHOLD", default=100.0))
        arg = "thConst"
    elif (method == "average") or (method == "medianToMin"):
        #pdcSpadFunctions.convertPixArrayToReg computes necessary values - don't need to pass anything
        return None
    elif method == "percent":
        value = float(os.getenv("SCREAMER_PERCENT", default = 90.0))
        arg = "thPct"
    elif method == "medianFactor":
        value = float(os.getenv("SCREAMER_FACTOR", default = 1.5))
        arg = "thMedFactor"
    else:
        print(f"{fgColors.bYellow}WARNING: Cannot get screamer value for method {method}. Using 'constant' method with threshold of 100 {fgColors.endc}")
        arg = "thConst"
        value = 100.0
    argDict = {arg:value}
    return argDict

def convertPixArrayToReg(
                            pixArray, # array or list containing 4096 pixel values
                            thMethod: ThreshMethod,
                            thOp: ThreshOp = ThreshOp.le,
                            thConst: float = -1.0,     # only used with ThreshMethod.constant
                            thPct: float = -1.0,       # only used with ThreshMethod.percent
                            thMedFactor: float = -1.0, # only used with ThreshMethod.medianFactor
                            pixEnMask = None,          # mask to apply to the pixel enable
                            plot = "",              # show a plot of the pixels to enable
                            log = False,               # print the registers when set to True
                            returnAnalysis = False     # return the analysis class
                        ) -> np.array:
    # validate input parameters
    if (isinstance(pixArray, np.ndarray) and
            np.shape(pixArray) == (pixMap.TOP_NX_PIX, pixMap.TOP_NY_PIX)):
        # 2D array
        pixArray = pixMap.xymap2vect(pixArray)
    if len(pixArray) != pixMap.TOP_N_PIX:
        raise ValueError("pixArray must contain exactly 4096 elements")

    # create a class to contain the analysis parameters
    pixAnalysis = EnabledPixelAnalysis()
    pixAnalysis.thMethod = thMethod
    pixAnalysis.thOp = thOp
    pixAnalysis.thConst = thConst
    pixAnalysis.thPct = thPct
    pixAnalysis.thMedFactor = thMedFactor

    # generate the threshold based on the thMethod specified
    if thMethod == ThreshMethod.constant:
        if thConst == -1.0:
            # validate the user specified a threshold constant
            raise ValueError("when using 'ThreshMethod.constant', thConst must be specified")
        pixAnalysis.thresh = thConst
    elif thMethod == ThreshMethod.average:
        pixAnalysis.thresh = np.average(pixArray)
    elif thMethod == ThreshMethod.percent:
        if thPct == -1.0:
            # validate the user specified a threshold percentage
            raise ValueError("when using 'ThreshMethod.percent', thPct must be specified")
        index = list(np.linspace(0, 100.0, pixMap.TOP_N_PIX))
        population = np.sort(pixArray)
        pixAnalysis.thresh = population[min(range(len(index)), key = lambda i: abs(index[i]-thPct))]
    elif thMethod == ThreshMethod.medianFactor:
        if thMedFactor == -1.0:
            # validate the user specified a factor to median
            raise ValueError("when using 'ThreshMethod.medianFactor', thMedFactor must be specified")
        pixAnalysis.thresh = thMedFactor * np.median(pixArray)
    elif thMethod == ThreshMethod.medianToMin:
        pixAnalysis.thresh = 2.0*np.median(pixArray)-min(pixArray)
    else:
        raise NotImplementedError(f"thMethod {thMethod} is not implemented")
    print(f"Threshold set to {pixAnalysis.thresh}")
    # compare pixArray to thresh based on threshold operator
    if thOp == ThreshOp.lt:
        pixToEnable = pixArray < pixAnalysis.thresh
    elif thOp == ThreshOp.le:
        pixToEnable = pixArray <= pixAnalysis.thresh
    elif thOp == ThreshOp.eq:
        pixToEnable = pixArray == pixAnalysis.thresh
    elif thOp == ThreshOp.ge:
        pixToEnable = pixArray >= pixAnalysis.thresh
    elif thOp == ThreshOp.gt:
        pixToEnable = pixArray > pixAnalysis.thresh

    # NOTE: disable pixels with TCR of 0 (usually defective)
    pixWithValidTcr = pixArray > 0
    pixToEnable = np.logical_and(pixToEnable, pixWithValidTcr)

    # apply mask
    if not pixEnMask is None:
        if (isinstance(pixEnMask, np.ndarray) and
                np.shape(pixEnMask) == (pixMap.TOP_NX_PIX, pixMap.TOP_NY_PIX)):
            # 2D array
            pixEnMask = pixMap.xymap2vect(pixEnMask)
        pixToEnable = np.logical_and(pixToEnable, pixEnMask)

    pixToEnable = np.array(pixToEnable)
    pixAnalysis.pixToEnable = pixToEnable
    pixAnalysis.numPixToEnable = (pixToEnable == True).sum()
    print(f"Enabling {pixAnalysis.numPixToEnable} pixels ({100.0*pixAnalysis.pctEnabled:>3.2f} %)")

    if plot!="":
        # Create a custom colormap from green to red
        # You can define the colors at specific points along the colormap
        colors = [(0, 'black'), (1, 'white')]
        cmap = mcolors.LinearSegmentedColormap.from_list("BlackWhite", colors)
        plt.ion()
        plt.figure()
        plt.imshow(pixMap.vect2xymap(pixToEnable).T, cmap=cmap, origin='lower', aspect="equal")
        #plt.show()
        plt.savefig(plot)
        plt.close()

    # calculate the total and average value per pixel
    pixAnalysis.totalAllPix = 0
    pixAnalysis.totalDisabled = 0
    for iPix in range(pixMap.TOP_N_PIX):
        pixAnalysis.totalAllPix += pixArray[iPix]
        if pixToEnable[iPix]:
            pixAnalysis.totalDisabled += pixArray[iPix]
    print(f"                         total        per pixel")
    print(f"All pixels enabled: {pixAnalysis.totalAllPix:>12.1f}, {pixAnalysis.totalAllPixPerPix:>12.1f}")
    print(f"Remaining pixels:   {pixAnalysis.totalDisabled:>12.1f}, {pixAnalysis.totalDisabledPerPix:>12.1f}")
    print(f"                    {100.0*pixAnalysis.pctTotal:>10.1f} %, {100.0*pixAnalysis.pctPerPix:>10.1f} %")

    # convert pixToEnable array to PDC pixel registers
    pdcPixReg = pixMap.vect2regs(pixToEnable, log=log)

    if returnAnalysis:
        return (pdcPixReg, pixAnalysis)
    else:
        return pdcPixReg
