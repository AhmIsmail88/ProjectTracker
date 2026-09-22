"""
ui/table_utils.py
Small shared helpers for QTableWidget-based screens.
"""

from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QTableWidgetItem, QAbstractItemView, QHeaderView, QFrame, QTableWidget
)
from PySide6.QtCore import Qt, QTimer, QByteArray, QThread, Signal

import config as app_config


class ExportWorker(QThread):
    """Runs a zero-arg export callable off the UI thread, so large exports
    (many items/attachments/projects) don't freeze the window."""
    finished_ok = Signal()
    finished_err = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            self.fn()
            self.finished_ok.emit()
        except Exception as exc:  # noqa: broad-except — surfaced to the UI
            self.finished_err.emit(str(exc))


class EmptyStateTable(QTableWidget):
    """A QTableWidget that shows a centered friendly message instead of a
    bare empty grid when there is nothing to display (shared by the
    Dashboard, Projects and Suppliers tables)."""

    def __init__(self, empty_text, parent=None):
        super().__init__(parent)
        self._empty_text = empty_text

    def set_empty_text(self, text):
        self._empty_text = text
        self.viewport().update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.rowCount() == 0:
            painter = QPainter(self.viewport())
            painter.setPen(self.palette().color(self.foregroundRole()).lighter(160))
            painter.drawText(self.viewport().rect(), Qt.AlignCenter, self._empty_text)
            painter.end()


def make_separator():
    """A thin vertical divider used to group toolbar buttons visually
    (e.g. Edit group | Order group | Attachments group | ...)."""
    line = QFrame()
    line.setFrameShape(QFrame.VLine)
    line.setFrameShadow(QFrame.Sunken)
    return line


class NumericTableWidgetItem(QTableWidgetItem):
    """A table cell that displays a formatted number (e.g. 1,234.50) but
    sorts by its real numeric value instead of alphabetically. Pass
    decimals=0 for whole-number columns (like a row/item number) that
    shouldn't show a trailing ".00"."""

    def __init__(self, value, decimals=2):
        super().__init__(f"{value:,.{decimals}f}")
        self._value = float(value)

    def __lt__(self, other):
        if isinstance(other, NumericTableWidgetItem):
            return self._value < other._value
        return super().__lt__(other)


class AutoFitHeaderView(QHeaderView):
    """A header that behaves like Excel's column/row border double-click:
    double-clicking the resize handle at the edge of a section auto-fits
    that section to its content — and if several sections are selected
    (e.g. you selected 3 columns), ALL of them are auto-fit together,
    not just the one you happened to double-click.
    """

    _EDGE_PX = 6  # width of the "resize handle" zone at the end of a section

    def __init__(self, orientation, table, parent=None):
        super().__init__(orientation, parent)
        self._table = table

    def mouseDoubleClickEvent(self, event):
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        coord = pos.x() if self.orientation() == Qt.Horizontal else pos.y()
        index = self.logicalIndexAt(pos)
        if index < 0:
            super().mouseDoubleClickEvent(event)
            return

        section_start = self.sectionPosition(index)
        section_size = self.sectionSize(index)
        near_trailing_edge = coord >= section_start + section_size - self._EDGE_PX
        if not near_trailing_edge:
            super().mouseDoubleClickEvent(event)
            return

        if self.orientation() == Qt.Horizontal:
            selected = sorted({i.column() for i in self._table.selectedIndexes()})
            targets = selected if (index in selected and len(selected) > 1) else [index]
            for col in targets:
                self._table.resizeColumnToContents(col)
        else:
            selected = sorted({i.row() for i in self._table.selectedIndexes()})
            targets = selected if (index in selected and len(selected) > 1) else [index]
            for row in targets:
                self._table.resizeRowToContents(row)


def configure_interactive_table(table, first_col_width=260, allow_row_drag=False, row_height=28,
                                 layout_key=None):
    """Configures a QTableWidget to be resizable and, optionally, to allow
    manual row drag-reordering. Row drag is OFF by default because it
    conflicts with column sorting (the table looks re-sorted the moment a
    header is clicked); screens that need manual ordering should use
    explicit Move Up / Move Down actions tied to a persisted sort_order
    instead (see TrackerPage).

    Both headers are swapped for AutoFitHeaderView so double-clicking a
    column/row border auto-fits it (and every other selected column/row)
    to its content, the same as Excel.

    Row heights also auto-refit (briefly debounced) whenever a column is
    resized — not just when the table is first populated — so a row that
    grew to fit wrapped text in a narrow column shrinks back down once
    you widen that column again, instead of staying tall forever.

    layout_key: if given, the column order/widths the user drags/resizes
    to are remembered (in config.json) and restored next time this table
    is shown — the user's own arrangement becomes the standing default
    for that table, no extra "save as default" step needed."""
    table.setWordWrap(True)
    table.setSortingEnabled(True)

    h_header = AutoFitHeaderView(Qt.Horizontal, table, table)
    table.setHorizontalHeader(h_header)
    h_header.setSectionResizeMode(QHeaderView.Interactive)
    h_header.setSectionsMovable(True)
    h_header.setStretchLastSection(True)
    h_header.setMinimumSectionSize(50)

    v_header = AutoFitHeaderView(Qt.Vertical, table, table)
    table.setVerticalHeader(v_header)
    v_header.setSectionResizeMode(QHeaderView.Interactive)
    v_header.setDefaultSectionSize(row_height)

    if allow_row_drag:
        table.setDragEnabled(True)
        table.setAcceptDrops(True)
        table.setDropIndicatorShown(True)
        table.setDragDropMode(QAbstractItemView.InternalMove)

    table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

    # Debounced re-fit: sectionResized fires continuously while dragging,
    # so wait for a short pause before actually resizing ~500 rows.
    refit_timer = QTimer(table)
    refit_timer.setSingleShot(True)
    refit_timer.setInterval(150)
    refit_timer.timeout.connect(table.resizeRowsToContents)
    h_header.sectionResized.connect(lambda *_args: refit_timer.start())

    if layout_key:
        restore_table_layout(table, layout_key)

        save_timer = QTimer(table)
        save_timer.setSingleShot(True)
        save_timer.setInterval(400)

        def _persist():
            state_b64 = bytes(h_header.saveState().toBase64()).decode("ascii")
            app_config.save_table_layout(layout_key, state_b64)

        save_timer.timeout.connect(_persist)
        h_header.sectionMoved.connect(lambda *_args: save_timer.start())
        h_header.sectionResized.connect(lambda *_args: save_timer.start())

    if table.columnCount() > 0 and not (layout_key and app_config.load_table_layout(layout_key)):
        table.setColumnWidth(0, first_col_width)


def restore_table_layout(table, layout_key):
    """Re-applies a previously saved column order/width for this table,
    if one was saved. Returns True if a saved layout was found and
    applied (even if the app's column count has since changed and the
    restore couldn't fully apply — Qt handles that mismatch safely)."""
    saved = app_config.load_table_layout(layout_key)
    if not saved:
        return False
    try:
        state = QByteArray.fromBase64(saved.encode("ascii"))
        table.horizontalHeader().restoreState(state)
    except Exception:
        return False
    return True


def reset_table_layout(table, layout_key, default_column_width=260):
    """Clears the saved layout and puts every column back to its default
    left-to-right order and width (used by a 'Reset Columns' action)."""
    app_config.clear_table_layout(layout_key)
    header = table.horizontalHeader()
    for visual in range(table.columnCount()):
        logical = header.logicalIndex(visual)
        if logical != visual:
            header.moveSection(header.visualIndex(logical), visual)
    for col in range(table.columnCount()):
        table.setColumnWidth(col, default_column_width if col == 0 else 120)
    table.resizeColumnsToContents()
