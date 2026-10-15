#----------------------------------------------------------------------------------
#-- Company: GRAMS
#-- Designer: Tommy Rossignol
#--
#-- Create Date: 2025-03-21
#-- Description:
#--      Using python ssh libraries to send remote commands to the ZCU102
#--      This script prepare the Controller data communication.
#--      Check for Zynq board NFS settings.
#--      Check for dataReader app on Zynq board.
#--      Check for .hex parsing app
#--
#-- Dependencies:
#-- Revision:
#-- Revision 1.0 - File Created
#-- Revision 2.0 - Updated for sharing on pdcv2-public
#-- Additional Comments:
#--
#----------------------------------------------------------------------------------
import sys, os
import numpy as np
import random
import time
import datetime
from itertools import chain
import statistics
import matplotlib.pyplot as plt

# custom modules
from pdcv2_modules.fgColors import fgColors
from pdcv2_modules.zynqEnvHelper import PROJECT_PATH, HOST_APPS_PATH, USER_DATA_DIR, HDF5_DATA_DIR
import pdcv2_modules.sshClientHelper as sshClientHelper
import pdcv2_modules.systemHelper as systemHelper
from pdcv2_modules.zynqCtlPdcRoutines import initCtlPdcFromClient, packetBank
from pdcv2_modules.zynqDataTransfer import zynqDataTransfer
from pdcv2_modules.systemHelper import sectionPrint
from pdcv2_modules.pdcHelper import *
#from modules.zynqHelper import *
from pdcv2_modules.h5Reader import *

# -----------------------------------------------
# --- open a connection with the ZCU102 board
# -----------------------------------------------
sectionPrint("open a connection with the ZCU102 board")
# parameters of the ZCU102 board
# open a client based on its name in the ssh config file
client = sshClientHelper.sshClientFromCfg(hostCfgName="zcudev")

# -----------------------------------------------
# --- prepare Zynq platform
# -----------------------------------------------
sectionPrint("prepare Zynq platform")
zynq = zynqDataTransfer(sshClientZynq=client)
zynq.init()

# -----------------------------------------------
# --- prepare controller for acquisition
# -----------------------------------------------
# NOTE: select here the PDC to use:
#       pdcEn=0x1 -> PDC0
#       pdcEn=0x2 -> PDC1
#       pdcEn=0x4 -> PDC2
#       pdcEn=0x8 -> PDC3
#       pdcEn=0xF -> PDC0, PDC1, PDC2, PDC3
icp = initCtlPdcFromClient(client=client, sysClkPrd=10e-9, pdcEn=0xF)

# -----------------------------------------------
# --- set system clock period
# -----------------------------------------------
icp.setSysClkPrd()

# -----------------------------------------------
# --- reset of the controller
# -----------------------------------------------
icp.resetCtl()

# -----------------------------------------------
# --- configure controller packet
# -----------------------------------------------
# NOTE always set SCSA register first to store other configuration registers in HDF5
# configure CFG_STATUS_A
    # 0x8000 = PDC_CFG
    # 0x4000 = CTL_CFG
    # 0x2000 = PDC_STATUS
    # 0x1000 = PDC_STATUS_ALL
    # 0x0007 = ALL CTL_STATUS
SCSA = 0x0000
# configure CTL_DATA_A
SCDA = 0x0000
# configure PDC_DATA_A
    # 0x0100 = DSUM
    # 0x00F7 = ZPP
SPDA = 0x0000
icp.setCtlPacket(bank=packetBank.BANKA, SCS=SCSA, SCD=SCDA, SPD=SPDA)

# -----------------------------------------------
# --- set delay of CFG_DATA pins
# -----------------------------------------------
icp.setDelay(signal="CFG_DATA", delay=300)

# -----------------------------------------------
# --- check for power good
# -----------------------------------------------
icp.checkPowerGood()

# -----------------------------------------------
# --- enable CFG_RTN_EN
# -----------------------------------------------
icp.setCfgRtnEn()

# -----------------------------------------------
# --- prepare PDC for configuration
# -----------------------------------------------
icp.preparePDC()

# ready to operate
print("\n=== READY TO OPERATE ===")
print("You can run other scripts to configure the PDC and Controller.")
print("  e.g. pdc-dbg-cnt-transmit (on Zynq)")
try:
    input("Press [enter] key to exit")
except KeyboardInterrupt:
    print("\nKeyboard Interrupt: exit program")
    sys.exit()





