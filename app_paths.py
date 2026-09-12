"""
app_paths.py
Resolves "the folder the app lives in" — used to find config.json, the
database, attachments/, and .env next to it.

This needs special handling for a built .exe: PyInstaller's --onefile
mode extracts the actual code to a temporary folder at runtime, so a
naive os.path.dirname(os.path.abspath(__file__)) would resolve to that
temporary (and later deleted) folder instead of the real folder holding
the .exe — which would silently break .env lookup, and worse, make
config.json (which remembers your chosen data folder) forget itself on
every single run.

sys.frozen / sys.executable is the standard, PyInstaller-documented way
to detect this and get the real .exe location instead.
"""

import os
import sys


def get_app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))
