"""
ui/global_search_dialog.py
"Search All Projects" — find an item by name across every project
without opening each one individually. Double-click (or Enter) a result
to jump straight to that project with the item selected.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView,
    QFileDialog, QMessageBox, QCheckBox, QComboBox
)
from PySide6.QtCore import Qt, Signal, QTimer

from export.excel_export import export_flat_items_to_excel


class GlobalSearchDialog(QDialog):
    #: emitted with (project_id, item_id) when the user picks a result
    result_chosen = Signal(int, int)

    def __init__(self, parent, db):
        super().__init__(parent)
        self.db = db

        self.setWindowTitle("Search All Projects")
        self.setMinimumSize(680, 440)

        layout = QVBoxLayout(self)

        search_row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search item name, area, supplier, remarks, unit, status\u2026")
        # Debounce: the search scans every item of every project in the
        # scope, so run it once the user pauses typing instead of on
        # literally every keystroke.
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(250)
        self._search_timer.timeout.connect(self._run_search)
        self.search_edit.textChanged.connect(lambda _t: self._search_timer.start())
        self.search_edit.returnPressed.connect(self._choose_current)
        search_row.addWidget(self.search_edit)
        layout.addLayout(search_row)

        scope_row = QHBoxLayout()
        scope_row.addWidget(QLabel("Search in:"))
        self.scope_combo = QComboBox()
        self.scope_combo.addItem("All projects", ("all", None))
        for g in self.db.get_project_groups():
            self.scope_combo.addItem(f"\U0001F4C1 {g['name']} (Group)", ("group", g["id"]))
        for p in self.db.get_projects():
            self.scope_combo.addItem(p["name"], ("project", p["id"]))
        self.scope_combo.currentIndexChanged.connect(lambda _i: self._search_timer.start())
        scope_row.addWidget(self.scope_combo, 1)
        layout.addLayout(scope_row)

        fields_row = QHBoxLayout()
        fields_row.addWidget(QLabel("Match on:"))
        self.field_checks = {}
        for key, label in self.db.SEARCHABLE_ITEM_FIELDS:
            cb = QCheckBox(label)
            cb.setChecked(True)
            cb.stateChanged.connect(lambda _s: self._search_timer.start())
            fields_row.addWidget(cb)
            self.field_checks[key] = cb
        fields_row.addStretch()
        all_btn = QPushButton("All")
        all_btn.clicked.connect(lambda: self._set_all_fields(True))
        none_btn = QPushButton("None")
        none_btn.clicked.connect(lambda: self._set_all_fields(False))
        fields_row.addWidget(all_btn)
        fields_row.addWidget(none_btn)
        layout.addLayout(fields_row)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Match mode:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Contains all words (any order)", "include")
        self.mode_combo.addItem("Contains exact phrase", "contains")
        self.mode_combo.addItem("Exact match", "equal")
        self.mode_combo.setToolTip(
            "\u201cContains all words\u201d finds a cell that has every word you typed, in any order and "
            "even with different punctuation \u2014 e.g. searching \u201cA B C\u201d finds \u201cB, A, C\u201d too. "
            "\u201cContains exact phrase\u201d requires that exact wording in that exact order. "
            "\u201cExact match\u201d requires the whole field to equal what you typed, nothing more."
        )
        self.mode_combo.currentIndexChanged.connect(lambda _i: self._search_timer.start())
        mode_row.addWidget(self.mode_combo, 1)
        layout.addLayout(mode_row)

        self.results_table = QTableWidget()
        self.results_table.setColumnCount(6)
        self.results_table.setHorizontalHeaderLabels(
            ["Item Name", "Project", "Area", "Status", "Total Qty", "Matched In"])
        self.results_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.results_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.results_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.results_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.results_table.doubleClicked.connect(lambda _i: self._choose_current())
        layout.addWidget(self.results_table)

        self.status_label = QLabel("Type at least 2 characters to search.")
        layout.addWidget(self.status_label)

        btn_row = QHBoxLayout()
        self.export_btn = QPushButton("\U0001F4E4 Export Results to Excel")
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self._export_results)
        btn_row.addWidget(self.export_btn)
        btn_row.addStretch()
        open_btn = QPushButton("Open \u2192")
        open_btn.setObjectName("primaryButton")
        open_btn.clicked.connect(self._choose_current)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(close_btn)
        btn_row.addWidget(open_btn)
        layout.addLayout(btn_row)

        self._results = []
        self.search_edit.setFocus()

    def _set_all_fields(self, checked):
        for cb in self.field_checks.values():
            cb.blockSignals(True)
            cb.setChecked(checked)
            cb.blockSignals(False)
        self._search_timer.start()

    def _selected_fields(self):
        return [key for key, cb in self.field_checks.items() if cb.isChecked()]

    def _resolve_scope_project_ids(self):
        kind, ident = self.scope_combo.currentData()
        if kind == "project":
            return [ident]
        if kind == "group":
            return [p["id"] for p in self.db.get_projects_in_group(ident)]
        return None

    def _run_search(self):
        query = self.search_edit.text().strip()
        self.results_table.setRowCount(0)
        if len(query) < 2:
            self.status_label.setText("Type at least 2 characters to search.")
            self._results = []
            self.export_btn.setEnabled(False)
            return

        selected_fields = self._selected_fields()
        if not selected_fields:
            self._results = []
            self.status_label.setText("Check at least one field above to search in.")
            self.export_btn.setEnabled(False)
            return

        project_ids = self._resolve_scope_project_ids()
        mode = self.mode_combo.currentData()
        self._results = self.db.search_items_across_projects(
            query, fields=selected_fields, project_ids=project_ids, mode=mode
        )
        field_key_by_label = {label: key for key, label in self.db.SEARCHABLE_ITEM_FIELDS}
        self.results_table.setRowCount(len(self._results))
        for row, r in enumerate(self._results):
            matched = r.get("matched_fields", [])
            values = [r["item_name"], r["project_name"], r["pump_station"] or "-",
                      r["status"], f"{r['total_quantity'] or 0:,.2f}", ", ".join(matched)]
            for col, val in enumerate(values):
                item = QTableWidgetItem(str(val))
                if col == 0:
                    item.setData(Qt.UserRole, (r["project_id"], r["id"]))
                if col == 5 and matched and matched != ["Item Name"]:
                    # Show what actually matched (e.g. the plate number
                    # buried in Remarks) so the user can confirm the hit
                    # without having to open the item first.
                    lines = [f"{label}: {r.get(field_key_by_label[label], '')}" for label in matched]
                    item.setToolTip("\n".join(lines))
                self.results_table.setItem(row, col, item)

        if self._results:
            self.results_table.selectRow(0)
            self.status_label.setText(f"{len(self._results)} match(es)")
        else:
            self.status_label.setText("No matches.")
        self.export_btn.setEnabled(bool(self._results))

    def _export_results(self):
        if not self._results:
            return
        query = self.search_edit.text().strip()
        scope_text = self.scope_combo.currentText()
        mode_text = self.mode_combo.currentText()
        default_name = f"Search - {query}.xlsx" if query else "Search Results.xlsx"
        path, _ = QFileDialog.getSaveFileName(self, "Export Search Results", default_name,
                                               "Excel Files (*.xlsx)")
        if not path:
            return
        try:
            export_flat_items_to_excel(
                self._results, path, sheet_title="Search Results",
                header_note=(f'Search: "{query}"  \u2014  Scope: {scope_text}  \u2014  Mode: {mode_text}  '
                             f'\u2014  {len(self._results)} result(s)')
            )
        except OSError as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        QMessageBox.information(self, "Done", f"Exported {len(self._results)} result(s) to:\n{path}")

    def _choose_current(self):
        row = self.results_table.currentRow()
        if row < 0 or row >= len(self._results):
            return
        name_item = self.results_table.item(row, 0)
        project_id, item_id = name_item.data(Qt.UserRole)
        self.result_chosen.emit(project_id, item_id)
        self.accept()
