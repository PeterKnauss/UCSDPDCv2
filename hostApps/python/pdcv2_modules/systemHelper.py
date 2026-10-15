#----------------------------------------------------------------------------------
#-- Company: GRAMS
#-- Designer: Tommy Rossignol
#-- 
#-- Create Date: 2023-03-22
#-- Description:
#--     module related to the system and error management
#--
#-- Dependencies: 
#-- Revision:
#-- Revision 1.0 - File Created
#-- Additional Comments:
#----------------------------------------------------------------------------------
import subprocess
import sys, os
import traceback
from pdcv2_modules.fgColors import fgColors

def sectionPrint(msg):
    print('')
    print('-'*50)
    print(f"--- {msg}")
    print('-'*50)

def printException(ex):
    # Get current system exception
    # https://docs.python.org/3/library/traceback.html
    ex_type, ex_value, ex_traceback = sys.exc_info()

    # Extract unformatter stack traces as tuples
    trace_back = traceback.extract_tb(ex_traceback)

    # print the message
    print(f"{fgColors.red}{'-'*75}{fgColors.endc}")
    print(f"{fgColors.red}{ex_type.__name__}{fgColors.endc}{' '*33}Traceback (most recent call last)")
    #print(f"{stack_trace}")
    for trace in trace_back:
        tfile=trace[0]
        tline=trace[1]
        tfunc=trace[2]
        tmess=trace[3]
        print(f"File {fgColors.bGreen}{tfile}:{tline}{fgColors.endc}")
        print(f"    Func.Name : {tfunc}")
        print(f"    Message : {tmess}")
    print(f"{fgColors.red}{ex_type.__name__}{fgColors.endc}: {ex_value}")

def get_gitVersion():
    try:
        version = '0x0000000'
        process = subprocess.Popen(['git', 'rev-parse', '--short', 'HEAD'],
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)
        stdout, stderr = process.communicate()
        if not stderr:
            # no error
            version = '0x' + stdout.decode().strip('\n')
            tmp = int(version, base=16)
        return version
    except BaseException as ex:
        return version

def strToBool(var):
    #Convert environment variable interpreted as a string to the appropriate boolean value

    if var in ('true', 'True', '1'):
        return True
    else:
        return False

def get_environVars():
    #Get PDC-specific environment variables
    pdcVarsList = ['SPAD_BIAS_V', 'HEAD_ID' ,'ANALOG_ONLY', 'MEAS_TIME', 'RAD_SOURCE_NAME', 'TCR_FILE', 'PDC_EN', 'HOLD_TIME_NS', 'RECH_TIME','FLAG_TIME','N_SPAD','SCREAMER_METHOD','SCREAMER_THRESHOLD', 'SCREAMER_PERCENT', 'SCREAMER_FACTOR', 'FNAME', 'SAVE_PLOT', 'DATA_TYPE','COIN_WLEN','COIN_NCH_TH','COIN_NUM_BANK', 'DSUM_DATA_TYPE', 'BIN_IDX_MODE']
    environVars = os.environ
    pdcVars = {}
    for var in pdcVarsList:
        if var in environVars.keys():
            pdcVars[var]=environVars[var]

    return pdcVars

def save_environVars():
    #Save PDC-specific environment variables to txt file
    vars = get_environVars()
    print("#!/bin/bash")
    for k in vars.keys():
        print(f"export {k}={vars[k]}\n")
    return


class Tee:
    # class to reproduce the behaviour of tee in linux CLI
    # to both print into sys.stdout (terminal) and log file
    def __init__(self, *files):
        self.files = files

    def write(self, obj):
        for f in self.files:
            f.write(obj)
            f.flush() # Ensure immediate writing

    def flush(self):
        for f in self.files:
            f.flush()
