"""Load the bundled interface font, including in the standalone executable."""
from pathlib import Path
from PySide6.QtGui import QFont, QFontDatabase
from app_paths import get_resource_dir


def install_cairo(app):
    if not getattr(app, "_cairo_loaded", False):
        font_path = Path(get_resource_dir()) / "assets" / "fonts" / "Cairo.ttf"
        font_id = QFontDatabase.addApplicationFont(str(font_path))
        if font_id < 0:
            raise RuntimeError("The bundled Cairo font could not be loaded.")
        app._cairo_loaded = True
    font = QFont("Cairo")
    font.setPixelSize(14)
    app.setFont(font)
