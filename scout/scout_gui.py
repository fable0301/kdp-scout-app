#!/usr/bin/env python3
"""
KDP Scout Desktop - Quick launcher.

Usage:
    python scout_gui.py

Or after pip install:
    kdp-scout-gui
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scout.gui.app import main

if __name__ == "__main__":
    main()
