#----------------------------------------------------------------------------------
#-- Company: GRAMS
#-- Designer: Gabriel Lessard
#--
#-- Create Date: 2025-03-11
#-- Description:
#--
#-- Dependencies:
#-- Revision:
#-- Revision 1.0 - File Created
#-- Additional Comments:
#----------------------------------------------------------------------------------
from pdcv2_modules.fgColors import fgColors
from pdcv2_modules.zynqEnvHelper import PROJECT_PATH, HOST_APPS_PATH, USER_DATA_DIR, HDF5_DATA_DIR
import pdcv2_modules.sshClientHelper as sshClientHelper
from pdcv2_modules.zynqCtlPdcRoutines import initCtlPdcFromClient, packetBank
from pdcv2_modules.pdcHelper import pdc_setting, setPdcTimeReg
from pdcv2_modules.h5Reader import h5Reader
from pdcv2_modules.zynqDataTransfer import zynqDataTransfer
from pdcv2_modules.systemHelper import sectionPrint
import unittest
import numpy as np
import os, sys

def printTestName():
    """
    printTestName: print name of calling test function
    """
    frame = sys._getframe( 1 )
    print(f"\n{fgColors.green}===== {os.path.basename( frame.f_code.co_name )} ====={fgColors.endc}")

# Runner for Head 2x2
class Head2x2TestRunner(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        sectionPrint("open a connection with the ZCU102 board")
        cls.client = sshClientHelper.sshClientFromCfg(hostCfgName="zcudev")
        
        sectionPrint("intialise zynq for data transfers")
        cls._zynqDataTx = zynqDataTransfer(sshClientZynq=cls.client)
        cls._zynqDataTx.init(archive=True)

        cls._reader = h5Reader(deleteAfter=True, hfAbsPath=cls._zynqDataTx.h5Path)


        cls.pdc_en = 0b1111
        #cls.client = cls.client
        cls.ctlCfg = initCtlPdcFromClient(client=cls.client, sysClkPrd=10e-9, pdcEn=cls.pdc_en)
        cls.ctlCfg.setSysClkPrd()

        cls._apply_config()
        cls.ctlCfg.startFSM()
        return super().setUpClass()
        
    
    @classmethod
    def tearDownClass(cls) -> None:
        cls._reader.h5Close()
        cls.ctlCfg.resetCtl()

        cls._zynqDataTx.close()
        return super().tearDownClass()
    
    def tearDown(cls):
        # Reset HDF5 reader
        
        return super().tearDown()
    
    @classmethod
    def _apply_config(cls, delay=300):
        # Given: an initial configuration for the controller 
        cls.ctlCfg.resetCtl()
        cls.ctlCfg.pdcEnUser = cls.pdc_en # Enable all 4 PDCs

        cls.ctlCfg.setCtlPacket(bank=packetBank.BANKA,
            SCS=0x7107, # Send all config to all PDC, get back status
            SCD=0x0000,
            SPD=0x0100) # 
        fsm_config = {
            "TOUT": 0x53FF, # Timeout: 
            "FEND": 0x8200, # FSM end enable, mode and delay
            "FTX1": 0x0080, # 
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
        cls.ctlCfg.setDelay(signal="CFG_DATA", delay=delay)
        cls.ctlCfg.setCfgRtnEn()
        cls.ctlCfg.setupFSM(fsm_config)
        cls.ctlCfg.preparePDC()

        ### Configure PDCs
        current_pdc_setting = pdc_setting()
        pdc_setting.TIME =  setPdcTimeReg(hold=150, rech=10,flag=4)
        current_pdc_setting.PIXL = 0x1102
        current_pdc_setting.DBGC = 0x8000
        current_pdc_setting.FIFO = 0x117f
        current_pdc_setting.DTXC = 0x00cc
        cls.ctlCfg.setCtlMode("MODE_CFG")
        current_pdc_setting.apply(session=cls.client.runPrint)

        # Then:
        ### Put PDCs in acquisition mode and start acquistion
        cls.ctlCfg.setCtlMode("MODE_ACQ")

        sectionPrint("_apply_config completed")

        return True     

    def test_00_h5file_produced(self):
        printTestName()
        print("Verify digital sum output through debug counter")
        
        # Expect: an HDF5 file is produced within 20 seconds
        if self._reader.hfFile == "":
            self.assertNotEqual(self._reader.waitForNewFile(timeout_sec=20), "")
        self.assertTrue(self._reader.h5Open())
        self.assertTrue(self._reader.h5GetCtl())

    def test_01_status_ok(self):
        printTestName()
        for iPDC in range(self.ctlCfg.nPdcEnUser):
            with self.subTest(PDC=iPDC):    
                status = self._reader.HDF_CTL.get(f"PDC_STATUS_ALL/PDC_0{iPDC}")[0]
                self.assertIn(status, (177,241))
    
    def test_02_dbg_cnt_value_ok(self):
        printTestName()
        for iPDC in range(self.ctlCfg.nPdcEnUser):
            with self.subTest(PDC=iPDC):
                [bin, data] = self._reader.getPdcDsum(iPDC)
                self.assertEqual(len(set(np.gradient(data))), 1, f"Failed PDC {iPDC}: gradient is not 1 across debug counter")
    

    
if __name__ == "__main__":
    unittest.main()
