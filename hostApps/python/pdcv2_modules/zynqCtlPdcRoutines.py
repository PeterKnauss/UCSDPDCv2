#----------------------------------------------------------------------------------
#-- Company: GRAMS
#-- Designer: Tommy Rossignol
#--
#-- Create Date: 2024-08-07
#-- Description:
#--     module with definition of routines to use
#--
#-- Dependencies:
#-- Revision:
#-- Revision 1.0 - File Created
#-- Additional Comments:
#----------------------------------------------------------------------------------
import sys
import numpy as np
import math
from enum import IntEnum
from typing import Literal

# custom modules
from pdcv2_modules.systemHelper import sectionPrint
from pdcv2_modules.fgColors import fgColors
import pdcv2_modules.sshClientHelper as sshClientHelper

class packetBank(IntEnum):
    BANKA = 0
    BANKB = 1

class packetSettings:
    def __init__(self):
        self.SCS = 0x0000 # CFG_STATUS
        self.SCD = 0x0000 # CTL_DATA
        self.SPD = 0x0000 # PDC_DATA


class initCtlPdcFromClient():
    def __init__(self, client, sysClkPrd=10e-9, pdcEn=0xF):
        sectionPrint("initialization of a Controller PDC helper")
        if ((type(client) != sshClientHelper.sshClient) and
            (type(client) != sshClientHelper.sshClientFromCfg)):
            print(f"{fgColors.red}ERROR: 'client' is not of type 'sshClient' nor 'sshClientFromCfg' but '{type(client)}'.{fgColors.endc}")
            sys.exit()

        # initial settings
        self.client = client
        self.sysClkPrd = sysClkPrd

        self.client.runPrint(cmd=f"boardInfo -l", printCmd=False)

        # requested by user, might change depending on hardware settings
        self.pdcEnUser = pdcEn
        self.nPdcEnUser = bin(self.pdcEnUser).count("1") # NOTE property/setter

        # maximum number of PDCs
        self.nPdcMax = self.client.runReturnInt(cmd=f"boardInfo --numasic --raw", printCmd=False)

        # number of SPADs available per PDC
        self.nSpad = 64

        # Controller packet settigns
        self.PACK_A = packetSettings()
        self.PACK_B = packetSettings()

    def print(self):
        print(f"sysClkPrd = {self.sysClkPrd} sec ({self.sysClkPrdNs} ns)")
        print(f"pdcEnUser = 0x{self.pdcEnUser:X}")
        print(f"nPdcMax = {self.nPdcMax}")
        print(f"nSpad = {self.nSpad}")

    @property
    def sysClkPrd(self):
        return self._sysClkPrd

    @sysClkPrd.setter
    def sysClkPrd(self, clkPrd):
        self._sysClkPrd = clkPrd
        self.sysClkPrdNs = int(np.round(self.sysClkPrd*1e9, 0))

    def setSysClkPrd(self, sysClkPrd=None):
        """
        setting system clock frequency.
        NOTE: always start with this function since it resets the Controller settings
        if sysClkPrd == None, using self.sysClkPrd, otherwise using sysClkPrd value
        """
        sectionPrint("set system clock period")
        if sysClkPrd != None:
            # using setting
            self.sysClkPrd = sysClkPrd

        self.client.runPrint(f"clkSet -P {self.sysClkPrdNs} --ns")

    def resetCtl(self):
        """
        full reset of the Controller
        does not reset the PDCs
        """
        sectionPrint("reset of the controller")
        self.client.runPrint('ctlCmd -c RSTN_FULL')

    def resetCtlFSM(self):
        """
        full reset of the Controller FSM
        does not reset the PDCs
        """
        sectionPrint("reset of the controller")
        self.client.runPrint('ctlCmd -c RSTN_SYS')

    def resetPDCSYS(self):
        """
        full reset of the PDC
        """
        sectionPrint("reset of the PDC SYSTEM")
        self.client.runPrint('ctlCmd -c PDC_RSTN_SYS')

    def resetCtlZPP(self):
        """
        Reset of the ZPP module
        """
        sectionPrint("reset of the Controller ZPP module")
        self.client.runPrint("ctlCmd -c RSTN_ZPP")
        

    def setCtlPacket(self, bank: packetBank, SCS=None, SCD=None, SPD=None):
        """
        configure either BANK_A or BANK_B
        SCS = SEND_CFG_STATUS
        SCD = SEND_CTL_DATA
        SPD = SEND_PDC_DATA
        if arguments are not specified, using settings from main class
        """
        sectionPrint("configure controller packet")
        if bank == packetBank.BANKA:
            pack = self.PACK_A
            bankName = 'A'
        else:
            pack = self.PACK_B
            bankName = 'B'

        # configure CFG_STATUS_X
        if SCS is not None:
            pack.SCS = SCS

        # configure CTL_DATA_X
        if SCD is not None:
            pack.SCD = SCD

        # configure PDC_DATA_X
        if SPD is not None:
            pack.SPD = SPD

        # sending settings to Controller
        self.client.runPrint(f"ctlCfg -a SCS{bankName} -r 0x{pack.SCS:04X} -g")
        self.client.runPrint(f"ctlCfg -a SCD{bankName} -r 0x{pack.SCD:04X} -g")
        self.client.runPrint(f"ctlCfg -a SPD{bankName} -r 0x{pack.SPD:04X} -g")

    def setDelay(self, signal, delay):
        """
        set FPGA delay lines
        signal:
            "CFG_DATA" : oDelay
            "FLAG"     : iDelay
            "DATA"     : iDelay
        """
        sectionPrint(f"set delay of {signal} pins")

        # reset the delay lines
        self.client.runPrint(f"ioDelaySet --signal {signal} --reset")  # reset all delay

        # get number of delay lines to configure
        numLines=self.client.runReturnSplitInt(f"ioDelaySet --signal {signal} -n")

        for line in range(numLines):
            self.client.runPrint(f"ioDelaySet --signal {signal} --sel {line} --count {delay} --get")

    def checkPowerGood(self):
        sectionPrint("check for power good")
        pwrGood = self.client.runReturnSplitInt('ctlCfg -P')
        if (pwrGood & self.pdcEnUser) != self.pdcEnUser:
            print(f"{fgColors.red}The proper adaptor board is not turned on, turn it on and restart the script{fgColors.endc}")
            sys.exit()

    def setCfgRtnEn(self):
        sectionPrint("enable CFG_RTN_EN")
        nCfgRtnEn = self.client.runReturnSplitInt('rtnEn -n')
        if self.nPdcMax == 8:
            # 2x2 heads setup
            if nCfgRtnEn != self.nPdcMax:
                print(f"{fgColors.red}ERROR: number of CFG_RTN_EN lines is different than expected, contact the system designer for a fix.{fgColors.endc}")
                sys.exit()
            self.client.runPrint(f"rtnEn -e 0x{self.pdcEnUser:04X} -s")
            cfgRtnEnSet = self.client.runReturnSplitInt(f"rtnEn -s", printCmd=False)
            if self.pdcEnUser != cfgRtnEnSet:
                # setting is not as expected
                print(f"{fgColors.red}The proper adaptor board is not turned on, turn it on and restart the script{fgColors.endc}")
                sys.exit()

        elif self.nPdcMax == 32:
            # 8x8 head setup
            PG = self.client.runReturnSplitInt(f"rtnEn -s", printCmd=False)
            PG_EXP = 0
            if self.pdcEnUser&0xFFFF != 0: PG_EXP+=1
            if (self.pdcEnUser>16)&0xFFFF != 0: PG_EXP+=2
            if PG&PG_EXP != PG_EXP:
                # setting is not as expected
                print(f"{fgColors.red}The proper adaptor board is not turned on, turn it on and restart the script{fgColors.endc}")
                sys.exit()

    def preparePDC(self):
        sectionPrint("setup the PDCs to use")
        self.client.runPrint(f"ctlCfg -a PDC0 -r 0x{self.pdcEnUser&0xFFFF:04X} -g")        # enable PDC
        self.client.runPrint(f"ctlCfg -a PDC1 -r 0x{(self.pdcEnUser>>16)&0xFFFF:04X} -g")  # enable PDC
        self.client.runPrint(f"ctlCfg -a CFG0 -r 0x{self.pdcEnUser&0xFFFF:04X} -g")        # enable PDC configuration
        self.client.runPrint(f"ctlCfg -a CFG1 -r 0x{(self.pdcEnUser>>16)&0xFFFF:04X} -g")  # enable PDC configuration
        self.client.runPrint( "ctlCfg -a PRST -r 0x0000 -g")                                # reset all PDCs

        # remove reset from PDCs
        if self.nPdcMax == 8:
            # 2x2 head setup, 1 reset per PDC
            self.client.runPrint(f"ctlCfg -a PRST -r 0x{self.pdcEnUser:04X} -g")
        elif self.nPdcMax == 32:
            # 8x8 head setup, # reset for all
            self.client.runPrint(f"ctlCfg -a PRST -r 0x1 -g")

    def setCtlMode(self, mode:Literal["MODE_CFG", "MODE_ACQ", "MODE_TRG"]):
        self.client.runPrint(f"ctlCmd -c {mode}")

    def setupFSM(self, cfg_dict:dict):
        """
        Sets-up the FSM config params based on the input dict.

        cfg_dict: dict containing the register and value to configure for the FSM. Only certain registers are allowed
        """
        allowed_keys = ["TOUT",
                        "FEND",
                        "FTX1",
                        "FTX0",
                        "ATX1",
                        "ATX0",
                        "SLW1",
                        "SLW0",
                        "FST1",
                        "FST0",
                        "FACQ",
                        "FSMM",
                        "MISC"]
        
        cmd = ""
        for reg, value in cfg_dict.items():
            if reg not in allowed_keys:
                print(f"{fgColors.bYellow} Cannot configure register {reg} for FSM {fgColors.endc}")
                continue
            cmd += f"ctlCfg -a {reg} -r 0x{value:04X} -g ; "
        self.client.runPrint(cmd)

    def startFSM(self):
        self.client.runPrint("ctlCmd -c FSM_START")

    def trigger(self):
        self.client.runPrint("ctlCmd -c PDC_TRG")

    def pack_trg_bank(self, bank:Literal["A", "B"]):
        if bank not in ["A", "B"]:
            print(f"{fgColors.bYellow} Unknown bank {bank} supplied {fgColors.endc}")
            return False
        self.client.runPrint(f"ctlCmd -c PACK_TRG_{bank}")

    def validPdcCfg(self):
        # list of status to validate
        #statusToValidate = [
        #    "BNK_RTN_CLK_ERR",
        #    "BNK_RTN_DATA_ERR",
        #    "BNK_RTN_ERR",
        #    "PDC_CMD_VALID_ERR",
        #    "PDC_CFG_VALID_ERR",
        #    "PDC_CFG_CS_ERR",
        #    "PDC_CFG_VALID_LEN_ERR",
        #    "GENERAL_STATUS",
        #]
        statusToValidate = [
            "BNK_RTN_CLK_ERR",
            "BNK_RTN_DATA_ERR",
            "PDC_CMD_VALID_ERR",
            "PDC_CFG_VALID_ERR",
            "PDC_CFG_CS_ERR",
            "PDC_CFG_VALID_LEN_ERR",
            "GENERAL_STATUS",
        ]
        # original check is CFG_VALID_ERR and CFG_CS_ERR
        # ctlCfg option --status (-s) can take multiple status, separated by a comma
        statusStr = ",".join(statusToValidate)
        cmd = f"ctlCfg -s {statusStr}"
        # running the command
        hostOutput = self.client.runReturn(cmd)
        hostOutput.encoding = 'utf-8'

        # checking for errors
        errorDetected = False
        for errLine in hostOutput.stderr:
            if errorDetected == False:
                print(f"{fgColors.red}ERROR: validation command '{cmd}' returned with following error message:{fgColors.endc}")
            print(f"{fgColors.red}{errLine}{fgColors.endc}")
            errorDetected = True
        if errorDetected:
            sys.exit()

        # get status, looping through all stdout lines
        nStatusFound = 0
        for statusLine in hostOutput.stdout:
            # check for all status
            for status in statusToValidate:
                if statusLine.startswith(status):
                    # statusLine contains the required status to validate
                    nStatusFound += 1
                    statusReceived = int(statusLine.split(':')[-1], base=16)
                    print(f"statusReceived for '{status}' is '{statusReceived}'")
                    if statusReceived != 0:
                        print(f"{fgColors.red}ERROR: {status} is set to 0x{statusReceived:08x}, expecting '0x00000000'.{fgColors.endc}")
                        sys.exit()
                    break
        if nStatusFound != len(statusToValidate):
            # not all status found
            print(f"{fgColors.red}ERROR: expected to find {len(statusToValidate)} status registers, but only found {nStatusFound}.{fgColors.endc}")
            sys.exit()

    def cfgAllPixRegs(self, regs, iPdc=None, printCmd=False):
        """
        program all the pixel enable registers of the PDC.
        regs must be an array of 256 elements of 16 bits
        """
        # make sure to select the proper PDCs
        cmd = ""
        if iPdc == None:
            # registers to apply to all PDCs
            cmd += "ctlCfg -a CFGS -r 0x0000 -g; \n"
            pdcStr = ""
        else:
            # registers apply to a single PDC
            pdcStr = f"--spdc {iPdc}"
        # then a command to disable all the pixels
        cmd += f"pdcPix --dis {pdcStr} --mode NONE; \n"
        # loop for each register and append the command
        for addr, reg in enumerate(regs):
            if not (reg == 0):
                cmd += f"pdcPix --addr {addr} --reg 0x{reg:04x} --mode NONE; \n"
        if addr != 255:
            print(f"{fgColors.red}ERROR: not programming all the registers.{fgColors.endc}")
        self.client.runPrint(cmd, printCmd=printCmd)

    def initExample(self):
        """
        default example
        """
        self.setSysClkPrd()
        self.print()
        self.resetCtl()
        self.setCtlPacket(bank=packetBank.BANKA, SCS=0x0000, SCD=0x0000, SPD=0x0000)
        self.setDelay(signal="CFG_DATA", delay=300)
        self.setCfgRtnEn()
        fsm_config = {
            "TOUT": 0x5030,
            "FEND": 0x8200,
            "FTX1": 0x0080,
            "FTX0": 0x8600,
            "ATX1": 0x0000,
            "ATX0": 0x0000,
            "SLW1": 0x0000,
            "SLW0": 0x0000,
            "FST1": 0x0080,
            "FST0": 0x8600,
            "FACQ": 0x0007,
            "FSMM": 0x0111 
        }
        self.setupFSM(fsm_config)
        self.preparePDC()

if __name__ == "__main__":
    # -----------------------------------------------
    # --- open a connection with the ZCU102 board
    # -----------------------------------------------
    sectionPrint("open a connection with the ZCU102 board")
    client = sshClientHelper.sshClientFromCfg(hostCfgName="zcudev")

    icpfc = initCtlPdcFromClient(client=client, sysClkPrd=10e-9)
    icpfc.initExample()
    icpfc.validPdcCfg()



