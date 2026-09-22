"""
ui/icons.py
Small, dependency-free line icons drawn with QPainter.

The sidebar needs a handful of simple glyphs; shipping them as drawn paths
keeps the app self-contained (no SVG plugin, no image files to ship or
theme), and lets every icon be regenerated in whatever colour the current
theme needs - which is exactly what the sidebar does when it switches
between the dark and light palettes, or when a nav item becomes active.
"""

from PySide6.QtCore import QPointF, QRectF, Qt
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


def _menu(p):
    for y in (4.0, 8.0, 12.0):
        p.drawLine(QPointF(2.8, y), QPointF(13.2, y))


def _lang(p):
    p.drawEllipse(QPointF(8.0, 8.0), 6.0, 6.0)
    p.drawLine(QPointF(2.0, 8.0), QPointF(14.0, 8.0))
    p.drawEllipse(QRectF(5.1, 2.0, 5.8, 12.0))


_DRAWERS = {
    "grid": _grid,
    "users": _users,
    "spark": _spark,
    "chart": _chart,
    "list": _list,
    "search": _search,
    "command": _command,
    "theme": _theme,
    "menu": _menu,
    "lang": _lang,
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
