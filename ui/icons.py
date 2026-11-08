"""
ui/icons.py
Small, dependency-free line icons drawn with QPainter.

The sidebar needs a handful of simple glyphs; shipping them as drawn paths
keeps the app self-contained (no SVG plugin, no image files to ship or
theme), and lets every icon be regenerated in whatever colour the current
theme needs - which is exactly what the sidebar does when it switches
between the dark and light palettes, or when a nav item becomes active.
"""

from PySide6.QtCore import QPointF, QRectF, Qt, QObject, QEvent, QSize
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

# All glyphs are drawn inside a 16x16 logical box and then scaled, so the
# geometry below stays readable and resolution-independent.
_BOX = 16.0
_STROKE = 1.55


def _grid(p):
    for x, y in ((1.6, 1.6), (8.9, 1.6), (1.6, 8.9), (8.9, 8.9)):
        p.drawRoundedRect(QRectF(x, y, 5.5, 5.5), 1.5, 1.5)


def _users(p):
    p.drawEllipse(QPointF(5.6, 5.0), 2.35, 2.35)
    p.drawArc(QRectF(1.7, 8.0, 7.8, 6.2), 0, 180 * 16)
    p.drawEllipse(QPointF(11.7, 5.8), 1.85, 1.85)
    p.drawArc(QRectF(8.8, 8.6, 6.2, 5.4), 0, 180 * 16)


def _spark(p):
    path = QPainterPath()
    path.moveTo(8.0, 1.4)
    path.cubicTo(8.6, 5.2, 10.8, 7.4, 14.6, 8.0)
    path.cubicTo(10.8, 8.6, 8.6, 10.8, 8.0, 14.6)
    path.cubicTo(7.4, 10.8, 5.2, 8.6, 1.4, 8.0)
    path.cubicTo(5.2, 7.4, 7.4, 5.2, 8.0, 1.4)
    p.drawPath(path)


def _chart(p):
    for x, height in ((2.6, 6.0), (6.2, 10.6), (9.8, 7.6), (13.4, 12.4)):
        p.drawLine(QPointF(x, 14.4), QPointF(x, 14.4 - height))


def _list(p):
    p.drawRoundedRect(QRectF(1.9, 2.4, 12.2, 11.2), 1.8, 1.8)
    p.drawLine(QPointF(1.9, 6.3), QPointF(14.1, 6.3))


def _search(p):
    p.drawEllipse(QPointF(7.0, 7.0), 4.5, 4.5)
    p.drawLine(QPointF(10.4, 10.4), QPointF(14.2, 14.2))


def _command(p):
    p.drawRoundedRect(QRectF(2.3, 2.3, 11.4, 11.4), 2.8, 2.8)
    p.drawLine(QPointF(6.2, 10.3), QPointF(9.9, 5.7))


def _theme(p):
    outer = QPainterPath()
    outer.addEllipse(QPointF(8.0, 8.0), 6.0, 6.0)
    bite = QPainterPath()
    bite.addEllipse(QPointF(11.2, 5.4), 5.3, 5.3)
    p.drawPath(outer.subtracted(bite))


def _gantt(p):
    # three staggered bars: the schedule glyph
    p.drawRoundedRect(QRectF(2.2, 3.0, 7.6, 2.9), 1.2, 1.2)
    p.drawRoundedRect(QRectF(5.0, 7.0, 8.8, 2.9), 1.2, 1.2)
    p.drawRoundedRect(QRectF(3.4, 11.0, 6.8, 2.9), 1.2, 1.2)


def _menu(p):
    for y in (4.0, 8.0, 12.0):
        p.drawLine(QPointF(2.8, y), QPointF(13.2, y))


def _lang(p):
    p.drawEllipse(QPointF(8.0, 8.0), 6.0, 6.0)
    p.drawLine(QPointF(2.0, 8.0), QPointF(14.0, 8.0))
    p.drawEllipse(QRectF(5.1, 2.0, 5.8, 12.0))


def _plus(p):
    p.drawLine(QPointF(8, 2.5), QPointF(8, 13.5))
    p.drawLine(QPointF(2.5, 8), QPointF(13.5, 8))


def _edit(p):
    p.drawLine(QPointF(3, 12), QPointF(12, 3))
    p.drawLine(QPointF(5, 14), QPointF(14, 5))
    p.drawLine(QPointF(12, 3), QPointF(14, 5))
    p.drawLine(QPointF(3, 12), QPointF(2, 15))
    p.drawLine(QPointF(2, 15), QPointF(5, 14))


def _trash(p):
    p.drawLine(QPointF(2, 4), QPointF(14, 4))
    p.drawRoundedRect(QRectF(4, 4, 8, 10), 1, 1)
    p.drawLine(QPointF(6, 2), QPointF(10, 2))
    p.drawLine(QPointF(7, 7), QPointF(7, 11))
    p.drawLine(QPointF(9, 7), QPointF(9, 11))


def _file(p):
    p.drawRoundedRect(QRectF(3, 1.5, 10, 13), 1, 1)
    p.drawLine(QPointF(6, 6), QPointF(10, 6))
    p.drawLine(QPointF(6, 9), QPointF(10, 9))


def _history(p):
    p.drawEllipse(QPointF(8, 8), 6, 6)
    p.drawLine(QPointF(8, 4), QPointF(8, 8))
    p.drawLine(QPointF(8, 8), QPointF(11, 10))


def _copy(p):
    p.drawRoundedRect(QRectF(1.5, 1.5, 9, 10), 1, 1)
    p.drawRoundedRect(QRectF(5.5, 5, 9, 9.5), 1, 1)


def _folder(p):
    path = QPainterPath()
    path.moveTo(1.5, 4)
    path.lineTo(6, 4)
    path.lineTo(8, 6)
    path.lineTo(14.5, 6)
    path.lineTo(14.5, 13)
    path.lineTo(1.5, 13)
    path.closeSubpath()
    p.drawPath(path)


def _transfer(p, incoming=False):
    p.drawLine(QPointF(2, 13), QPointF(14, 13))
    p.drawLine(QPointF(8, 2), QPointF(8, 10))
    tip, wing = (10, 7) if incoming else (2, 5)
    p.drawLine(QPointF(8, tip), QPointF(5, wing))
    p.drawLine(QPointF(8, tip), QPointF(11, wing))


def _logout(p):
    p.drawLine(QPointF(9.5, 2.5), QPointF(2.5, 2.5))
    p.drawLine(QPointF(2.5, 2.5), QPointF(2.5, 13.5))
    p.drawLine(QPointF(2.5, 13.5), QPointF(9.5, 13.5))
    p.drawLine(QPointF(6.5, 8.0), QPointF(13.5, 8.0))
    p.drawLine(QPointF(13.5, 8.0), QPointF(10.8, 5.3))
    p.drawLine(QPointF(13.5, 8.0), QPointF(10.8, 10.7))


_DRAWERS = {
    "plus": _plus, "edit": _edit, "trash": _trash, "file": _file,
    "history": _history, "copy": _copy, "folder": _folder,
    "upload": _transfer, "download": lambda p: _transfer(p, True),
    "grid": _grid,
    "users": _users,
    "spark": _spark,
    "chart": _chart,
    "list": _list,
    "search": _search,
    "command": _command,
    "theme": _theme,
    "gantt": _gantt,
    "menu": _menu,
    "lang": _lang,
    "logout": _logout,
}


def make_icon(name, color, size=32):
    """An QIcon for *name* stroked in *color*. Unknown names yield an empty
    icon rather than raising, so a typo can never take the UI down."""
    drawer = _DRAWERS.get(name)
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    if drawer is None:
        return QIcon(pm)

    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    pen = QPen(QColor(color))
    pen.setWidthF(_STROKE)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.scale(size / _BOX, size / _BOX)
    drawer(p)
    p.end()
    return QIcon(pm)


def apply_standard_icons(root):
    """Use the same line icons on page tools, popup dialogs and menus."""
    from PySide6.QtWidgets import QPushButton, QMenu
    from i18n import tr, tr_text
    from constants import get_theme
    from ui.styles import DARK_TOKENS, LIGHT_TOKENS

    tokens = DARK_TOKENS if get_theme() == "dark" else LIGHT_TOKENS
    labels = {}
    for name, keys in {
        "plus": ("add", "add_item"), "edit": ("edit", "edit_item"),
        "trash": ("delete", "delete_item", "trash"), "history": ("history",),
        "copy": ("duplicate",), "file": ("attachments", "export_pdf", "reports", "save_as_txt"),
        "upload": ("export_excel",), "spark": ("generate_report", "quick_report"),
    }.items():
        for key in keys:
            labels[tr(key).lstrip("+ ")] = name
    for name, captions in {
        "edit": ("Bulk Edit", "Edit Fields…", "Rename"),
        "trash": ("Delete Forever",), "search": ("Find & Replace", "Find & Replace…"),
        "menu": ("More Actions", "More Filters", "Move to Top", "Move to Bottom", "Move to Position…"),
        "folder": ("Manage Groups…", "Manage Groups", "Open", "Open →"),
        "download": ("Import from Excel", "Import Cost Updates", "Import", "Upload File...", "Upload Files…"),
        "copy": ("Duplicate",), "list": ("Details",),
        "upload": ("Export Filtered to Excel", "Export Results to Excel", "Export for Cost Update",
                   "Export Selected Projects", "Export Checked → One Sheet", "Export Filtered View to Excel", "Possibly Forgotten (Excel)"),
        "file": ("Dashboard Summary (PDF)", "Possibly Forgotten (PDF)", "Documents"),
        "history": ("Refresh",), "spark": ("Test AI Connection",),
    }.items():
        for caption in captions:
            labels[tr_text(caption)] = name

    buttons = root.findChildren(QPushButton)
    if isinstance(root, QPushButton):
        buttons.append(root)
    for button in buttons:
        if button.objectName() in ("navButton", "hamburgerButton"):
            continue
        caption = tr_text(button.text())
        name = labels.get(caption.lstrip("+ ").rstrip(" •"))
        if name:
            button.setText(caption.lstrip("+ "))
            color = tokens["on_accent"] if button.objectName() == "primaryButton" else tokens["danger"] if name == "trash" else tokens["text2"]
            button.setIcon(make_icon(name, color))
            button.setIconSize(QSize(16, 16))
    menus = root.findChildren(QMenu)
    if isinstance(root, QMenu):
        menus.append(root)
    for menu in menus:
        for action in menu.actions():
            name = labels.get(action.text().split("\t")[0].lstrip("+ "))
            if name:
                action.setIcon(make_icon(name, tokens["danger"] if name == "trash" else tokens["text2"]))


class StandardIconFilter(QObject):
    def eventFilter(self, watched, event):
        if event.type() == QEvent.Show:
            from PySide6.QtWidgets import QDialog, QDialogButtonBox, QMenu, QPushButton
            if isinstance(watched, (QDialog, QMenu, QPushButton)):
                if isinstance(watched, QDialog):
                    from i18n import tr_text
                    for box in watched.findChildren(QDialogButtonBox):
                        for button in box.buttons():
                            label = button.text().replace("&", "")
                            button.setText(tr_text(label))
                apply_standard_icons(watched)
        return False
