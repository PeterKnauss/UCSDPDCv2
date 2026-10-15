#----------------------------------------------------------------------------------
#-- Company: GRAMS
#-- Designer: Tommy Rossignol
#--
#-- Create Date: 2023-03-22
#-- Description:
#--     module related to the PDC settings and functions
#--
#-- Dependencies:
#-- Revision:
#-- Revision 1.0 - File Created
#-- Additional Comments:
#----------------------------------------------------------------------------------
from enum import IntEnum

# -------------------
# ----- CLASSES -----
# -------------------
class PDC_ADDR(IntEnum):
    RSVD = 0
    PIXL = 1
    TIME = 2
    ANLG = 3
    STHH = 4
    STHL = 5
    ACQA = 6
    ACQB = 7
    DBGC = 8
    FIFO = 9
    DTXC = 10
    OUTD = 11
    OUTF = 12
    OUTC = 13
    TRGC = 14

class OUT_MUX(IntEnum):
    FLAG = 0
    CLK_TX = 1
    DATA = 2
    TRG = 3
    VSS = 4
    PIX_FLAG = 5
    PIX_QC = 6
    PIX_SYNC = 7
    SUM_LT = 8
    SUM_IB = 9
    SUM_GT = 10
    SUM_EQ = 11
    MODE_ACQ = 12
    MODE_TRG = 13
    MODE_CFG = 14
    CLK_CS = 15
    CLK_SYNC = 16
    CLK_PIPE = 17
    FIFO_WR_EN = 18
    FIFO_RD_EN = 19
    TX_DATA_VALID = 20
    FIFO_EMPTY = 21
    FIFO_OVERWR = 22
    FIFO_FULL = 23
    CFG_CLK = 24
    CFG_DATA = 25
    CFG_VALID = 26
    CMD_VALID = 27
    PG_VDD_FE = 28
    PG_VDD_AM = 29
    PG_VDD_QC = 30
    UNUSED = 31
    VDD = 30

# PDC settings (for reference only)
class pdc_setting:
    def __init__():
        self.PIXL=0x1100
        self.TIME=0xDEDE
        self.ANLG=0x0000
        self.STHH=0x0000
        self.STHL=0x1FFF
        self.ACQA=0x1432
        self.ACQB=0x020A
        self.DBGC=0x11CD
        self.FIFO=0x007F
        self.DTXC=0x00CC
        self.OUTD=0x0082
        self.OUTF=0x030C
        self.OUTC=0x03DA
        self.TRGC=0x0000

    def __init__(self, PIXL=0x1100,
                       TIME=0xDEDE,
                       ANLG=0x0000,
                       STHH=0x0000,
                       STHL=0x1FFF,
                       ACQA=0x1432,
                       ACQB=0x020A,
                       DBGC=0x11CD,
                       FIFO=0x007F,
                       DTXC=0x00CC,
                       OUTD=0x0082,
                       OUTF=0x030C,
                       OUTC=0x03DA,
                       TRGC=0x0000):
        self.PIXL=PIXL
        self.TIME=TIME
        self.ANLG=ANLG
        self.STHH=STHH
        self.STHL=STHL
        self.ACQA=ACQA
        self.ACQB=ACQB
        self.DBGC=DBGC
        self.FIFO=FIFO
        self.DTXC=DTXC
        self.OUTD=OUTD
        self.OUTF=OUTF
        self.OUTC=OUTC
        self.TRGC=TRGC

    def print(self, sel="ALL"):
        attrs = vars(self)
        for item in attrs.items():
            if (sel == "ALL" or sel == item[0]):
                print(f"{item[0]} = 0x{item[1]:04x}")

    def apply(self, session):
        cmd = ""
        cmd += f"pdcCfg -a PIXL -r {self.PIXL} ;"
        cmd += f"pdcCfg -a ANLG -r {self.ANLG} ;"
        cmd += f"pdcCfg -a STHH -r {self.STHH} ;"
        cmd += f"pdcCfg -a STHL -r {self.STHL} ;"
        cmd += f"pdcCfg -a ACQA -r {self.ACQA} ;"
        cmd += f"pdcCfg -a ACQB -r {self.ACQB} ;"
        cmd += f"pdcCfg -a DBGC -r {self.DBGC} ;"
        cmd += f"pdcCfg -a FIFO -r {self.FIFO} ;"
        cmd += f"pdcCfg -a DTXC -r {self.DTXC} ;"
        cmd += f"pdcCfg -a OUTD -r {self.OUTD} ;"
        cmd += f"pdcCfg -a OUTF -r {self.OUTF} ;"
        cmd += f"pdcCfg -a OUTC -r {self.OUTC} ;"
        cmd += f"pdcCfg -a TRGC -r {self.TRGC} ;"
        
        return session(cmd)
    





# ---------------------
# ----- FUNCTIONS -----
# ---------------------

def setPdcTimeReg(hold: int, rech: int, flag: int) -> int:
    """
    Input as reg values, not ns
    """
    REG = 0
    REG += (hold&0x3F)
    REG += ((rech&0x1F)<<6)
    REG += ((flag&0x1F)<<11)
    return REG

def setPDCTime(hold_ns:float, rech_ns: float, flag: float, session):
    """
    Input as ns
    """
    session(f"pdcTime -H {hold_ns} -R {rech_ns} -F {flag}")




if __name__ == "__main__":
    # testing pdcHelper class only when module is not called via 'import'
    PDC_SETTING = pdc_setting()