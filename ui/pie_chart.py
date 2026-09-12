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
            painter.setPen(self.palette().color(self.foregroundRole()).lighter(160))
            painter.drawText(self.rect(), Qt.AlignCenter, "No data")
            return

        painter.setPen(QPen(QColor("#00000000")))
        start_angle = 90 * 16  # 12 o'clock, Qt angles in 1/16th degrees
        for _label, value, color in self._slices:
            span = round(value / total * 360 * 16)
            painter.setBrush(QColor(color))
            painter.drawPie(rect, start_angle, -span)  # clockwise
            start_angle -= span
