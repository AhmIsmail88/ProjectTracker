"""
ui/dialogs.py
All popup dialogs used by the main window: add/edit project, add/edit item,
add/edit supplier, and manage attachments for an item.
"""

from i18n import tr_text

import os
import subprocess
import sys
import auth

from PySide6.QtWidgets import (
    QDialog, QFormLayout, QVBoxLayout, QHBoxLayout, QLineEdit, QComboBox,
    QDoubleSpinBox, QTextEdit, QPushButton, QDialogButtonBox, QListWidget,
    QListWidgetItem, QLabel, QFileDialog, QMessageBox, QCheckBox, QWidget,
    QInputDialog, QSplitter, QStackedWidget, QDateEdit, QSpinBox
)
from PySide6.QtCore import Qt, Signal, QDate
from PySide6.QtGui import QColor, QPixmap

from constants import (
    ATTACHMENT_CATEGORIES, POST_DELIVERY_CATEGORIES_SET, CURRENCIES, STATUSES,
    compute_status, is_over_supplied, remaining_to_request, remaining_to_deliver,
    is_delivered_without_request, is_over_requested,
    DELIVERED_NO_REQUEST_COLOR, DELIVERED_NO_REQUEST_TEXT, OVER_REQUEST_COLOR, OVER_REQUEST_TEXT,
)
from i18n import tr

# Optional: PySide6 ships QtPdf, but a trimmed build might not - a missing
# module must only disable the PDF preview, never break the app.
try:
    from PySide6.QtPdf import QPdfDocument
    from PySide6.QtPdfWidgets import QPdfView
    PDF_PREVIEW_AVAILABLE = True
except Exception:  # noqa: BLE001 - optional feature
    QPdfDocument = QPdfView = None
    PDF_PREVIEW_AVAILABLE = False

#: Extensions the preview pane can render itself.
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}


class AutoGrowTextEdit(QTextEdit):
    """A QTextEdit that grows with its content, up to a ceiling.

    Long item names used to be cut off behind a scrollbar inside a
    fixed-height box; this keeps the whole value visible. The ceiling stops a
    pathological paste from pushing the rest of a form off the screen, and
    height_changed lets the dialog grow with the field instead of squeezing
    its other rows.
    """

    height_changed = Signal(int)

    def __init__(self, min_height=56, max_height=200, parent=None):
        super().__init__(parent)
        self._min_height = min_height
        self._max_height = max_height
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setFixedHeight(min_height)
        self.textChanged.connect(self._apply_height)

    def _apply_height(self):
        document = self.document()
        document.setTextWidth(max(1, self.viewport().width()))
        needed = int(document.documentLayout().documentSize().height()) + 6
        target = max(self._min_height, min(needed, self._max_height))
        if target != self.height():
            self.setFixedHeight(target)
            self.height_changed.emit(target)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # The wrap width changed, so the number of lines may have too.
        self._apply_height()


def open_file_externally(path):
    """Open a file with the OS default application (cross platform)."""
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # noqa: only exists on Windows
        elif sys.platform == "darwin":
            subprocess.run(["open", path], check=False)
        else:
            subprocess.run(["xdg-open", path], check=False)
    except Exception as exc:
        QMessageBox.warning(None, "Could not open file", str(exc))


class ProjectDialog(QDialog):
    """Add or edit a project's header information."""

    _NEW_GROUP_SENTINEL = "\u2795 New Group\u2026"

    def __init__(self, parent=None, project=None, db=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle(tr("edit_project") if project else tr("new_project"))
        self.setMinimumWidth(440)

        self.name_edit = QLineEdit()
        self.location_edit = QLineEdit()
        self.contractor_edit = QLineEdit()
        self.project_number_edit = QLineEdit()
        self.currency_combo = QComboBox()
        self.currency_combo.addItems(CURRENCIES)

        self.group_combo = QComboBox()
        self._reload_group_combo()
        self.group_combo.currentIndexChanged.connect(self._on_group_changed)
        self.assignee_combo = QComboBox()
        self._reload_assignee_combo()
        # Only a manager assigns engineers; for other roles the field
        # stays visible but read-only.
        self.assignee_combo.setEnabled(auth.is_manager(self.db))

        self.notes_edit = QTextEdit()
        self.notes_edit.setFixedHeight(70)

        form = QFormLayout()
        form.addRow(tr_text("Project Name*:"), self.name_edit)
        group_label = QLabel(tr_text("Main Project (Group):"))
        group_label.setToolTip(
            tr_text("Which overall/main project this belongs to \u2014 several related section-projects "
            "(e.g. different areas of the same site) can share one Group, so you can select and "
            "report on them together from the Dashboard or AI Assistant.")
        )
        form.addRow(group_label, self.group_combo)
        form.addRow(tr_text("Assigned engineer:"), self.assignee_combo)
        form.addRow(tr_text("Location:"), self.location_edit)
        form.addRow(tr_text("Contractor:"), self.contractor_edit)
        form.addRow(tr_text("Project Number:"), self.project_number_edit)
        form.addRow(tr_text("Default Currency:"), self.currency_combo)
        form.addRow(tr_text("Notes:"), self.notes_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

        self._is_new_project = project is None

        if project:
            self.name_edit.setText(project["name"] or "")
            self.location_edit.setText(project["location"] or "")
            self.contractor_edit.setText(project["contractor"] or "")
            self.project_number_edit.setText(project["project_number"] or "")
            idx = self.currency_combo.findText(project["currency"] or "SAR")
            self.currency_combo.setCurrentIndex(max(idx, 0))
            group_idx = self.group_combo.findData(project["group_id"])
            self.group_combo.setCurrentIndex(max(group_idx, 0))
            self.notes_edit.setPlainText(project["notes"] or "")
            assignee = project["assigned_user_id"] if "assigned_user_id" in project.keys() else None
            combo_index = self.assignee_combo.findData(assignee)
            self.assignee_combo.setCurrentIndex(combo_index if combo_index >= 0 else 0)
        else:
            self.currency_combo.setCurrentText("SAR")

    def _reload_assignee_combo(self):
        self.assignee_combo.addItem(tr_text("Unassigned"), None)
        if not self.db:
            return
        for user in self.db.list_users(active_only=True):
            if user["role"] == "user":
                label = user["display_name"] or user["username"]
                self.assignee_combo.addItem(label, user["id"])

    def selected_assignee_id(self):
        return self.assignee_combo.currentData()

    def _reload_group_combo(self, select_group_id=None):
        self.group_combo.blockSignals(True)
        self.group_combo.clear()
        self.group_combo.addItem("\u2014 No group \u2014", None)
        if self.db:
            for g in self.db.get_project_groups():
                self.group_combo.addItem(g["name"], g["id"])
        self.group_combo.addItem(self._NEW_GROUP_SENTINEL, "__new__")
        if select_group_id is not None:
            idx = self.group_combo.findData(select_group_id)
            self.group_combo.setCurrentIndex(max(idx, 0))
        self.group_combo.blockSignals(False)

    def _on_group_changed(self, _index):
        if self.group_combo.currentData() != "__new__":
            if self._is_new_project:
                self._prefill_from_group(self.group_combo.currentData())
            return
        # "+ New Group…" was picked — prompt for a name, create it, and
        # select the new group instead of leaving the sentinel selected.
        name, ok = QInputDialog.getText(self, "New Group", "Group name (e.g. the overall project name):")
        name = (name or "").strip()
        if not ok or not name or self.db is None or not auth.is_manager(self.db):
            self._reload_group_combo()  # revert to "No group" — nothing was actually picked
            return
        new_id = self.db.add_project_group(name)
        self._reload_group_combo(select_group_id=new_id)
        if self._is_new_project:
            self._prefill_from_group(new_id)

    def _prefill_from_group(self, group_id):
        """When creating a NEW project and picking an existing group that
        already has member projects, copy Location/Contractor/Currency
        from its most recent one as a convenience starting point (still
        freely editable) — this is exactly what keeps a group's projects
        consistent instead of one saying "Madinah" and another "MADINAH"."""
        if group_id is None or self.db is None:
            return
        siblings = self.db.get_projects_in_group(group_id)
        if not siblings:
            return
        latest = siblings[-1]
        if not self.location_edit.text().strip():
            self.location_edit.setText(latest["location"] or "")
        if not self.contractor_edit.text().strip():
            self.contractor_edit.setText(latest["contractor"] or "")
        idx = self.currency_combo.findText(latest["currency"] or "SAR")
        self.currency_combo.setCurrentIndex(max(idx, 0))

    def _on_accept(self):
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "Missing name", "Project name is required.")
            return
        if self.group_combo.currentData() == "__new__":
            QMessageBox.warning(self, "Pick a group", "Finish creating the new group first, or choose \u201cNo group\u201d.")
            return
        self.accept()

    def get_data(self):
        return {
            "name": self.name_edit.text().strip(),
            "location": self.location_edit.text().strip(),
            "contractor": self.contractor_edit.text().strip(),
            "project_number": self.project_number_edit.text().strip(),
            "currency": self.currency_combo.currentText().strip() or "SAR",
            "group_id": self.group_combo.currentData(),
            "notes": self.notes_edit.toPlainText().strip(),
        }


class ManageGroupsDialog(QDialog):
    """Lightweight rename/delete for project groups — groups are just a
    name-plus-defaults label (no soft-delete/trash of their own, unlike
    projects/items/suppliers), so this stays intentionally simple.
    Deleting a group here never deletes its member projects; they just
    become ungrouped."""

    def __init__(self, parent, db):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle(tr_text("Manage Groups"))
        self.setMinimumSize(380, 320)

        layout = QVBoxLayout(self)
        hint = QLabel(
            tr_text("Rename or delete a Main Project (Group). Deleting a group never deletes its "
            "member projects \u2014 they just become ungrouped.")
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget, 1)

        btn_row = QHBoxLayout()
        add_btn = QPushButton(tr_text("+ New"))
        add_btn.clicked.connect(self._add)
        rename_btn = QPushButton(tr_text("Rename"))
        rename_btn.clicked.connect(self._rename)
        delete_btn = QPushButton(tr_text("Delete"))
        delete_btn.setObjectName("dangerButton")
        delete_btn.clicked.connect(self._delete)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(rename_btn)
        btn_row.addWidget(delete_btn)
        layout.addLayout(btn_row)

        close_btn = QPushButton(tr_text("Close"))
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

        self._reload()

    def _reload(self):
        self.list_widget.clear()
        for g in self.db.get_project_groups():
            item = QListWidgetItem(g["name"])
            item.setData(Qt.UserRole, g["id"])
            self.list_widget.addItem(item)

    def _selected_id(self):
        item = self.list_widget.currentItem()
        if item is None:
            QMessageBox.information(self, "No group selected", "Select a group first.")
            return None
        return item.data(Qt.UserRole)

    def _add(self):
        if not auth.is_manager(self.db):
            return
        name, ok = QInputDialog.getText(self, "New Group", "Group name:")
        name = (name or "").strip()
        if ok and name and auth.is_manager(self.db):
            self.db.add_project_group(name)
            self._reload()

    def _rename(self):
        if not auth.is_manager(self.db):
            return
        group_id = self._selected_id()
        if group_id is None:
            return
        current = self.list_widget.currentItem().text()
        name, ok = QInputDialog.getText(self, "Rename Group", "Group name:", text=current)
        name = (name or "").strip()
        if ok and name and auth.is_manager(self.db):
            self.db.update_project_group(group_id, name=name)
            self._reload()

    def _delete(self):
        if not auth.is_manager(self.db):
            return
        group_id = self._selected_id()
        if group_id is None:
            return
        name = self.list_widget.currentItem().text()
        member_count = len(self.db.get_projects_in_group(group_id))
        msg = f"Delete group {name!r}?"
        if member_count:
            msg += f"\n\nIts {member_count} project(s) will NOT be deleted \u2014 they'll just become ungrouped."
        if (QMessageBox.question(self, "Delete Group", msg) == QMessageBox.Yes
                and auth.is_manager(self.db)):
            self.db.delete_project_group(group_id)
            self._reload()


class SupplierDialog(QDialog):
    """Add or edit a supplier record."""

    def __init__(self, parent=None, supplier=None):
        super().__init__(parent)
        self.setWindowTitle(tr("edit") + " " + tr("suppliers") if supplier else tr("suppliers"))
        self.setMinimumWidth(380)

        self.name_edit = QLineEdit()
        self.contact_edit = QLineEdit()
        self.phone_edit = QLineEdit()
        self.email_edit = QLineEdit()
        self.notes_edit = QTextEdit()
        self.notes_edit.setFixedHeight(60)

        form = QFormLayout()
        form.addRow(tr_text("Supplier Name*:"), self.name_edit)
        form.addRow(tr_text("Contact Person:"), self.contact_edit)
        form.addRow(tr_text("Phone:"), self.phone_edit)
        form.addRow(tr_text("Email:"), self.email_edit)
        form.addRow(tr_text("Notes:"), self.notes_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

        if supplier:
            self.name_edit.setText(supplier["name"] or "")
            self.contact_edit.setText(supplier["contact_person"] or "")
            self.phone_edit.setText(supplier["phone"] or "")
            self.email_edit.setText(supplier["email"] or "")
            self.notes_edit.setPlainText(supplier["notes"] or "")

    def _on_accept(self):
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "Missing name", "Supplier name is required.")
            return
        self.accept()

    def get_data(self):
        return {
            "name": self.name_edit.text().strip(),
            "contact_person": self.contact_edit.text().strip(),
            "phone": self.phone_edit.text().strip(),
            "email": self.email_edit.text().strip(),
            "notes": self.notes_edit.toPlainText().strip(),
        }


class ItemDialog(QDialog):
    """Add or edit a single tracked item/material line.

    Status is no longer picked manually — it is computed live from the
    quantities (see constants.compute_status) and shown as a read-only
    chip. The user can still force "On Hold", or mark that a PO has been
    issued, via checkboxes.
    """

    def __init__(self, parent=None, item=None, suppliers=None, db=None, default_currency="SAR"):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle(tr("edit_item") if item else tr("add_item"))
        self.setMinimumWidth(520)
        self._suppliers = list(suppliers or [])

        # Grows with the name so a long description stays fully readable.
        self.item_name_edit = AutoGrowTextEdit(min_height=56, max_height=200)
        self.pump_station_edit = QLineEdit()

        supplier_row = QHBoxLayout()
        self.supplier_combo = QComboBox()
        self._reload_supplier_combo()
        add_supplier_btn = QPushButton("+ " + tr_text("New supplier"))
        add_supplier_btn.setToolTip(tr_text("Add a new supplier without leaving this form"))
        add_supplier_btn.clicked.connect(self._add_supplier_inline)
        supplier_row.addWidget(self.supplier_combo, 1)
        supplier_row.addWidget(add_supplier_btn)

        self.unit_edit = QLineEdit()
        self.currency_combo = QComboBox()
        self.currency_combo.addItems(CURRENCIES)
        self.currency_combo.setCurrentText(default_currency or "SAR")

        self.total_qty_spin = self._make_spin()
        self.requested_qty_spin = self._make_spin()
        self.delivered_qty_spin = self._make_spin()
        self.unit_cost_spin = self._make_spin(decimals=2)

        for spin in (self.total_qty_spin, self.requested_qty_spin, self.delivered_qty_spin):
            spin.valueChanged.connect(self._refresh_computed)

        self.remaining_request_label = QLabel(tr_text("0"))
        self.remaining_deliver_label = QLabel(tr_text("0"))
        self.status_chip = QLabel()
        self.status_chip.setAlignment(Qt.AlignCenter)
        self.status_chip.setFixedHeight(26)

        self.manual_hold_check = QCheckBox(tr_text("On Hold (manual override)"))
        self.po_issued_check = QCheckBox(tr_text("PO Issued"))
        self.manual_hold_check.stateChanged.connect(self._refresh_computed)
        self.po_issued_check.stateChanged.connect(self._refresh_computed)

        self.variance_note_edit = QLineEdit()
        self.variance_note_edit.setPlaceholderText(tr_text("Required when delivered quantity exceeds total quantity"))
        self.variance_note_label = QLabel(tr_text("Over-supply note*:"))
        self.variance_note_edit.setVisible(False)
        self.variance_note_label.setVisible(False)

        self.remarks_edit = QTextEdit()
        self.remarks_edit.setFixedHeight(84)

        form = QFormLayout()
        form.addRow(tr_text("Item Name*:"), self.item_name_edit)
        # Keep the form stable: when the name field grows, the window grows
        # with it instead of compressing the rows underneath.
        self.item_name_edit.height_changed.connect(lambda _h: self.adjustSize())
        form.addRow(tr_text("Pump Station / Area:"), self.pump_station_edit)
        form.addRow(tr_text("Supplier:"), supplier_row)
        form.addRow(tr_text("Unit:"), self.unit_edit)
        form.addRow(tr_text("Currency:"), self.currency_combo)
        form.addRow(tr_text("Total Quantity:"), self.total_qty_spin)
        form.addRow(tr_text("Requested Quantity:"), self.requested_qty_spin)
        form.addRow(tr_text("Delivered Quantity:"), self.delivered_qty_spin)
        form.addRow(tr_text("Unit Cost:"), self.unit_cost_spin)
        form.addRow(tr_text("Remaining to request:"), self.remaining_request_label)
        form.addRow(tr_text("Remaining to deliver:"), self.remaining_deliver_label)
        form.addRow(self.po_issued_check)
        form.addRow(self.manual_hold_check)
        form.addRow(tr_text("Computed Status:"), self.status_chip)
        form.addRow(self.variance_note_label, self.variance_note_edit)
        form.addRow(tr_text("Remarks / Drawing No.:"), self.remarks_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

        if item:
            self.item_name_edit.setPlainText(item["item_name"] or "")
            self.pump_station_edit.setText(item["pump_station"] or "")
            if item["supplier_id"]:
                idx = self.supplier_combo.findData(item["supplier_id"])
                if idx < 0:
                    # The supplier was (soft-)deleted since this item was
                    # last edited. Keep it selectable so editing any other
                    # field here does not silently CLEAR the item's
                    # supplier on save.
                    label = item["supplier_name"] or f"Supplier #{item['supplier_id']}"
                    self.supplier_combo.addItem(f"{label} (deleted)", item["supplier_id"])
                    idx = self.supplier_combo.count() - 1
                self.supplier_combo.setCurrentIndex(idx)
            self.unit_edit.setText(item["unit"] or "")
            currency = (item["currency"] or default_currency or "SAR").strip()
            cur_idx = self.currency_combo.findText(currency)
            if cur_idx < 0 and currency:
                # A currency outside the standard list (e.g. imported from
                # Excel) must survive an edit of some other field instead of
                # silently becoming the first entry (SAR).
                self.currency_combo.addItem(currency)
                cur_idx = self.currency_combo.count() - 1
            self.currency_combo.setCurrentIndex(max(cur_idx, 0))
            for spin, key in ((self.total_qty_spin, "total_quantity"),
                              (self.requested_qty_spin, "requested_quantity"),
                              (self.delivered_qty_spin, "delivered_quantity"),
                              (self.unit_cost_spin, "unit_cost")):
                self._load_spin(spin, item[key])
            self.manual_hold_check.setChecked(bool(item["manual_hold"]))
            self.po_issued_check.setChecked(bool(item["po_issued"]))
            self.variance_note_edit.setText(item["variance_note"] or "")
            self.remarks_edit.setPlainText(item["remarks"] or "")

        self._refresh_computed()

    def _reload_supplier_combo(self, select_id=None):
        self.supplier_combo.blockSignals(True)
        self.supplier_combo.clear()
        self.supplier_combo.addItem(tr_text("(No supplier)"), None)
        for s in self._suppliers:
            self.supplier_combo.addItem(s["name"], s["id"])
        if select_id is not None:
            idx = self.supplier_combo.findData(select_id)
            if idx >= 0:
                self.supplier_combo.setCurrentIndex(idx)
        self.supplier_combo.blockSignals(False)

    def _add_supplier_inline(self):
        """Lets the user add a supplier from inside the item form, so they
        don't have to cancel, go to Suppliers, and come back."""
        dlg = SupplierDialog(self)
        if dlg.exec():
            data = dlg.get_data()
            if self.db is not None:
                new_id = self.db.add_supplier(**data)
                self._suppliers = list(self.db.get_suppliers())
                self._reload_supplier_combo(select_id=new_id)
            else:
                QMessageBox.warning(self, "Unavailable", "Cannot save supplier: no database connection.")

    @staticmethod
    def _make_spin(decimals=2):
        spin = QDoubleSpinBox()
        spin.setDecimals(decimals)
        spin.setMaximum(1_000_000_000)
        spin.setMinimum(0)
        return spin

    _MAX_SPIN_DECIMALS = 6

    @classmethod
    def _decimals_needed(cls, value):
        """Fractional digits *value* really has (2..6), so the spin box can
        show it exactly instead of rounding it to two places."""
        for places in range(2, cls._MAX_SPIN_DECIMALS + 1):
            if abs(round(value, places) - value) < 1e-9:
                return places
        return cls._MAX_SPIN_DECIMALS

    def _load_spin(self, spin, value):
        value = float(value or 0)
        spin.setDecimals(max(spin.decimals(), self._decimals_needed(value)))
        spin.setValue(value)
        # Remember the stored value: if the user leaves this field alone,
        # get_data() returns it untouched (no rounding, no audit noise).
        spin.setProperty("original_value", value)

    @staticmethod
    def _spin_value(spin):
        original = spin.property("original_value")
        if original is not None and abs(spin.value() - round(original, spin.decimals())) < 1e-12:
            return original
        return spin.value()

    def _refresh_computed(self):
        total = self.total_qty_spin.value()
        requested = self.requested_qty_spin.value()
        delivered = self.delivered_qty_spin.value()

        self.remaining_request_label.setText(f"{remaining_to_request(total, requested):,.2f}")
        self.remaining_deliver_label.setText(f"{remaining_to_deliver(total, delivered):,.2f}")

        status = compute_status(
            total, requested, delivered,
            self.manual_hold_check.isChecked(), self.po_issued_check.isChecked(),
        )
        over = is_over_supplied(total, delivered)
        delivered_no_request = is_delivered_without_request(requested, delivered)
        over_requested = is_over_requested(total, requested)

        info = STATUSES.get(status, {"color": "#E5E7EB", "text": "#374151"})
        if over:
            bg, fg, label = "#EDE1FB", "#5B21B6", f"{tr_text(status)} ({tr_text('Over-supplied')})"
        elif delivered_no_request:
            bg, fg = DELIVERED_NO_REQUEST_COLOR, DELIVERED_NO_REQUEST_TEXT
            label = f"{tr_text(status)} ({tr_text('Delivered w/o request')})"
        elif over_requested:
            bg, fg = OVER_REQUEST_COLOR, OVER_REQUEST_TEXT
            label = f"{tr_text(status)} ({tr_text('Over-requested')})"
        else:
            bg, fg, label = info["color"], info["text"], tr_text(status)
        self.status_chip.setText(label)
        self.status_chip.setStyleSheet(
            f"background-color: {bg}; color: {fg}; border-radius: 6px; font-weight: 700; padding: 3px 8px;"
        )

        self.variance_note_label.setVisible(over)
        self.variance_note_edit.setVisible(over)

    def _on_accept(self):
        if not self.item_name_edit.toPlainText().strip():
            QMessageBox.warning(self, "Missing name", "Item name is required.")
            return
        total = self.total_qty_spin.value()
        delivered = self.delivered_qty_spin.value()
        if is_over_supplied(total, delivered) and not self.variance_note_edit.text().strip():
            QMessageBox.warning(
                self, "Note required",
                "Delivered quantity exceeds total quantity. Please add a short note explaining the over-supply."
            )
            self.variance_note_edit.setFocus()
            return
        self.accept()

    def get_data(self):
        return {
            "item_name": self.item_name_edit.toPlainText().strip(),
            "pump_station": self.pump_station_edit.text().strip(),
            "supplier_id": self.supplier_combo.currentData(),
            "unit": self.unit_edit.text().strip(),
            "currency": self.currency_combo.currentText().strip(),
            "total_quantity": self._spin_value(self.total_qty_spin),
            "requested_quantity": self._spin_value(self.requested_qty_spin),
            "delivered_quantity": self._spin_value(self.delivered_qty_spin),
            "unit_cost": self._spin_value(self.unit_cost_spin),
            "manual_hold": self.manual_hold_check.isChecked(),
            "po_issued": self.po_issued_check.isChecked(),
            "variance_note": self.variance_note_edit.text().strip(),
            "remarks": self.remarks_edit.toPlainText().strip(),
        }


class ScheduleActivityDialog(QDialog):
    """Add or edit one activity of a project time schedule.

    Dates are only meaningful together, so both are edited here and validated
    as a range: storing an end before the start would break both the timeline
    and the exported report.
    """

    def __init__(self, parent=None, activity=None, phases=None, project_id=None,
                 db=None, default_start=None):
        super().__init__(parent)
        self.db = db
        self.project_id = project_id
        self.activity = activity
        self.setWindowTitle(tr("schedule_edit_title") if activity else tr("schedule_add_title"))
        self.setMinimumWidth(440)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.name_edit = AutoGrowTextEdit(min_height=32, max_height=120)
        form.addRow(tr("schedule_col_activity") + "*:", self.name_edit)

        self.phase_combo = QComboBox()
        self.phase_combo.setEditable(True)
        existing = [p for p in (phases or []) if p]
        self.phase_combo.addItems(existing)
        self.phase_combo.setCurrentText(existing[0] if existing else "")
        form.addRow(tr("schedule_col_phase") + ":", self.phase_combo)

        today = QDate.currentDate()
        start = today
        end = today.addDays(7)
        if activity:
            for key, target in (("start_date", "start"), ("end_date", "end")):
                value = activity[key]
                if value:
                    parsed = QDate.fromString(str(value)[:10], "yyyy-MM-dd")
                    if parsed.isValid():
                        if target == "start":
                            start = parsed
                        else:
                            end = parsed
        elif default_start is not None:
            start = default_start
            end = default_start.addDays(7)

        self.start_edit = QDateEdit(start)
        self.start_edit.setCalendarPopup(True)
        self.start_edit.setDisplayFormat("yyyy-MM-dd")
        self.end_edit = QDateEdit(end)
        self.end_edit.setCalendarPopup(True)
        self.end_edit.setDisplayFormat("yyyy-MM-dd")
        form.addRow(tr("schedule_col_start") + ":", self.start_edit)
        form.addRow(tr("schedule_col_end") + ":", self.end_edit)

        self.progress_spin = QSpinBox()
        self.progress_spin.setRange(0, 100)
        self.progress_spin.setSuffix(" %")
        form.addRow(tr("schedule_col_progress") + ":", self.progress_spin)

        self.milestone_check = QCheckBox(tr("schedule_col_milestone"))
        form.addRow("", self.milestone_check)

        self.notes_edit = AutoGrowTextEdit(min_height=32, max_height=120)
        form.addRow(tr("schedule_col_notes") + ":", self.notes_edit)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if activity:
            self.name_edit.setPlainText(activity["name"] or "")
            self.phase_combo.setCurrentText(activity["phase"] or "")
            self.progress_spin.setValue(int(activity["progress"] or 0))
            self.milestone_check.setChecked(bool(activity["milestone"]))
            self.notes_edit.setPlainText(activity["notes"] or "")

    def _on_accept(self):
        if not self.name_edit.toPlainText().strip():
            QMessageBox.warning(self, tr("schedule_add_title"), tr("schedule_validate_name"))
            return
        if self.end_edit.date() < self.start_edit.date():
            QMessageBox.warning(self, tr("schedule_add_title"), tr("schedule_validate_dates"))
            return
        self.accept()

    def values(self):
        """The fields to store (dates as YYYY-MM-DD, matching the schema)."""
        return {
            "name": self.name_edit.toPlainText().strip(),
            "phase": self.phase_combo.currentText().strip(),
            "start_date": self.start_edit.date().toString("yyyy-MM-dd"),
            "end_date": self.end_edit.date().toString("yyyy-MM-dd"),
            "progress": self.progress_spin.value(),
            "milestone": self.milestone_check.isChecked(),
            "notes": self.notes_edit.toPlainText().strip(),
        }


# Public alias retained for existing callers.
from ui.attachments_dialog import AttachmentsDialog
