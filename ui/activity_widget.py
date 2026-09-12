"""
ui/activity_widget.py
Reusable "Activity / History" timeline rendering, shared by:
 - the project-level Activity tab (TrackerPage)
 - the per-item History dialog
 - the per-supplier History dialog
 - the per-project History dialog

Renders audit_log rows (see database.py) as a readable, colored timeline.
"""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QListWidget, QListWidgetItem, QLabel, QDialog, QPushButton, QHBoxLayout
from PySide6.QtGui import QColor, QBrush
from PySide6.QtCore import Qt

from i18n import tr

FIELD_LABELS = {
    "name": "Name",
    "item_name": "Item Name",
    "location": "Location",
    "contractor": "Contractor",
    "project_number": "Project Number",
    "currency": "Currency",
    "notes": "Notes",
    "contact_person": "Contact Person",
    "phone": "Phone",
    "email": "Email",
    "pump_station": "Pump Station / Area",
    "supplier_id": "Supplier",
    "unit": "Unit",
    "total_quantity": "Total Quantity",
    "requested_quantity": "Requested Quantity",
    "delivered_quantity": "Delivered Quantity",
    "unit_cost": "Unit Cost",
    "remarks": "Remarks",
    "status": "Status",
    "manual_hold": "On Hold",
    "po_issued": "PO Issued",
    "variance_note": "Over-supply Note",
}

ACTION_ICON = {
    "created": "\u2795",   # +
    "updated": "\u270F\uFE0F",  # pencil
    "deleted": "\U0001F5D1",   # trash
    "restored": "\u21A9\uFE0F",  # undo arrow
    "purged": "\u2620\uFE0F",   # permanent
}

ACTION_COLOR = {
    "created": "#0E9F82",
    "updated": "#2563EB",
    "deleted": "#DC2626",
    "restored": "#9333EA",
    "purged": "#6B7280",
}


def _format_value(v):
    if v is None or v == "":
        return "\u2014"
    return str(v)


def _format_row(row):
    field_label = FIELD_LABELS.get(row["field"], row["field"] or "")
    action = row["action"]
    icon = ACTION_ICON.get(action, "\u2022")
    name = row["entity_name"] or f"#{row['entity_id']}"

    if action == "created":
        text = f"{icon}  \u201c{name}\u201d created"
    elif action == "deleted":
        text = f"{icon}  \u201c{name}\u201d deleted"
    elif action == "restored":
        text = f"{icon}  \u201c{name}\u201d restored"
    elif action == "purged":
        text = f"{icon}  \u201c{name}\u201d permanently deleted"
    elif action == "updated":
        old = _format_value(row["old_value"])
        new = _format_value(row["new_value"])
        text = f"{icon}  \u201c{name}\u201d \u2014 {field_label}: {old} \u2192 {new}"
    else:
        text = f"{icon}  \u201c{name}\u201d {action}"

    return text, ACTION_COLOR.get(action, "#374151")


class ActivityListWidget(QWidget):
    """Embeddable timeline list (used as a tab, not just a dialog)."""

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget)
        self.empty_label = QLabel("No activity recorded yet.")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setVisible(False)
        layout.addWidget(self.empty_label)

    def load(self, **query_kwargs):
        rows = self.db.get_activity(**query_kwargs)
        self.list_widget.clear()
        self.empty_label.setVisible(len(rows) == 0)
        last_date = None
        for row in rows:
            date_part = (row["changed_at"] or "").split(" ")[0]
            if date_part != last_date:
                header = QListWidgetItem(f"\u2500\u2500 {date_part} \u2500\u2500")
                header.setFlags(Qt.NoItemFlags)
                header.setTextAlignment(Qt.AlignCenter)
                header.setForeground(QBrush(QColor("#9AA3B8")))
                self.list_widget.addItem(header)
                last_date = date_part
            text, color = _format_row(row)
            time_part = (row["changed_at"] or "").split(" ")[-1]
            item = QListWidgetItem(f"{time_part}   {text}")
            item.setForeground(QBrush(QColor(color)))
            self.list_widget.addItem(item)


class ActivityDialog(QDialog):
    """Popup version, used for 'History' on a single item/supplier/project."""

    def __init__(self, parent, db, title, **query_kwargs):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(520, 480)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"<b>{title}</b>"))

        self.activity_view = ActivityListWidget(db)
        layout.addWidget(self.activity_view)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self.activity_view.load(**query_kwargs)
