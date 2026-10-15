#----------------------------------------------------------------------------------
#-- Company: GRAMS
#-- Designer: Tommy Rossignol
#--
#-- Create Date: 2024-07-10
#-- Description:
#--     module related ZCU102 and PDC server and data transfer
#--
#-- Dependencies:
#-- Revision:
#-- Revision 1.0 - File Created
#-- Additional Comments:
#----------------------------------------------------------------------------------
import numpy as np
import sys, os
import ipaddress
import subprocess
import glob
import time
from pssh.exceptions import SessionError
import psutil

# custom modules
from pdcv2_modules.fgColors import fgColors
from pdcv2_modules.zynqEnvHelper import PROJECT_PATH, HOST_APPS_PATH, USER_DATA_DIR, HDF5_DATA_DIR
import pdcv2_modules.sshClientHelper as sshClientHelper
from pdcv2_modules.systemHelper import sectionPrint, printException

class zynqDataTransfer:
    def __init__(self, sshClientZynq: sshClientHelper.sshClient):
        """
        constructor, setup required member variables for operation
        """
        # open ssh client to Zynq board
        self.sshClient = sshClientZynq

        # address of the host running this code
        self.hostAddr = "127.0.0.1"
        with os.popen("hostname -I") as hostCmd:
            self.hostAddr = hostCmd.read().strip()

        # path to NFS bin and data on Zynq board
        self.zynqNfsBinPath = "/mnt/bin"
        self.zynqNfsDataPath = "/mnt/data"
        self.serverNfsDataPath = "/mnt/zynq/PDCv2/data" # default value, to be overwritten in initNFS # TBD
        self.nfsServerName = None
        self.nfsServerAddr = None
        self.launchedFromNfsServer = False

        # dataReader app
        self.dataReaderName = "dataReader"
        self.dataReaderPidRemote = None # started by another application
        self.dataReaderPidLocal = None  # started by this application

        # hex app
        #self.hexAppName = "dma2h5" # NOTE: soon to be replaced by hexRead
        self.hexAppName = "hexRead" # NOTE: soon to be replaced by hexRead
        self.hexAppPath = ""       # NOTE: to be set in getHexAppPath()
        self.hexAppOutPathDefault = HDF5_DATA_DIR
        self.hexAppPidRemote = None # started by another application
        self.hexAppPidLocal = None  # started by this application
        self.hexAppPopen = None
        self.hexInputPath = self.serverNfsDataPath # can be overwritten by getHexInputPath()
        self.hexDataExt = ".hex"

        # HDF5
        self.h5Path = None


    def __del__(self):
        """
        destructor, cleaning everything, closing app when done
        """        
        self.close()


    def debug(self):
        """
        print all member variables of the class
        """
        for item in self.__dict__:
            print(f"{item}={self.__dict__[item]}")

    def getHexAppPath(self):
        """
        try to find the path to hexApp, if not use a default value
        """
        # test if hexApp is in path
        with os.popen(f"which {self.hexAppName}") as hostCmd:
            hexAppInPath = hostCmd.read().strip()
        if len(hexAppInPath) > 0:
            #if os.path.isfile(os.path.join(hexAppPath, self.hexAppName)):
            if os.path.isfile(hexAppInPath):
                self.hexAppPath = os.path.dirname(hexAppInPath)
                print(f"{fgColors.green}'{self.hexAppName}' found at '{self.hexAppPath}'.{fgColors.endc}")
                return
        else:
            print(f"{fgColors.yellow}WARNING: '{self.hexAppName}' is not in 'PATH'.{fgColors.endc}")

        # not found it yet
        hexPossiblePathList = [
            HOST_APPS_PATH,
            "/mnt/zynq/PDCv2/tools",
        ]
        for hexPossiblePath in hexPossiblePathList:
            if os.path.isdir(hexPossiblePath) and os.path.isfile(os.path.join(hexPossiblePath, self.hexAppName)):
                self.hexAppPath = hexPossiblePath
                print(f"{fgColors.bBlue}INFO: '{self.hexAppName}' found at '{self.hexAppPath}'.{fgColors.endc}")
                return
        print(f"{fgColors.yellow}[{moduleName}] WARNING: Could not find path to {self.hexAppName}.{fgColors.endc}")
        self.hexAppPath = ""

    def initNfs(self):
        """
        get Zynq board NFS settings and store them
        """
        # NFS settings - from Zynq linux file system command 'df'
        nfsSettings = self.sshClient.runReturnStr(f"df -T | grep {self.zynqNfsDataPath}",
                                                  printCmd=False)
        if len(nfsSettings) == 0:
            # NFS data path is not mounted
            print(f"{fgColors.red}ERROR: The NFS is not properly configured on the ZCU102.\n"
                  f"       Use 'setup-zynq' script on ZCU102 or the proper 'mount' command.{fgColors.endc}")
            # exit module, user must setup manually NFS
            sys.exit()

        elif len(nfsSettings) > 0:
            # found settings associated with self.zynqNfsDataPath
            print(f"NFS settings: {nfsSettings[0]}")
            self.nfsServerName = nfsSettings[0].split(':')[0]

            # get the NFS server path from the Zynq linux
            try:
                serverNfsDataPath = nfsSettings[0].split(' ')[0].split(':')[1]
            except Exception as ex:
                printException(ex)

            try:
                # check if nfsServerName is set as an IPv4 address
                self.nfsServerAddr = str(ipaddress.ip_address(self.nfsServerName))
            except ValueError as ex:
                # not a valid IPv4 address, maybe a hostname, try to ping it
                nfsServerIp = self.nfsServerName # default value if ping is not working
                pingStr = self.sshClient.runReturnStr(f"ping {self.nfsServerName} -c 1 -W 0.1 2>&1", printCmd=False)
                for line in pingStr:
                    if line.startswith(f"PING {self.nfsServerName} ("):
                        nfsServerIp = line.replace(f"PING {self.nfsServerName} (", "").split(")")[0]
                        break
                try:
                    # last try, if it fails, leave it as is and let the rest of the script handle it
                    self.nfsServerAddr = str(ipaddress.ip_address(nfsServerIp))
                except ValueError as ex:
                    # fall back to addr = name
                    self.nfsServerAddr = self.nfsServerName
            #print(f"nfsServerName: {self.nfsServerName}, nfsServerAddr: {self.nfsServerAddr}")

            if self.nfsServerAddr in self.hostAddr:
                # host address and NFS server have the same address
                print(f"{fgColors.bBlue}INFO: This script is running on the NFS server '{self.nfsServerName}' ({self.nfsServerAddr}).{fgColors.endc}")
                self.launchedFromNfsServer = True
                if "serverNfsDataPath" in locals():
                    if os.path.isdir(serverNfsDataPath):
                        self.serverNfsDataPath = serverNfsDataPath
                        print(f"{fgColors.bBlue}INFO: Using the NFS server path {self.serverNfsDataPath}.{fgColors.endc}")
            else:
                # host address and NFS server have different addresses
                self.launchedFromNfsServer = False
                print(f"{fgColors.bYellow}WARNING: This script is not running on the NFS server '{self.nfsServerName}' ({self.nfsServerAddr}).{fgColors.endc}")
                if "serverNfsDataPath" in locals():
                    if serverNfsDataPath != self.serverNfsDataPath:
                        print(f"{fgColors.bYellow}WARNING: Mismatch in the NFS server path from Zynq setup and this script.{fgColors.endc}")
                        print(f"{fgColors.bYellow}         Zynq   : {serverNfsDataPath}{fgColors.endc}")
                        print(f"{fgColors.bYellow}         Script : {self.serverNfsDataPath}{fgColors.endc}")


    def __getDataReaderPid(self):
        """
        private function to get process id of dataReader app
        """
        return self.sshClient.runReturnStr(f"pgrep {self.dataReaderName}", printCmd=False)


    def initDataReader(self, dataReaderLaunch=False):
        """
        trying to start dataReader app on Zynq board if not already running
        """
        PID = self.__getDataReaderPid()

        if len(PID) == 0:
            # no PID found for the app
            if dataReaderLaunch:
                # starting the app if not running
                print(f"{fgColors.bBlue}INFO: starting '{self.dataReaderName}'.{fgColors.endc}")
                self.sshClient.run(f"{self.dataReaderName} -vvv -c")
                PID = self.__getDataReaderPid()
                self.dataReaderPidLocal = PID  # started by this application
                return
            else:
                # not starting the app
                print(f"{fgColors.bYellow}WARNING: {self.dataReaderName} is not started.{fgColors.endc}")
                return

        elif len(PID) == 1:
            # a single PID found
            if PID == self.dataReaderPidLocal:
                # previously started by this application
                print(f"{fgColors.bBlue}INFO: {self.dataReaderName} already started by this application with PID {PID}.{fgColors.endc}")
                return
            elif PID == self.dataReaderPidRemote:
                # started by another application
                print(f"{fgColors.bBlue}INFO: {self.dataReaderName} already started by another application with PID {PID}.{fgColors.endc}")
                return

        else:
            # found multiple PIDs for the app
            print(f"{fgColors.bYellow}WARNING: multiple PIDs found for {self.dataReaderName}:{fgColors.endc}", end='')
            for pid in PID:
                print(f" {fgColors.bYellow}{pid}{fgColors.endc}", end='')
            print()

        if self.dataReaderPidRemote == None:
            # first call, no PID saved
            self.dataReaderPidRemote = PID
            print(f"{fgColors.bBlue}INFO: {self.dataReaderName} running with PID {PID}.{fgColors.endc}")
        elif (self.dataReaderPidRemote != PID) and (self.dataReaderPidRemote != []):
            # call with different setting
            print(f"{fgColors.bYellow}WARNING: a different PID was previously saved.{fgColors.endc}")


    def __getHexAppPid(self):
        """
        private function to get process id of hdf5 app
        """
        with os.popen(f"pgrep {self.hexAppName}") as hostCmd:
            return hostCmd.read().split()
        return []

    def getHexArgs(self):
        """
        get all arguments and options used to launch hex parser app (hexRead)
        """
        PID = self.__getHexAppPid()
        if len(PID) == 1:
            # a single PID, expected behaviour
            try:
                with os.popen(f"cat /proc/{PID[0]}/cmdline | sed -e 's|\\x00| |g'; echo") as hostCmd:
                    hexAppArgs = hostCmd.read().split()
                    return hexAppArgs
            except Exception as ex:
                # TBD better handling
                return ""    
        else:
            # TBD error management
            if len(PID) == 0:
                print(f"{fgColors.red}ERROR: {self.hexAppName} app is not running on this machine.{fgColors.endc}")
            else:
                print(f"{fgColors.red}ERROR: {self.hexAppName} app is running {len(PID)} times on this machine.{fgColors.endc}")
        return ""


    def getHexInputPath(self, verbose=True):
        """
        get hexApp input path for parsing .hex files
        """
        hexReadArgs = self.getHexArgs()
        if ("-ipath" in hexReadArgs) or ("-i" in hexReadArgs):
            ipath = ""
            try:
                ipathIdx = hexReadArgs.index('-i')
                ipath = hexReadArgs[ipathIdx+1]
            except ValueError:
                try:
                    ipathIdx = hexReadArgs.index('--ipath')
                    ipath = hexReadArgs[ipathIdx+1]
                except ValueError:
                    print("{fgColors.red}ERROR: something wrong happened. {fgColors.endc}")
                    ipathIdx = -1
            if verbose and os.path.isdir(ipath):
                print(f"hexRead read data from {ipath}")
            self.hexInputPath = ipath

    def doneParsingHex(self):
        """
        check if hexApp finished parsing .hex files
        """
        self.getHexInputPath(verbose=False)
        nFiles = 0
        for f in os.listdir(self.hexInputPath):
            if f.endswith(self.hexDataExt):
                nFiles += 1
        return nFiles == 0

    def initHex(self,
                autoStart=False,
                printParsed=False,
                archive=False,
                exportH5=True,
                hexReadExtraArgs=""):
        """
        hdf5 app
        """
        PID = self.__getHexAppPid()

        if len(PID) == 0:
            # no PID found for the app
            if self.launchedFromNfsServer:
                if autoStart:
                    # running on NFS server, trying to start the app
                    # try to fing path to app
                    self.getHexAppPath()
                    print(f"{fgColors.bBlue}INFO: starting '{self.hexAppName}' to read from '{self.serverNfsDataPath}'.{fgColors.endc}")
                    archiveOption = ""
                    if archive:
                        archiveOption = "-a"
                    hexReadOptions = ""
                    if self.hexAppName == "hexRead":
                        # hexRead do not export as HDF5 per default
                        if exportH5:
                            hexReadOptions += " --h5"
                        if printParsed:
                            # debug option to print parsed data (slower execution)
                            hexReadOptions += " --print"
                        hexReadOptions += " --verbose 2"
                    else:
                        # NOTE: hexReadExtraArgs not supported with dma2h5
                        hexReadExtraArgs = ""

                    cmd = f"{os.path.join(self.hexAppPath, self.hexAppName)} " \
                          f"{archiveOption} {hexReadOptions} " \
                          f"-i {self.serverNfsDataPath} " \
                          f"-o {self.hexAppOutPathDefault} " \
                          f"{hexReadExtraArgs} "
                    # NOTE: hexReadExtraArgs must always be placed last because of --module option
                    # command can be long, split per options
                    cmdList = cmd.split(" -")
                    for i, cmdItem in enumerate(cmdList):
                        if i == 0:
                            print(f"{fgColors.bBlue}INFO: {cmdItem}{fgColors.endc}")
                        else:
                            print(f"{fgColors.bBlue}          -{cmdItem}{fgColors.endc}")
                    # run the command
                    self.hexAppPopen = subprocess.Popen(cmd, shell=True,
                                                        stdout=subprocess.DEVNULL,
                                                        encoding='utf-8') # stderr=subprocess.DEVNULL,
                    try:
                        # if an error occurs while starting the app, it is quick, otherwise, it will timeout
                        out, err = self.hexAppPopen.communicate(timeout=0.1)
                        if self.hexAppPopen.returncode:
                            print(f"{fgColors.red}ERROR: {self.hexAppName} app returned exit code {np.int8(self.hexAppPopen.returncode)}.{fgColors.endc}")
                            if out is not None:
                                print(out)
                            if err is not None:
                                print(f"{fgColors.red}{err}{fgColors.endc}")
                            # leave the execution
                            sys.exit()
                    except subprocess.TimeoutExpired:
                        # normal execution
                        pass

                    PID = self.__getHexAppPid()
                    self.hexAppPidLocal = PID  # started by this application

                else:
                    # running on NFS server and app is not started
                    print(f"{fgColors.red}ERROR: '{self.hexAppName}' app is not running on the server.{fgColors.endc}")
                    sys.exit()
            else:
                # not running on the NFS server
                print(f"{fgColors.bYellow}WARNING: '{self.hexAppName}' app is not running on this machine.{fgColors.endc}")

        if len(PID) == 1:
            # a single PID found
            with os.popen(f"cat /proc/{PID[0]}/cmdline | sed -e 's|\\x00| |g'; echo") as hostCmd:
                hexAppArgs = hostCmd.read().split()
            if exportH5:
                try:
                    # NOTE: fix this code for usage with --opath and make sure it is not specified from a module
                    outIdx = hexAppArgs.index('-o')+1
                    h5Path = hexAppArgs[outIdx]
                    if os.path.isdir(h5Path):
                        self.h5Path = h5Path
                        self.hexAppPidRemote = PID
                        print(f"{fgColors.bBlue}INFO: '{self.hexAppName}' is running.{fgColors.endc}")
                        print(f"{fgColors.bBlue}INFO: using {self.h5Path} as path to look for HDF5 data.{fgColors.endc}")
                except (IndexError, ValueError) as ex:
                    pass

        #sys.exit()
        if exportH5 and self.h5Path == None:
            try:
                h5Path = input(f"Could not find the HDF5 export path. Enter the path to use:")
                if os.path.isdir(h5Path):
                    self.h5Path = h5Path
                else:
                    print(f"{fgColors.red}ERROR: HDF5 path {h5Path} does not exists.{fgColors.endc}")
                    sys.exit()
            except KeyboardInterrupt:
                pass

    def init(self, archive=False):
        """
        call all init functions. For a custom init, call each function manually in your script
        """
        try:
            self.initNfs()
            self.initDataReader(dataReaderLaunch=True)
            self.initHex(autoStart=True, archive=archive)
            self.debug()
        except KeyboardInterrupt:
            print("\nKeyboard Interrupt: exit program")
            sys.exit()

    def cleanDataPath(self):
        """
        Clean all files with hexDataExt from serverNfsDataPath
        """
        if self.launchedFromNfsServer and os.path.exists(self.serverNfsDataPath):
            # Make sure the function is called from the nfs server
            print(f"{fgColors.bBlue}INFO: running on NFS server, cleaning data path {self.serverNfsDataPath}.{fgColors.endc}")
            search_pattern = os.path.join(self.serverNfsDataPath, f"*{self.hexDataExt}")
            files_to_delete = glob.glob(search_pattern)
            nDeletedFiles = 0
            for file_path in files_to_delete:
                try:
                    print("|", end="")
                    if nDeletedFiles > 50:
                        print("\r", end="")
                    os.remove(file_path)
                    #print(f"Deleted: {file_path}")

                    nDeletedFiles += 1
                except OSError as e:
                    print(f"Error deleting {file_path}: {e}")
            print(f"\nDeleted {nDeletedFiles} files")

    def close(self):
        if self.dataReaderPidLocal != None:
            # close dataReader if open within this app
            for PID in self.dataReaderPidLocal:
                print(f"closing {self.dataReaderName} at PID {PID}")
                self.sshClient.run(f"kill {PID}")
                self.dataReaderPidLocal = None
        if self.hexAppPidLocal != None:
            # close hexApp if open within this app
            for PID in self.hexAppPidLocal:
                print(f"closing {self.hexAppName} at PID {PID}")
                #os.popen(f"kill {PID}")
                # to kill only if process is still active
                try:
                    #cmd=f"pgrep {self.hexAppName} | grep {self.hexAppPidLocal} | xargs -i {{}} kill {{}}".split(" ")
                    #subprocess.Popen(cmd)
                    os.popen(f"pgrep {self.hexAppName} | grep {self.hexAppPidLocal} | xargs -I {{}} kill {{}}")
                except ImportError as e: # Python was shutting when this was called
                    pass
                self.hexAppPidLocal = None

def clearHexRead():
    for proc in psutil.process_iter(['pid','name']):
        try:
            if 'hexRead'.lower() in proc.info['name'].lower():
                #Get pid and name of any hexRead process
                pid = proc.info['pid']
                name = proc.info['name']
                print(f"{fgColors.blue}Found existing hexRead process PID {pid}{fgColors.endc}")
                #kill process
                proc.kill()
                print(f"{fgColors.blue}hexRead process PID {pid} killed{fgColors.endc}")
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass


if __name__ == "__main__":
    # testing the class
    try:
        # -----------------------------------------------
        # --- open a connection with the ZCU102 board
        # -----------------------------------------------
        sectionPrint("open a connection with the ZCU102 board")
        # parameters of the ZCU102 board
        hostname = "zcudev"
        local_client = sshClientHelper.sshClientFromCfg(hostCfgName=hostname)

        # -----------------------------------------------
        # --- init a zynqDataTransfer object
        # -----------------------------------------------
        sectionPrint("init a zynqDataTransfer object")
        zynq = zynqDataTransfer(sshClientZynq=local_client)
        zynq.initNfs()
        zynq.initDataReader(dataReaderLaunch=False)
        zynq.initDataReader(dataReaderLaunch=True)
        zynq.initDataReader(dataReaderLaunch=False)
        zynq.initHex()
        zynq.init()

        # -----------------------------------------------
        # --- print members of zynq object
        # -----------------------------------------------
        sectionPrint("print members of zynq object")
        zynq.debug()
        zynq.close()
    finally:
        pass
















