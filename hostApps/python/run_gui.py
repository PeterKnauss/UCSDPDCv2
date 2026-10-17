#!/usr/bin/env python3
"""Control GUI for the PDCv2 scripts.   python run_gui.py [--config-dir DIR]"""
import argparse
import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication
from pdcv2_gui.dialogs import load_settings
from pdcv2_gui.jobs import JobQueue
from pdcv2_gui.main_window import MainWindow
from pdcv2_gui.workspace import Workspace

p = argparse.ArgumentParser(description="PDCv2 control GUI")
p.add_argument("--config-dir", default=str(Path(__file__).resolve().parent / "configs"), help="folder with run.yaml, hardware.yaml, modes/, supplies/")
args = p.parse_args()
app = QApplication(sys.argv)
app.setStyle("Fusion")
window = MainWindow(Workspace(Path(args.config_dir)), JobQueue(), load_settings())
window.show()
sys.exit(app.exec())
