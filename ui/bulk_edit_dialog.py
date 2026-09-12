"""
ui/bulk_edit_dialog.py
"Bulk Edit" — apply the same Supplier / Unit / Currency / Area value to
several selected items at once, instead of opening each one individually.
Each field has its own checkbox: only checked fields are changed, so
partially filling in the dialog never accidentally blanks out fields you
didn't mean to touch.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QPushButton,
    QComboBox, QLineEdit, QCheckBox, QMessageBox, QTextEdit
)

from constants import CURRENCIES


class BulkEditDialog(QDialog):
    def __init__(self, parent, db, item_ids, default_currency="SAR"):
        super().__init__(parent)
        self.db = db
        self.item_ids = list(item_ids)

        self.setWindowTitle("Bulk Edit")
        self.setMinimumWidth(440)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            f"<b>Editing {len(self.item_ids)} item(s)</b><br>"
            f"Only checked fields below will be changed \u2014 leave a field "
            f"unchecked to keep each item's existing value."
        ))

        form = QFormLayout()

        # -- Supplier --
        supplier_row = QHBoxLayout()
        self.supplier_check = QCheckBox()
        self.supplier_combo = QComboBox()
        self.supplier_combo.addItem("\u2014 none \u2014", None)
        for s in self.db.get_suppliers():
            self.supplier_combo.addItem(s["name"], s["id"])
        self.supplier_combo.setEnabled(False)
        self.supplier_check.stateChanged.connect(
            lambda state: self.supplier_combo.setEnabled(bool(state)))
        supplier_row.addWidget(self.supplier_check)
        supplier_row.addWidget(self.supplier_combo, 1)
        form.addRow("Supplier", supplier_row)

        # -- Unit --
        unit_row = QHBoxLayout()
        self.unit_check = QCheckBox()
        self.unit_edit = QLineEdit()
        self.unit_edit.setEnabled(False)
        self.unit_check.stateChanged.connect(lambda state: self.unit_edit.setEnabled(bool(state)))
        unit_row.addWidget(self.unit_check)
        unit_row.addWidget(self.unit_edit, 1)
        form.addRow("Unit", unit_row)

        # -- Currency --
        currency_row = QHBoxLayout()
        self.currency_check = QCheckBox()
        self.currency_combo = QComboBox()
        self.currency_combo.addItems(CURRENCIES)
        self.currency_combo.setCurrentText(default_currency or "SAR")
        self.currency_combo.setEnabled(False)
        self.currency_check.stateChanged.connect(lambda state: self.currency_combo.setEnabled(bool(state)))
        currency_row.addWidget(self.currency_check)
        currency_row.addWidget(self.currency_combo, 1)
        form.addRow("Currency", currency_row)

        # -- Pump Station / Area --
        area_row = QHBoxLayout()
        self.area_check = QCheckBox()
        self.area_edit = QLineEdit()
        self.area_edit.setEnabled(False)
        self.area_check.stateChanged.connect(lambda state: self.area_edit.setEnabled(bool(state)))
        area_row.addWidget(self.area_check)
        area_row.addWidget(self.area_edit, 1)
        form.addRow("Pump Station / Area", area_row)

        # -- Remarks -- (replaces each selected item's Remarks with this exact
        # text; for tweaking existing wording instead of replacing it wholesale,
        # use Find & Replace instead)
        remarks_row = QHBoxLayout()
        self.remarks_check = QCheckBox()
        self.remarks_edit = QTextEdit()
        self.remarks_edit.setFixedHeight(56)
        self.remarks_edit.setEnabled(False)
        self.remarks_check.stateChanged.connect(lambda state: self.remarks_edit.setEnabled(bool(state)))
        remarks_row.addWidget(self.remarks_check)
        remarks_row.addWidget(self.remarks_edit, 1)
        form.addRow("Remarks", remarks_row)

        layout.addLayout(form)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        apply_btn = QPushButton(f"Apply to {len(self.item_ids)} item(s)")
        apply_btn.setObjectName("primaryButton")
        apply_btn.clicked.connect(self._apply)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(apply_btn)
        layout.addLayout(btn_row)

    def _apply(self):
        fields = {}
        if self.supplier_check.isChecked():
            fields["supplier_id"] = self.supplier_combo.currentData()
        if self.unit_check.isChecked():
            fields["unit"] = self.unit_edit.text().strip()
        if self.currency_check.isChecked():
            fields["currency"] = self.currency_combo.currentText()
        if self.area_check.isChecked():
            fields["pump_station"] = self.area_edit.text().strip()
        if self.remarks_check.isChecked():
            fields["remarks"] = self.remarks_edit.toPlainText().strip()

        if not fields:
            QMessageBox.information(self, "Nothing to apply", "Check at least one field to change.")
            return

        self.db.bulk_update_items(self.item_ids, **fields)
        self.accept()
