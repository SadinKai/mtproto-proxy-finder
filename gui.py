#!/usr/bin/env python3
"""
MTProto Proxy Finder & Manager - Direct GUI Launcher.
Runs the Tkinter application directly.
"""

import os
import sys

# Ensure current directory is in search path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from checker import launch_gui_app

if __name__ == "__main__":
    launch_gui_app()
