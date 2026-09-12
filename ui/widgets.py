"""
ui/widgets.py
Small reusable UI pieces.

UndoBar: a bottom "snackbar" that appears after a delete action with a
countdown, showing a message + an Undo button. Deletes throughout the app
are soft deletes (see database.py), so Undo just restores the row; if the
bar times out without being clicked, the row simply stays in the Trash
screen where it can still be restored or purged later.
"""

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Qt, QTimer

from i18n import tr


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
