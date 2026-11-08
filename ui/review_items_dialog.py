from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QAbstractItemView
from ui.table_utils import EmptyStateTable, configure_interactive_table
from PySide6.QtWidgets import QTableWidgetItem
from i18n import tr_text


class ReviewItemsDialog(QDialog):
    item_opened = Signal(int, int)

    def __init__(self, db, project_ids=None, criterion="all", parent=None, status=None):
        super().__init__(parent)
        self.setWindowTitle(tr_text(status or {"all": "Total Items", "missing_cost": "Missing Unit Cost",
                                    "missing_documents": "Missing Documents", "stale": "Stale Items"}[criterion]))
        self.resize(980, 560)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr_text("Double-click an item to open its project.")))
        self.table = EmptyStateTable(tr_text("No matching items."))
        headings = ("Item Name", "Project", "Area", "Status", "Unit Cost", "Currency")
        self.table.setColumnCount(len(headings))
        self.table.setHorizontalHeaderLabels([tr_text(label) for label in headings])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        configure_interactive_table(self.table)
        self.table.setWordWrap(False)
        self.table.setSortingEnabled(False)
        projects = [p for p in db.get_projects() if project_ids is None or p["id"] in project_ids]
        grouped = db.get_items_for_projects([p["id"] for p in projects])
        stale = {item["id"] for item in db.get_dashboard_summary(project_ids=project_ids)["stale_items"]} if criterion == "stale" else set()
        rows = []
        for project in projects:
            categories = db.get_item_attachment_categories(project["id"]) if criterion == "missing_documents" else {}
            for item in grouped.get(project["id"], []):
                if status is not None and item["status"] != status:
                    continue
                if criterion == "missing_cost" and item["unit_cost"]:
                    continue
                if criterion == "missing_documents" and {"PR", "PO"}.issubset(categories.get(item["id"], set())):
                    continue
                if criterion == "stale" and item["id"] not in stale:
                    continue
                rows.append((item, project))
        self.table.setRowCount(len(rows))
        for row, (item, project) in enumerate(rows):
            values = (item["item_name"], project["name"], item["pump_station"] or "—", tr_text(item["status"]),
                      f"{item['unit_cost'] or 0:,.2f}", item["currency"] or project["currency"])
            for col, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setToolTip(value)
                if col == 0:
                    cell.setData(Qt.UserRole, (project["id"], item["id"]))
                self.table.setItem(row, col, cell)
        self.table.setSortingEnabled(True)
        self.table.doubleClicked.connect(self._open_current)
        layout.addWidget(self.table, 1)
        button = QPushButton(tr_text("Close"))
        button.clicked.connect(self.accept)
        layout.addWidget(button)

    def _open_current(self, *_):
        cell = self.table.item(self.table.currentRow(), 0)
        if cell:
            self.item_opened.emit(*cell.data(Qt.UserRole))
            self.accept()
