import numpy as np

# PDC PIXEL CONSTANTS
TOP_NX_REG=16   # number of registers along x axis (CMOS pads axis)
TOP_NY_REG=16   # number of registers along y axis
TOP_N_REG=TOP_NX_REG*TOP_NY_REG

# a register is 4x4 pixels
REG_NX_PIX=4    # number of pixels along x axis in a pixel register
REG_NY_PIX=4    # number of pixels along y axis in a pixel register
REG_N_PIX=REG_NX_PIX*REG_NY_PIX

TOP_NX_PIX = TOP_NX_REG*REG_NX_PIX
TOP_NY_PIX = TOP_NY_REG*REG_NY_PIX
TOP_N_PIX = TOP_NX_PIX*TOP_NY_PIX

# number of pixel enable register
N_PDC_REG = int(TOP_N_PIX/REG_N_PIX)

# of the different implementation, this one is the fastest
def vect2xymap(value_unmapped):
    """
    Converts a vector with pixel index from 0 to 4095 into
    an array representing the ASIC with 64 rows (y) and 64 columns (x)
    """
    vect_len = len(value_unmapped)
    if (vect_len == TOP_N_PIX):
        value_mapped=np.zeros((TOP_NX_PIX, TOP_NY_PIX))

        iPix = 0
        for yReg in range(0, TOP_NY_REG):
            for xReg in range(0, TOP_NX_REG):
                for yPix in range(0, REG_NY_PIX):
                    x = xReg*REG_NX_PIX
                    y = yReg*REG_NY_PIX + yPix
                    value_mapped[x:x+REG_NX_PIX, y] = value_unmapped[iPix:iPix+REG_NX_PIX]
                    iPix += REG_NX_PIX

        return value_mapped
    else:
        print("Warning: size must be 64 x 64, found %d items" % vect_len)
        return value_unmapped

## logic with optimization
#def vect2xymap(value_unmapped):
#    """
#    Converts a vector with pixel index from 0 to 4095 into
#    an array representing the ASIC with 64 rows (y) and 64 columns (x)
#    """
#    vect_len = len(value_unmapped)
#    if (vect_len == TOP_N_PIX):
#        value_mapped=np.zeros((TOP_NX_PIX, TOP_NY_PIX))
#
#        for iPix in range(0, TOP_N_PIX):
#            # index of the register based on REG_N_PIX pixels in a register
#            iReg = int(iPix/REG_N_PIX)
#            yReg = int(iReg/TOP_NX_REG)
#            xReg = iReg % TOP_NX_REG
#            iPixInReg = iPix % REG_N_PIX
#            yPix = int(iPixInReg/REG_NX_PIX)
#            xPix = iPixInReg % REG_NX_PIX
#            x = xReg*REG_NX_PIX + xPix
#            y = yReg*REG_NY_PIX + yPix
#
#            value_mapped[x, y] = value_unmapped[iPix]
#
#        return value_mapped
#    else:
#        print("Warning: size must be 64 x 64, found %d items" % vect_len)
#        return value_unmapped

## logic without optimization (slowest)
#def vect2xymap(value_unmapped):
#    """
#    Converts a vector with pixel index from 0 to 4095 into
#    an array representing the ASIC with 64 rows (y) and 64 columns (x)
#    """
#    vect_len = len(value_unmapped)
#    if (vect_len == TOP_N_PIX):
#        value_mapped=np.zeros((TOP_NX_PIX, TOP_NY_PIX))
#
#        for iPix in range(0, TOP_N_PIX):
#            # index of the register based on REG_N_PIX pixels in a register
#            iReg = int(iPix/REG_N_PIX)
#            yReg = int(iReg/TOP_NX_REG)
#            xReg = iReg - (yReg*TOP_NX_REG)
#            iPixInReg = iPix-(iReg*REG_N_PIX)
#            yPix = int(iPixInReg/REG_NX_PIX)
#            xPix = iPixInReg - (yPix*REG_NX_PIX)
#            x = xReg*REG_NX_PIX + xPix
#            y = yReg*REG_NY_PIX + yPix
#
#            value_mapped[x, y] = value_unmapped[iPix]
#
#        return value_mapped
#    else:
#        print("Warning: size must be 64 x 64, found %d items" % vect_len)
#        return value_unmapped

XPIX = 64
YPIX = 64
def vect2xy (value_unmapped):
    """
    Converts a vector into an array representing the ASIC
    The vector is filled with y=0, x=0-63, then y=1, x=0-63 and so on
    """
    vect_len = len(value_unmapped)
    if (vect_len == 4096):
        #value_mapped=np.zeros_like(value_unmapped)
        #value_mapped.resize(XPIX, YPIX)
        value_mapped=np.zeros((XPIX, YPIX))

        for y in range(0, YPIX):
            #print("shape mapped = "+str(np.shape(value_mapped[:, y])))
            #print("shape unmapped = "+str(np.shape(value_unmapped[y*XPIX:(y+1)*XPIX])))
            value_mapped[:, y] = value_unmapped[y*XPIX:(y+1)*XPIX]

        return value_mapped
    else:
        print("Warning: size must be 64 x 64, found %d items" % vect_len)
        return value_unmapped

def idx_map(x, y):
    """
    Converts a X, Y based pixel index to a pixel index
    """
    idx_x =  x     +  3*(x  & 0x0000003C)
    idx_y = (y<<2) + 15*((y & 0x0000003C)<<2)
    return idx_x + idx_y;

def xy_map(idx: int):
    """
    Converts a pixel index to a  X, Y based pixel index

    Args:
        idx (int): The 1D pixel index.

    Returns:
        tuple[int, int]: The (x, y) coordinates.
    """
    # Initialize x and y
    for y in range(YPIX):
        idx_y = (y << 2) + 15 * ((y & 0x0000003C) << 2)
        if idx < idx_y:
            continue
        for x in range(XPIX):
            idx_x = x + 3 * (x & 0x0000003C)
            if idx == idx_x + idx_y:
                return x, y

    raise ValueError("Invalid index: Could not map to (x, y)")

def xymap2vect(value_mapped):
    """
    Converts an array representing the ASIC with 64 rows (y) and 64 columns (x) into a vector with pixel index from 0 to 4095
    """
    array_shape = np.shape(value_mapped)
    if (array_shape == (TOP_NX_PIX, TOP_NY_PIX)):
        vector=np.zeros(TOP_N_PIX)

        for yPix in range(0, TOP_NY_PIX):
            for xPix in range(0, TOP_NX_PIX):
                vector[idx_map(xPix, yPix)] = value_mapped[xPix, yPix]

        return vector
    else:
        print("Warning: size must be 64 x 64, found {array_shape} items")
        return value_mapped


def vect2regs(vect, log=False):
    """
    Converts a vector of pixels to the pixel enable registers of the PDC
    Values in vect must be 0/1 or False/True
    """
    pdcPixReg = np.zeros(N_PDC_REG, dtype=np.uint16)
    for iReg in range(N_PDC_REG):
        for iPix in range(REG_N_PIX):
            if vect[REG_N_PIX*iReg+iPix]:
                pdcPixReg[iReg] |= (0x1 << iPix)
        if log:
            print(f"{iReg:>3d}:0x{pdcPixReg[iReg]:04x}")
    return pdcPixReg


def xy2regs(xyArray, log=False):
    """
    Converts a X, Y based pixel array to the pixel enable registers of the PDC
    Values in xyArray must be 0/1 or False/True
    """
    pdcPixReg = np.zeros(N_PDC_REG, dtype=np.uint16)
    for yReg in range(TOP_NY_REG):
        for xReg in range(TOP_NX_REG):
            iReg = TOP_NX_REG*yReg + xReg
            for yPix in range(REG_NY_PIX):
                for xPix in range(REG_NX_PIX):
                    iPix = yPix*REG_NX_PIX + xPix
                    row = yReg*REG_NY_PIX+yPix
                    col = xReg*REG_NX_PIX+xPix
                    if xyArray[col, row]:
                        pdcPixReg[iReg] |= (0x1 << iPix)
            if log:
                print(f"{iReg:>3d}:0x{pdcPixReg[iReg]:04x}")
    return pdcPixReg

