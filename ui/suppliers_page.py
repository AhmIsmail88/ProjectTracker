"""
ui/suppliers_page.py
Standalone "Suppliers" screen — suppliers are shared across all projects.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QMessageBox, QStyle
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QShortcut, QKeySequence

from ui.dialogs import SupplierDialog
from ui.table_utils import configure_interactive_table, EmptyStateTable
from ui.activity_widget import ActivityDialog
from i18n import tr

SUPPLIER_COLUMNS = ["Name", "Contact Person", "Phone", "Email"]


class SuppliersPage(QWidget):
    def __init__(self, db, undo_bar, parent=None):
        super().__init__(parent)
        self.db = db
        self.undo_bar = undo_bar

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)

        title = QLabel(tr("suppliers"))
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(tr("search"))
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._apply_filter)
        layout.addWidget(self.search_edit)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("+ " + tr("add"))
        add_btn.setObjectName("primaryButton")
        add_btn.clicked.connect(self._add_supplier)
        edit_btn = QPushButton(tr("edit"))
        edit_btn.clicked.connect(self._edit_supplier)
        delete_btn = QPushButton(tr("delete"))
        delete_btn.setObjectName("dangerButton")
        delete_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon))
        delete_btn.clicked.connect(self._delete_supplier)
        history_btn = QPushButton("\U0001F553 " + tr("history"))
        history_btn.clicked.connect(self._open_history)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(edit_btn)
        btn_row.addWidget(delete_btn)
        btn_row.addWidget(history_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.table = EmptyStateTable("No suppliers yet \u2014 click \u201c+ Add\u201d to create one.")
        self.table.setColumnCount(len(SUPPLIER_COLUMNS))
        self.table.setHorizontalHeaderLabels(SUPPLIER_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        configure_interactive_table(self.table, first_col_width=220)
        self.table.doubleClicked.connect(lambda _i: self._edit_supplier())
        for key in (Qt.Key_Return, Qt.Key_Enter):
            enter_sc = QShortcut(QKeySequence(key), self.table)
            enter_sc.setContext(Qt.WidgetShortcut)
            enter_sc.activated.connect(self._edit_supplier)
        layout.addWidget(self.table)

        self.reload()

    def reload(self):
        self.table.setSortingEnabled(False)
        suppliers = list(self.db.get_suppliers())
        self.table.setRowCount(len(suppliers))
        for row, s in enumerate(suppliers):
            values = [s["name"], s["contact_person"] or "", s["phone"] or "", s["email"] or ""]
            for col, val in enumerate(values):
                cell = QTableWidgetItem(val)
                if col == 0:
                    cell.setData(Qt.UserRole, s["id"])
                self.table.setItem(row, col, cell)
        self.table.setSortingEnabled(True)
        self.table.resizeRowsToContents()
        self._apply_filter()

    def _apply_filter(self):
        text = self.search_edit.text().strip().lower()
        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, 0)
            show = (not text) or (text in (name_item.text().lower() if name_item else ""))
            self.table.setRowHidden(row, not show)

    def _selected_id(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "No supplier selected", "Select a supplier first.")
            return None
        return self.table.item(row, 0).data(Qt.UserRole)

    def _select_row_by_id(self, supplier_id):
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.data(Qt.UserRole) == supplier_id:
                self.table.selectRow(row)
                self.table.scrollToItem(item)
                self.table.setFocus()
                break

    def _add_supplier(self):
        dlg = SupplierDialog(self)
        if dlg.exec():
            new_id = self.db.add_supplier(**dlg.get_data())
            self.search_edit.clear()  # a stale search filter could hide the new supplier
            self.reload()
            self._select_row_by_id(new_id)

    def _edit_supplier(self):
        sid = self._selected_id()
        if sid is None:
            return
        suppliers = {s["id"]: s for s in self.db.get_suppliers()}
        dlg = SupplierDialog(self, supplier=suppliers[sid])
        if dlg.exec():
            self.db.update_supplier(sid, **dlg.get_data())
            self.reload()

    def _delete_supplier(self):
        sid = self._selected_id()
        if sid is None:
            return
        suppliers = {s["id"]: s for s in self.db.get_suppliers()}
        name = suppliers[sid]["name"]
        self.db.delete_supplier(sid)
        self.reload()

        def _undo():
            self.db.restore_supplier(sid)
            self.reload()

        self.undo_bar.show_message(f"Supplier '{name}' deleted.", _undo)

    def _open_history(self):
        sid = self._selected_id()
        if sid is None:
            return
        suppliers = {s["id"]: s for s in self.db.get_suppliers()}
        name = suppliers[sid]["name"]
        dlg = ActivityDialog(self, self.db, f"{tr('history')} \u2014 {name}", entity_type="supplier", entity_id=sid)
        dlg.exec()
