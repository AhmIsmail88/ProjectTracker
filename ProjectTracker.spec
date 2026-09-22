# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    # The window/taskbar icon is loaded at runtime, so it must be bundled
    # as data; the same file is also stamped onto the .exe below.
    datas=[('assets/app.ico', 'assets')],
    # Arabic PDF support (imported lazily inside export/pdf_export.py):
    # pin them so PyInstaller always bundles them into the exe.
    # The in-app attachment preview renders PDFs with QtPdf; the import is
    # wrapped in try/except, so list it explicitly.
    hiddenimports=['arabic_reshaper', 'bidi', 'bidi.algorithm',
                   'PySide6.QtPdf', 'PySide6.QtPdfWidgets'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
