# class to easily add colors to terminal using f-string
# Example: print(f"{fgColors.green}Some text in green{fgColors.endc}")
# https://en.wikipedia.org/wiki/ANSI_escape_code#3-bit_and_4-bit
class fgColors:
    black = '\033[30m'
    red = '\033[31m'
    green = '\033[32m'
    yellow = '\033[33m'
    blue = '\033[34m'
    magenta = '\033[35m'
    cyan = '\033[36m'
    white = '\033[37m'

    bBlack = '\033[90m'
    bRed = '\033[91m'
    bGreen = '\033[92m'
    bYellow = '\033[93m'
    bBlue = '\033[94m'
    bMagenta = '\033[95m'
    bCyan = '\033[96m'
    bWhite = '\033[97m'

    endc = '\033[0m'
    bold = '\033[1m'
    underline = '\033[4m'
