"""
ui/dialogs.py
All popup dialogs used by the main window: add/edit project, add/edit item,
add/edit supplier, and manage attachments for an item.
"""

import os
import subprocess
import sys

from PySide6.QtWidgets import (
    QDialog, QFormLayout, QVBoxLayout, QHBoxLayout, QLineEdit, QComboBox,
    QDoubleSpinBox, QTextEdit, QPushButton, QDialogButtonBox, QListWidget,
    QListWidgetItem, QLabel, QFileDialog, QMessageBox, QCheckBox, QWidget,
    QInputDialog, QSplitter, QStackedWidget
)
from PySide6.QtCore import Qt
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

        self.notes_edit = QTextEdit()
        self.notes_edit.setFixedHeight(70)

        form = QFormLayout()
        form.addRow("Project Name*:", self.name_edit)
        group_label = QLabel("Main Project (Group):")
        group_label.setToolTip(
            "Which overall/main project this belongs to \u2014 several related section-projects "
            "(e.g. different areas of the same site) can share one Group, so you can select and "
            "report on them together from the Dashboard or AI Assistant."
        )
        form.addRow(group_label, self.group_combo)
        form.addRow("Location:", self.location_edit)
        form.addRow("Contractor:", self.contractor_edit)
        form.addRow("Project Number:", self.project_number_edit)
        form.addRow("Default Currency:", self.currency_combo)
        form.addRow("Notes:", self.notes_edit)

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
        else:
            self.currency_combo.setCurrentText("SAR")

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
        if not ok or not name or self.db is None:
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
        self.setWindowTitle("Manage Groups")
        self.setMinimumSize(380, 320)

        layout = QVBoxLayout(self)
        hint = QLabel(
            "Rename or delete a Main Project (Group). Deleting a group never deletes its "
            "member projects \u2014 they just become ungrouped."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget, 1)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("+ New")
        add_btn.clicked.connect(self._add)
        rename_btn = QPushButton("Rename")
        rename_btn.clicked.connect(self._rename)
        delete_btn = QPushButton("Delete")
        delete_btn.setObjectName("dangerButton")
        delete_btn.clicked.connect(self._delete)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(rename_btn)
        btn_row.addWidget(delete_btn)
        layout.addLayout(btn_row)

        close_btn = QPushButton("Close")
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
        name, ok = QInputDialog.getText(self, "New Group", "Group name:")
        name = (name or "").strip()
        if ok and name:
            self.db.add_project_group(name)
            self._reload()

    def _rename(self):
        group_id = self._selected_id()
        if group_id is None:
            return
        current = self.list_widget.currentItem().text()
        name, ok = QInputDialog.getText(self, "Rename Group", "Group name:", text=current)
        name = (name or "").strip()
        if ok and name:
            self.db.update_project_group(group_id, name=name)
            self._reload()

    def _delete(self):
        group_id = self._selected_id()
        if group_id is None:
            return
        name = self.list_widget.currentItem().text()
        member_count = len(self.db.get_projects_in_group(group_id))
        msg = f"Delete group {name!r}?"
        if member_count:
            msg += f"\n\nIts {member_count} project(s) will NOT be deleted \u2014 they'll just become ungrouped."
        if QMessageBox.question(self, "Delete Group", msg) == QMessageBox.Yes:
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
        form.addRow("Supplier Name*:", self.name_edit)
        form.addRow("Contact Person:", self.contact_edit)
        form.addRow("Phone:", self.phone_edit)
        form.addRow("Email:", self.email_edit)
        form.addRow("Notes:", self.notes_edit)

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

        self.item_name_edit = QTextEdit()
        self.item_name_edit.setFixedHeight(56)
        self.pump_station_edit = QLineEdit()

        supplier_row = QHBoxLayout()
        self.supplier_combo = QComboBox()
        self._reload_supplier_combo()
        add_supplier_btn = QPushButton("+ " + tr("suppliers"))
        add_supplier_btn.setToolTip("Add a new supplier without leaving this form")
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

        self.remaining_request_label = QLabel("0")
        self.remaining_deliver_label = QLabel("0")
        self.status_chip = QLabel()
        self.status_chip.setAlignment(Qt.AlignCenter)
        self.status_chip.setFixedHeight(26)

        self.manual_hold_check = QCheckBox("On Hold (manual override)")
        self.po_issued_check = QCheckBox("PO Issued")
        self.manual_hold_check.stateChanged.connect(self._refresh_computed)
        self.po_issued_check.stateChanged.connect(self._refresh_computed)

        self.variance_note_edit = QLineEdit()
        self.variance_note_edit.setPlaceholderText("Required when delivered quantity exceeds total quantity")
        self.variance_note_label = QLabel("Over-supply note*:")
        self.variance_note_edit.setVisible(False)
        self.variance_note_label.setVisible(False)

        self.remarks_edit = QTextEdit()
        self.remarks_edit.setFixedHeight(56)

        form = QFormLayout()
        form.addRow("Item Name*:", self.item_name_edit)
        form.addRow("Pump Station / Area:", self.pump_station_edit)
        form.addRow("Supplier:", supplier_row)
        form.addRow("Unit:", self.unit_edit)
        form.addRow("Currency:", self.currency_combo)
        form.addRow("Total Quantity:", self.total_qty_spin)
        form.addRow("Requested Quantity:", self.requested_qty_spin)
        form.addRow("Delivered Quantity:", self.delivered_qty_spin)
        form.addRow("Unit Cost:", self.unit_cost_spin)
        form.addRow("Remaining to request:", self.remaining_request_label)
        form.addRow("Remaining to deliver:", self.remaining_deliver_label)
        form.addRow(self.po_issued_check)
        form.addRow(self.manual_hold_check)
        form.addRow("Computed Status:", self.status_chip)
        form.addRow(self.variance_note_label, self.variance_note_edit)
        form.addRow("Remarks / Drawing No.:", self.remarks_edit)

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
            cur_idx = self.currency_combo.findText(item["currency"] or default_currency or "SAR")
            self.currency_combo.setCurrentIndex(max(cur_idx, 0))
            self.total_qty_spin.setValue(item["total_quantity"] or 0)
            self.requested_qty_spin.setValue(item["requested_quantity"] or 0)
            self.delivered_qty_spin.setValue(item["delivered_quantity"] or 0)
            self.unit_cost_spin.setValue(item["unit_cost"] or 0)
            self.manual_hold_check.setChecked(bool(item["manual_hold"]))
            self.po_issued_check.setChecked(bool(item["po_issued"]))
            self.variance_note_edit.setText(item["variance_note"] or "")
            self.remarks_edit.setPlainText(item["remarks"] or "")

        self._refresh_computed()

    def _reload_supplier_combo(self, select_id=None):
        self.supplier_combo.blockSignals(True)
        self.supplier_combo.clear()
        self.supplier_combo.addItem("(No supplier)", None)
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
            bg, fg, label = "#EDE1FB", "#5B21B6", f"{status} (Over-supplied)"
        elif delivered_no_request:
            bg, fg = DELIVERED_NO_REQUEST_COLOR, DELIVERED_NO_REQUEST_TEXT
            label = f"{status} (Delivered w/o request)"
        elif over_requested:
            bg, fg = OVER_REQUEST_COLOR, OVER_REQUEST_TEXT
            label = f"{status} (Over-requested)"
        else:
            bg, fg, label = info["color"], info["text"], status
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
            "total_quantity": self.total_qty_spin.value(),
            "requested_quantity": self.requested_qty_spin.value(),
            "delivered_quantity": self.delivered_qty_spin.value(),
            "unit_cost": self.unit_cost_spin.value(),
            "manual_hold": self.manual_hold_check.isChecked(),
            "po_issued": self.po_issued_check.isChecked(),
            "variance_note": self.variance_note_edit.text().strip(),
            "remarks": self.remarks_edit.toPlainText().strip(),
        }


class AttachmentsDialog(QDialog):
    """Manage PR / PO / Reference files attached to one item.
    Supports uploading multiple files, opening them, and deleting them."""

    def __init__(self, parent, db, item_id, item_name):
        super().__init__(parent)
        self.db = db
        self.item_id = item_id
        self.setWindowTitle(f"Attachments - {item_name}")
        self.setMinimumSize(860, 520)
        self._current_pixmap = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Item: {item_name}"))

        self.category_combo = QComboBox()
        self.category_combo.addItems(ATTACHMENT_CATEGORIES)

        add_row = QHBoxLayout()
        add_row.addWidget(QLabel("Category:"))
        add_row.addWidget(self.category_combo)
        upload_btn = QPushButton("Upload File...")
        upload_btn.clicked.connect(self._upload_file)
        add_row.addWidget(upload_btn)
        layout.addLayout(add_row)

        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(lambda _item: self._open_selected())
        self.list_widget.currentItemChanged.connect(lambda _a, _b: self._update_preview())

        # List on one side, preview on the other: double-click still opens the
        # file in its default application, but the common case (checking what a
        # PR/PO scan actually is) no longer needs to leave the app.
        self.preview_label = QLabel("Select a file to preview.")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setWordWrap(True)
        self.preview_label.setMinimumWidth(320)

        self.preview_stack = QStackedWidget()
        self.preview_stack.addWidget(self.preview_label)
        self.pdf_view = None
        self.pdf_document = None
        if PDF_PREVIEW_AVAILABLE:
            self.pdf_document = QPdfDocument(self)
            self.pdf_view = QPdfView()
            self.pdf_view.setDocument(self.pdf_document)
            self.pdf_view.setPageMode(QPdfView.PageMode.SinglePage)
            self.pdf_view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
            self.preview_stack.addWidget(self.pdf_view)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.list_widget)
        splitter.addWidget(self.preview_stack)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter)

        btn_row = QHBoxLayout()
        open_btn = QPushButton("Open")
        open_btn.clicked.connect(self._open_selected)
        delete_btn = QPushButton("Delete")
        delete_btn.clicked.connect(self._delete_selected)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(open_btn)
        btn_row.addWidget(delete_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self._reload_list()

    def _reload_list(self):
        self.list_widget.clear()
        for att in self.db.get_attachments(self.item_id):
            display = f"[{att['category']}] {att['original_name']}  ({att['uploaded_date']})"
            list_item = QListWidgetItem(display)
            list_item.setData(Qt.UserRole, dict(att))
            self.list_widget.addItem(list_item)

    def _show_preview_message(self, text):
        self._current_pixmap = None
        self.preview_label.setPixmap(QPixmap())   # drop any previous image
        self.preview_label.setText(text)
        self.preview_stack.setCurrentIndex(0)

    def _scaled_preview(self):
        if self._current_pixmap is None:
            return QPixmap()
        return self._current_pixmap.scaled(self.preview_label.size(),
                                           Qt.KeepAspectRatio, Qt.SmoothTransformation)

    def _update_preview(self):
        """Renders the selected attachment in-app: images directly, PDFs via
        QtPdf, anything else just tells the user to use Open."""
        current = self.list_widget.currentItem()
        att = current.data(Qt.UserRole) if current else None
        if not att:
            self._show_preview_message("Select a file to preview.")
            return

        path = att.get("file_path") or ""
        extension = os.path.splitext(path)[1].lower()

        if extension in IMAGE_EXTENSIONS and os.path.isfile(path):
            pixmap = QPixmap(path)
            if pixmap.isNull():
                self._show_preview_message("Could not read this image.")
                return
            self._current_pixmap = pixmap
            self.preview_label.setText("")
            self.preview_label.setPixmap(self._scaled_preview())
            self.preview_stack.setCurrentIndex(0)
            return

        if extension == ".pdf" and PDF_PREVIEW_AVAILABLE and os.path.isfile(path):
            self.pdf_document.load(path)
            if self.pdf_document.status() == QPdfDocument.Status.Ready:
                self._current_pixmap = None
                self.preview_label.setPixmap(QPixmap())
                self.preview_stack.setCurrentIndex(1)
                return
            self._show_preview_message("Could not open this PDF in the app - use Open.")
            return

        self._show_preview_message(
            f"No in-app preview for '{extension or 'this file'}'.\nUse Open to view it."
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._current_pixmap is not None:
            self.preview_label.setPixmap(self._scaled_preview())

    def _upload_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select file to attach")
        if not path:
            return
        category = self.category_combo.currentText()

        if category in POST_DELIVERY_CATEGORIES_SET:
            item = self.db.get_item(self.item_id)
            if not item or item["status"] != "Delivered":
                confirm = QMessageBox.question(
                    self, "Item not marked as Delivered",
                    f"This item's status is '{item['status'] if item else 'unknown'}', not 'Delivered'.\n\n"
                    f"Upload this {category} document anyway?"
                )
                if confirm != QMessageBox.Yes:
                    return

        self.db.add_attachment(self.item_id, category, path)
        self._reload_list()

    def _current_attachment(self):
        current = self.list_widget.currentItem()
        if not current:
            QMessageBox.information(self, "No selection", "Select a file first.")
            return None
        return current.data(Qt.UserRole)

    def _open_selected(self):
        att = self._current_attachment()
        if att:
            open_file_externally(att["file_path"])

    def _delete_selected(self):
        att = self._current_attachment()
        if not att:
            return
        confirm = QMessageBox.question(self, "Delete file", f"Remove '{att['original_name']}'?")
        if confirm == QMessageBox.Yes:
            self.db.delete_attachment(att["id"])
            self._reload_list()
