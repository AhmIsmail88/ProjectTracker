# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules



a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    # The window/taskbar icon is loaded at runtime, so it must be bundled
    # as data; the same file is also stamped onto the .exe below.
    datas=[('assets/app.ico', 'assets'), ('assets/fonts', 'assets/fonts'),
           ('assets/spin_up.svg', 'assets'), ('assets/spin_down.svg', 'assets')],
    # Arabic PDF support (imported lazily inside export/pdf_export.py):
    # pin them so PyInstaller always bundles them into the exe.
    # The in-app attachment preview renders PDFs with QtPdf; the import is
    # wrapped in try/except, so list it explicitly.
    hiddenimports=['arabic_reshaper', 'bidi', 'bidi.algorithm',
                   'PySide6.QtPdf', 'PySide6.QtPdfWidgets',
                   # matplotlib imports these by name at runtime
                   # (_check_versions), which PyInstaller cannot see.
                   'kiwisolver', 'kiwisolver._cext', 'kiwisolver.exceptions',
                   'cycler', 'dateutil', 'pyparsing']
                  # matplotlib 3.11 is newer than PyInstaller's hook for it, which
                  # then misses some of its modules (e.g. layout_engine).
                  + collect_submodules('matplotlib', filter=lambda m: '.tests' not in m),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Not used by the app; a broken copy in the build machine's Python
    # otherwise makes PyInstaller's analysis fail.
    excludes=['sqlalchemy'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ProjectTracker',
    icon=['assets/app.ico'],
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
