"""
ui/pie_chart.py
A small, dependency-free pie chart widget — drawn with QPainter instead
of pulling in a charting library (keeps the packaged .exe lean and
avoids depending on PySide6's optional QtCharts addon, which isn't
guaranteed to be present in every PySide6 install).
"""

from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QPainter, QColor, QPen
from PySide6.QtCore import Qt, QRectF

from constants import chart_label_color


class PieChartWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._slices = []  # list of (label, value, color_hex)
        self.setMinimumSize(160, 160)

    def set_data(self, slices):
        """slices: list of (label, value, color_hex). Values <= 0 are
        dropped (a zero-count status would just be an invisible sliver)."""
        self._slices = [s for s in slices if s[1] > 0]
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        side = min(self.width(), self.height()) - 12
        if side <= 0:
            return
        rect = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)

        total = sum(v for _l, v, _c in self._slices)
        if total <= 0:
            painter.setPen(QColor(chart_label_color()))
            painter.drawText(self.rect(), Qt.AlignCenter, "No data")
            return

        # Drawn as a ring (thick stroked arc) with the total in the middle:
        # a single-status breakdown - the common case in this app, where
        # everything can still be "Not requested" - then reads as "100% of
        # N" instead of a blank disc.
        thickness = max(8.0, side * 0.22)
        ring = rect.adjusted(thickness / 2, thickness / 2, -thickness / 2, -thickness / 2)
        start_angle = 90 * 16  # 12 o'clock, Qt angles in 1/16th degrees
        for _label, value, color in self._slices:
            span = round(value / total * 360 * 16)
            pen = QPen(QColor(color), thickness)
            pen.setCapStyle(Qt.FlatCap)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawArc(ring, start_angle, -span)  # clockwise
            start_angle -= span

        font = painter.font()
        font.setPointSizeF(max(9.0, side * 0.11))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(chart_label_color()))
        painter.drawText(self.rect(), Qt.AlignCenter, f"{total:,}")
