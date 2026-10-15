#----------------------------------------------------------------------------------
#-- Company: GRAMS
#-- Designer: Tommy Rossignol
#--
#-- Create Date: 2023-03-22
#-- Description:
#--     module related to the remote ssh client and functions
#--
#-- Dependencies:
#-- Revision:
#-- Revision 1.0 - File Created
#-- Additional Comments:
#----------------------------------------------------------------------------------
import os
from pssh.clients import SSHClient
import time

# to automatically get the ssh infos from ssh configuration file
from sshconf import read_ssh_config
from os.path import expanduser

# custom modules
from pdcv2_modules.fgColors import fgColors

# class to deal with functions
class sshClient:
    # -----------------------------------------------
    # --- constructor
    # -----------------------------------------------
    def __init__(self, host, user, password):
        self.client = SSHClient(host=host, user=user, password=password)
    def __del__(self):
        print("Disconnecting sshClient")
        self.client.disconnect()

    # -----------------------------------------------
    # --- functions
    # -----------------------------------------------
    # function to send a command
    def run(self, cmd):
        host_out = self.client.run_command(cmd)
        #time.sleep(0.010)
        return host_out.exit_code

    # function to send a command and display the result
    def runPrint(self, cmd, printCmd=True, returnLines=False):
        if printCmd: print(cmd)
        host_out = self.client.run_command(cmd)
        lines_out=[l for l in host_out.stdout] 
        for line in host_out.stdout:
            print(line)
        #time.sleep(0.020)
        time.sleep(0.010)
        return [host_out.exit_code]+lines_out if returnLines else host_out.exit_code

    # function to send a command and display the result and sleep
    def runSleep(self, cmd, msSleep: float):
        host_out = self.client.run_command(cmd)
        #print(f"  [runSleep]: waiting for {msSleep/1000.0} ms")
        time.sleep(msSleep/1000.0)  # time in milliseconds
        return host_out.exit_code

    # function to send a command and display the result and sleep
    def runPrintSleep(self, cmd, msSleep, printCmd=True):
        if printCmd: print(cmd)
        host_out = self.client.run_command(cmd)
        for line in host_out.stdout:
            print(line)
        #exit_code = host_out.exit_code
        time.sleep(msSleep/1000.0)  # time in milliseconds
        return host_out.exit_code

    # function to send a command and return the result as a string
    def runReturnStr(self, cmd, printCmd=True) -> str:
        if printCmd: print(cmd)
        host_out = self.client.run_command(cmd)
        rtnStr=list()
        for line in host_out.stdout:
        #    return line
            rtnStr.append(line)
        #return host_out.stdout
        return rtnStr

    # function to send a command and return the result as a string
    def runReturnInt(self, cmd, printCmd=True) -> int:
        if printCmd: print(cmd)
        host_out = self.client.run_command(cmd)
        for line in host_out.stdout:
            return int(line, base=0);  # automatic base

    # function to send a command and return the result as a string
    def runReturnSplitInt(self, cmd, printCmd=True) -> int:
        if printCmd: print(cmd)
        host_out = self.client.run_command(cmd)
        for line in host_out.stdout:
            return int(line.split()[-1], base=0);  # automatic base

    # function to send a command and return the object
    def runReturn(self, cmd, printCmd=True):
        if printCmd: print(cmd)
        return self.client.run_command(cmd)


# class to deal with functions
class sshClientFromCfg(sshClient):
    def __init__(self,
                 hostCfgName="zcudev",
                 cfgFile="~/.ssh/config"):
        # warning color
        errorLevel = "WARNING"
        errorColor = fgColors.red
        warningColor = fgColors.yellow
        # default host settings
        self.host = '102.180.0.16'
        self.user = 'zynq'

        # try to get settings from config file
        #cfgFile = "~/.ssh/config"
        try:
            userSshCfg = read_ssh_config(expanduser(cfgFile))
            hostCfg = userSshCfg.host(hostCfgName)
            if hostCfg == {}:
                print(f"{errorColor}{errorLevel}:\n"
                      f"    {hostCfgName} does not exists in {cfgFile}\n"
                      f"    Review your '{cfgFile}' file.\n"
                      f"    Using default host '{self.host}' and default user '{self.user}'\n"
                      f"{fgColors.endc}")
            else:
                # normal execution
                self.host = hostCfg['hostname']
                self.user = hostCfg['user']
                try:
                    self.pkey = hostCfg['identityfile']
                except KeyError as ex:
                    print(f"{warningColor}WARNING: 'IdentityFile' not set in {cfgFile}")
                    if (os.path.isfile("~/.ssh/id_rsa_zcu")):
                        # added in setup.sh script
                        self.pkey = "~/.ssh/id_rsa_zcu"
                    else:
                        # fall back file
                        print(f"{warningColor}WARNING:\n"
                              f"    '~/.ssh/id_rsa_zcu' does not exists\n"
                              f"    Have you run 'setup.sh' script on your host ?\n"
                              f"    Using default '~/.ssh/id_rsa'"
                              f"{fgColors.endc}")
                        self.pkey = "~/.ssh/id_rsa"
        except FileNotFoundError:
            print(f"{errorColor}{errorLevel}:\n"
                  f"    {cfgFile} does not exists\n"
                  f"    Create your '{cfgFile}' file."
                  f"{fgColors.endc}")
        except KeyError:
            print(f"{errorColor}{errorLevel}:\n"
                  f"    {hostCfgName} settings must include 'hostname', 'user' and 'identityfile'\n"
                  f"    Review your '{cfgFile}' file."
                  f"{fgColors.endc}")

        # open client
        print(f"Connecting to '{hostCfgName}': host '{self.host}' with user '{self.user}'")
        self.client = SSHClient(host=self.host, user=self.user, pkey=self.pkey)
    # others methods are inherited from sshClient
