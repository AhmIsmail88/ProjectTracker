"""
ui/import_excel_dialog.py
"Import from Excel" — lets the user bring an existing spreadsheet-based
tracker into the app: pick a file, choose whether it becomes a new
project or gets added to an existing one, map its columns to our fields
(auto-guessed as a starting point), preview a few mapped rows, then
import in the background.
"""

import os

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QPushButton,
    QComboBox, QLineEdit, QRadioButton, QButtonGroup, QFileDialog,
    QMessageBox, QTableWidget, QTableWidgetItem, QProgressBar, QGroupBox
)
from PySide6.QtCore import Qt, QThread, Signal

from importers.excel_import import (
    IMPORT_FIELDS, read_sheet_names, read_headers, guess_mapping,
    preview_rows, import_items_from_excel,
)

NOT_MAPPED = "\u2014 not mapped \u2014"


class _ImportWorker(QThread):
    finished_ok = Signal(dict)
    finished_err = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            result = self.fn()
            self.finished_ok.emit(result)
        except Exception as exc:  # noqa: broad-except — surfaced to the UI
            self.finished_err.emit(str(exc))


class ImportExcelDialog(QDialog):
    def __init__(self, parent, db):
        super().__init__(parent)
        self.db = db
        self.file_path = None
        self.headers = []
        self.header_row_idx = 1
        self.mapping_combos = {}
        self._worker = None

        self.setWindowTitle("Import from Excel")
        self.setMinimumSize(680, 640)

        layout = QVBoxLayout(self)

        # ---- File + sheet ----
        file_row = QHBoxLayout()
        self.file_label = QLabel("No file selected.")
        self.file_label.setWordWrap(True)
        pick_btn = QPushButton("Select Excel File...")
        pick_btn.clicked.connect(self._pick_file)
        file_row.addWidget(pick_btn)
        file_row.addWidget(self.file_label, 1)
        layout.addLayout(file_row)

        sheet_row = QHBoxLayout()
        sheet_row.addWidget(QLabel("Sheet:"))
        self.sheet_combo = QComboBox()
        self.sheet_combo.setEnabled(False)
        self.sheet_combo.currentIndexChanged.connect(self._on_sheet_changed)
        sheet_row.addWidget(self.sheet_combo, 1)
        layout.addLayout(sheet_row)

        # ---- Destination ----
        dest_box = QGroupBox("Import into")
        dest_layout = QVBoxLayout(dest_box)

        new_row = QHBoxLayout()
        self.new_project_radio = QRadioButton("Create a new project:")
        self.new_project_radio.setChecked(True)
        self.new_project_name_edit = QLineEdit()
        new_row.addWidget(self.new_project_radio)
        new_row.addWidget(self.new_project_name_edit, 1)
        dest_layout.addLayout(new_row)

        existing_row = QHBoxLayout()
        self.existing_project_radio = QRadioButton("Add to existing project:")
        self.existing_project_combo = QComboBox()
        for p in self.db.get_projects():
            self.existing_project_combo.addItem(p["name"], p["id"])
        existing_row.addWidget(self.existing_project_radio)
        existing_row.addWidget(self.existing_project_combo, 1)
        dest_layout.addLayout(existing_row)

        dest_group = QButtonGroup(self)
        dest_group.addButton(self.new_project_radio)
        dest_group.addButton(self.existing_project_radio)
        layout.addWidget(dest_box)

        # ---- Column mapping ----
        map_box = QGroupBox("Map spreadsheet columns to fields")
        map_form = QFormLayout(map_box)
        for field_key, label, required in IMPORT_FIELDS:
            combo = QComboBox()
            combo.addItem(NOT_MAPPED)
            combo.currentIndexChanged.connect(self._refresh_preview)
            self.mapping_combos[field_key] = combo
            map_form.addRow((label + " *") if required else label, combo)
        layout.addWidget(map_box)

        # ---- Preview ----
        layout.addWidget(QLabel("<b>Preview</b> (first rows, as they'll be imported):"))
        self.preview_table = QTableWidget()
        self.preview_table.setColumnCount(len(IMPORT_FIELDS))
        self.preview_table.setHorizontalHeaderLabels([label for _k, label, _r in IMPORT_FIELDS])
        self.preview_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.preview_table.setMaximumHeight(180)
        layout.addWidget(self.preview_table)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        # ---- Buttons ----
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        self.import_btn = QPushButton("\U0001F4E5 Import")
        self.import_btn.setObjectName("primaryButton")
        self.import_btn.setEnabled(False)
        self.import_btn.clicked.connect(self._run_import)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(self.import_btn)
        layout.addLayout(btn_row)

        self._imported_project_id = None

    # ------------------------------------------------------------------ #
    def _pick_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Excel file", "", "Excel Files (*.xlsx *.xlsm)")
        if not path:
            return
        self.file_path = path
        self.file_label.setText(os.path.basename(path))
        if not self.new_project_name_edit.text().strip():
            self.new_project_name_edit.setText(os.path.splitext(os.path.basename(path))[0])

        try:
            sheets = read_sheet_names(path)
        except Exception as exc:
            QMessageBox.critical(self, "Could not read file", str(exc))
            return

        self.sheet_combo.blockSignals(True)
        self.sheet_combo.clear()
        self.sheet_combo.addItems(sheets)
        self.sheet_combo.setEnabled(len(sheets) > 1)
        self.sheet_combo.blockSignals(False)
        self._load_sheet(sheets[0] if sheets else None)

    def _on_sheet_changed(self, _index):
        self._load_sheet(self.sheet_combo.currentText() or None)

    def _load_sheet(self, sheet_name):
        if not self.file_path:
            return
        try:
            self.headers, self.header_row_idx = read_headers(self.file_path, sheet_name)
        except Exception as exc:
            QMessageBox.critical(self, "Could not read sheet", str(exc))
            return

        guessed = guess_mapping(self.headers)
        for field_key, combo in self.mapping_combos.items():
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(NOT_MAPPED)
            combo.addItems([h for h in self.headers if h])
            guess = guessed.get(field_key)
            if guess:
                idx = combo.findText(guess)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
            combo.blockSignals(False)

        self._refresh_preview()

    def _current_mapping(self):
        mapping = {}
        for field_key, combo in self.mapping_combos.items():
            text = combo.currentText()
            if text and text != NOT_MAPPED:
                mapping[field_key] = text
        return mapping

    def _refresh_preview(self):
        self.preview_table.setRowCount(0)
        if not self.file_path:
            return
        mapping = self._current_mapping()
        has_name = "item_name" in mapping
        self.import_btn.setEnabled(has_name)
        if not has_name:
            self.status_label.setText("Map at least \u201cItem Name\u201d to continue.")
            return
        self.status_label.setText("")

        try:
            sheet_name = self.sheet_combo.currentText() or None
            rows = preview_rows(self.file_path, sheet_name, self.header_row_idx, mapping, limit=8)
        except Exception as exc:
            self.status_label.setText(f"Preview failed: {exc}")
            return

        self.preview_table.setRowCount(len(rows))
        for r, record in enumerate(rows):
            for c, (field_key, _label, _req) in enumerate(IMPORT_FIELDS):
                value = record.get(field_key)
                self.preview_table.setItem(r, c, QTableWidgetItem("" if value is None else str(value)))
        self.preview_table.resizeRowsToContents()

    # ------------------------------------------------------------------ #
    def _run_import(self):
        if not self.file_path:
            return
        mapping = self._current_mapping()
        if "item_name" not in mapping:
            QMessageBox.information(self, "Missing mapping", "Map at least \u201cItem Name\u201d to continue.")
            return

        if self.new_project_radio.isChecked():
            name = self.new_project_name_edit.text().strip()
            if not name:
                QMessageBox.information(self, "Missing name", "Enter a name for the new project.")
                return
            project_id = self.db.add_project(name)
        else:
            project_id = self.existing_project_combo.currentData()
            if project_id is None:
                QMessageBox.information(self, "No project", "Choose an existing project first.")
                return

        sheet_name = self.sheet_combo.currentText() or None
        header_row_idx = self.header_row_idx
        file_path = self.file_path

        self.import_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.status_label.setText("Importing\u2026")

        def _do_import():
            return import_items_from_excel(self.db, project_id, file_path, sheet_name, header_row_idx, mapping)

        self._imported_project_id = project_id
        self._worker = _ImportWorker(_do_import)
        self._worker.finished_ok.connect(self._on_import_done)
        self._worker.finished_err.connect(self._on_import_error)
        self._worker.start()

    def _on_import_done(self, result):
        self.progress.setVisible(False)
        self.import_btn.setEnabled(True)
        lines = [f"\u2705 Imported {result['imported']} item(s)."]
        if result["skipped"]:
            lines.append(f"\u26A0 Skipped {len(result['skipped'])} row(s) (e.g. {result['skipped'][0]}).")
        if result["unmatched_suppliers"]:
            names = ", ".join(result["unmatched_suppliers"][:5])
            more = "..." if len(result["unmatched_suppliers"]) > 5 else ""
            lines.append(f"\u2139 Supplier(s) not matched (left unassigned): {names}{more}")
        QMessageBox.information(self, "Import complete", "\n".join(lines))
        self.accept()

    def _on_import_error(self, err):
        self.progress.setVisible(False)
        self.import_btn.setEnabled(True)
        QMessageBox.critical(self, "Import failed", err)

    def imported_project_id(self):
        """The project id that was created/added to — set once the dialog
        was accepted after a successful import."""
        return self._imported_project_id
