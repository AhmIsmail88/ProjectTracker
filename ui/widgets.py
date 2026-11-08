"""
ui/widgets.py
Small reusable UI pieces.

UndoBar: a bottom "snackbar" that appears after a delete action with a
countdown, showing a message + an Undo button. Deletes throughout the app
are soft deletes (see database.py), so Undo just restores the row; if the
bar times out without being clicked, the row simply stays in the Trash
screen where it can still be restored or purged later.
"""

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QLayout
from PySide6.QtCore import Qt, QTimer, Signal, QRect, QSize

from i18n import tr


class FlowLayout(QLayout):
    """Wrap filter chips instead of growing the window's minimum width."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []
        self.setSpacing(6)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations()

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._arrange(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._arrange(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def _arrange(self, rect, test):
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x, y, line_height = area.x(), area.y(), 0
        rtl = self.parentWidget() and self.parentWidget().layoutDirection() == Qt.RightToLeft
        for item in self._items:
            size = item.sizeHint()
            if x + size.width() > area.right() + 1 and line_height:
                x, y, line_height = area.x(), y + line_height + self.spacing(), 0
            if not test:
                position = area.right() - (x - area.x()) - size.width() + 1 if rtl else x
                item.setGeometry(QRect(position, y, size.width(), size.height()))
            x += size.width() + self.spacing()
            line_height = max(line_height, size.height())
        return y + line_height - rect.y() + margins.bottom()


class ActionCard(QFrame):
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("clickable", True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.clicked.emit()
            event.accept()
        else:
            super().keyPressEvent(event)


class UndoBar(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("undoBar")
        self.setVisible(False)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        self._undo_callback = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 10, 12, 10)
        self.message_label = QLabel("")
        self.undo_btn = QPushButton()
        self.undo_btn.setObjectName("linkButton")
        self.undo_btn.clicked.connect(self._on_undo_clicked)

        layout.addWidget(self.message_label, 1)
        layout.addWidget(self.undo_btn)

    def show_message(self, message, undo_callback, timeout_ms=7000):
        """Show the bar with *message* and wire the Undo button to
        *undo_callback* (a zero-arg callable)."""
        self._undo_callback = undo_callback
        self.message_label.setText(message)
        self.undo_btn.setText(tr("undo"))
        self.setVisible(True)
        self._timer.start(timeout_ms)

    def _on_undo_clicked(self):
        if self._undo_callback:
            self._undo_callback()
        self._timer.stop()
        self.setVisible(False)
        self._undo_callback = None
