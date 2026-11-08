"""Test-package setup.

The app keeps its UI preferences (language, theme, window layout, the AI
data-sharing answer) in QSettings("ProjectTracker", "MainWindow"), which on
Windows is the real user's registry. Tests must never change those, so
before any app module is imported, QSettings(organization, application) is
redirected to an INI file in a throw-away folder. Every other QSettings
form (an explicit file path + format) is left untouched.
"""
import atexit
import os
import shutil
import tempfile

from PySide6 import QtCore

_REAL_QSETTINGS = QtCore.QSettings
TEST_SETTINGS_DIR = tempfile.mkdtemp(prefix="pt_test_settings_")
atexit.register(shutil.rmtree, TEST_SETTINGS_DIR, True)


class _IsolatedQSettings(_REAL_QSETTINGS):
    def __init__(self, *args, **kwargs):
        if (len(args) >= 2 and isinstance(args[0], str) and isinstance(args[1], str)
                and not kwargs):
            name = f"{args[0]}_{args[1]}.ini".replace(os.sep, "_")
            super().__init__(os.path.join(TEST_SETTINGS_DIR, name), _REAL_QSETTINGS.IniFormat,
                             *args[2:])
        else:
            super().__init__(*args, **kwargs)


QtCore.QSettings = _IsolatedQSettings
