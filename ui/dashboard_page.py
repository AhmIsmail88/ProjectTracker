"""
ui/dashboard_page.py
"Dashboard" — a cross-project overview: pick one or several projects (or
leave the selection empty for "all"), and see their combined status
breakdown (as a pie chart + legend), estimated value per currency, how
much pricing data is still missing, and which "Not requested" items
have sat untouched the longest (possibly forgotten).
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGridLayout,
    QFrame, QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView,
    QFileDialog, QMessageBox, QTreeWidget, QTreeWidgetItem, QSplitter,
    QProgressBar,
)
from PySide6.QtCore import Qt, Signal, QByteArray, QTimer
from PySide6.QtGui import QPainter

from i18n import tr
from ui.table_utils import configure_interactive_table, ExportWorker, EmptyStateTable
from export.excel_export import (
    export_projects_combined_to_excel, export_items_for_cost_update, export_stale_items_to_excel,
)
from export.dashboard_pdf_export import export_dashboard_summary_to_pdf, export_stale_items_to_pdf
from importers.excel_import import import_cost_updates_from_excel
import config as app_config

# Deliberately NOT reusing constants.STATUS_COLORS here: those are pale
# pastel tones designed to sit behind dark text as a table chip — as a
# solid pie-slice fill (especially on the dark theme's dark background)
# they'd look washed out and hard to tell apart. This palette is chosen
# for clear contrast and distinctness as solid fills instead.
_STATUS_PIE_COLORS = {
    "Not requested": "#94A3B8",
    "Partially Requested": "#FBBF24",
    "Requested": "#60A5FA",
    "PO Issued": "#818CF8",
    "Partially Delivered": "#FB923C",
    "Delivered": "#34D399",
    "On Hold": "#F87171",
}
_FALLBACK_COLORS = ["#60A5FA", "#34D399", "#FBBF24", "#F87171", "#A78BFA", "#F472B6", "#38BDF8"]


def _stat_card(title, value_text, severity=None):
    card = QFrame()
    card.setObjectName("statCard")
    if severity:
        card.setProperty("severity", severity)  # "warn" | "bad" — picked up by the stylesheet
    layout = QVBoxLayout(card)
    value_label = QLabel(value_text)
    value_label.setObjectName("statValue")
    title_label = QLabel(title)
    title_label.setObjectName("breadcrumb")
    layout.addWidget(value_label)
    layout.addWidget(title_label)
    return card, value_label


def _fit_table_height(table, row_count, row_height=30, header_height=32, max_rows=6):
    """Sizes a small summary table to its actual content instead of
    leaving a tall block of empty space below 1-2 rows of data."""
    visible_rows = max(1, min(row_count, max_rows))
    table.setFixedHeight(header_height + visible_rows * row_height + 4)


def _color_swatch(color_hex):
    sw = QFrame()
    sw.setFixedSize(12, 12)
    sw.setStyleSheet(f"background-color: {color_hex}; border-radius: 3px;")
    return sw


class DashboardPage(QWidget):
    #: emitted with (project_id, item_id) when the user picks a stale item to jump to
    item_opened = Signal(int, int)

    def __init__(self, db):
        super().__init__()
        self.db = db

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, 1)

        # ---- Left: project picker (which project(s) this dashboard covers) ----
        picker_box = QVBoxLayout()
        picker_box.addWidget(QLabel("<b>Projects</b>"))
        picker_hint = QLabel("Nothing checked = all projects combined. Check a Main Project "
                              "to include all of its projects at once.")
        picker_hint.setObjectName("breadcrumb")
        picker_hint.setWordWrap(True)
        picker_box.addWidget(picker_hint)

        self.project_tree = QTreeWidget()
        self.project_tree.setHeaderHidden(True)
        self.project_tree.itemChanged.connect(self._on_tree_item_changed)
        self._tree_updating = False
        picker_box.addWidget(self.project_tree, 1)

        picker_btn_row = QHBoxLayout()
        select_all_btn = QPushButton("Select All")
        select_all_btn.clicked.connect(lambda: self._set_all_checked(True))
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(lambda: self._set_all_checked(False))
        picker_btn_row.addWidget(select_all_btn)
        picker_btn_row.addWidget(clear_btn)
        picker_box.addLayout(picker_btn_row)

        self.export_checked_btn = QPushButton("\U0001F4E4 Export Checked \u2192 One Sheet")
        self.export_checked_btn.setToolTip(
            "Exports every item from the checked project(s) into ONE combined Excel sheet "
            "(not one tab per project) \u2014 for comparing them side by side."
        )
        self.export_checked_btn.clicked.connect(self._export_checked_projects)
        picker_box.addWidget(self.export_checked_btn)

        picker_box.addWidget(QLabel("<b>Bulk Price Update</b>"))
        self.export_costs_btn = QPushButton("\U0001F4E4 Export for Cost Update")
        self.export_costs_btn.setToolTip(
            "Exports every item from the checked project(s) with an editable Unit Cost column \u2014 "
            "fill in prices in Excel (much faster than one item at a time), then use "
            "\u201cImport Cost Updates\u201d below to apply them."
        )
        self.export_costs_btn.clicked.connect(self._export_for_cost_update)
        picker_box.addWidget(self.export_costs_btn)

        self.import_costs_btn = QPushButton("\U0001F4E5 Import Cost Updates")
        self.import_costs_btn.setToolTip(
            "Reads a file you filled in (from Export for Cost Update) and applies the prices back. "
            "A blank Unit Cost cell is left untouched, so you can fill prices in over several sessions."
        )
        self.import_costs_btn.clicked.connect(self._import_cost_updates)
        picker_box.addWidget(self.import_costs_btn)

        picker_box.addWidget(QLabel("<b>Share Reports</b>"))
        self.export_summary_pdf_btn = QPushButton("\U0001F4C4 Dashboard Summary (PDF)")
        self.export_summary_pdf_btn.setToolTip(
            "A clean, professional PDF for sharing with management or a consultant \u2014 the stat cards, "
            "status breakdown, and estimated value by currency (no item-level list)."
        )
        self.export_summary_pdf_btn.clicked.connect(self._export_summary_pdf)
        picker_box.addWidget(self.export_summary_pdf_btn)

        self.export_stale_pdf_btn = QPushButton("\U0001F4C4 Possibly Forgotten (PDF)")
        self.export_stale_pdf_btn.setToolTip(
            "Just the \u201cPossibly Forgotten\u201d item list, as its own document \u2014 for sharing that on its "
            "own without the rest of the dashboard."
        )
        self.export_stale_pdf_btn.clicked.connect(self._export_stale_pdf)
        picker_box.addWidget(self.export_stale_pdf_btn)

        self.export_stale_excel_btn = QPushButton("\U0001F4CA Possibly Forgotten (Excel)")
        self.export_stale_excel_btn.setToolTip(
            "The same \u201cPossibly Forgotten\u201d list, saved as an Excel sheet instead of a PDF."
        )
        self.export_stale_excel_btn.clicked.connect(self._export_stale_excel)
        picker_box.addWidget(self.export_stale_excel_btn)

        picker_frame = QFrame()
        picker_frame.setLayout(picker_box)
        picker_frame.setMinimumWidth(180)
        splitter.addWidget(picker_frame)

        # ---- Right: everything else ----
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self._content = content
        splitter.addWidget(content)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        saved_state = app_config.load_table_layout("dashboard_splitter")
        if saved_state:
            try:
                splitter.restoreState(QByteArray.fromBase64(saved_state.encode("ascii")))
            except Exception:
                splitter.setSizes([240, 900])
        else:
            splitter.setSizes([240, 900])
        splitter.splitterMoved.connect(
            lambda *_a: app_config.save_table_layout(
                "dashboard_splitter", bytes(splitter.saveState().toBase64()).decode("ascii")
            )
        )

        header_row = QHBoxLayout()
        title = QLabel("Dashboard")
        title.setObjectName("pageTitle")
        header_row.addWidget(title)
        header_row.addStretch()
        refresh_btn = QPushButton("\u21BB Refresh")
        refresh_btn.clicked.connect(self.reload)
        header_row.addWidget(refresh_btn)
        layout.addLayout(header_row)

        # ---- Stat cards ----
        cards_row = QGridLayout()
        cards_row.setSpacing(10)
        self.card_projects, self.val_projects = _stat_card("Projects Shown", "0")
        self.card_items, self.val_items = _stat_card("Total Items", "0")
        self.card_missing_cost, self.val_missing_cost = _stat_card("Missing Unit Cost", "0")
        self.card_stale, self.val_stale = _stat_card("Stale Items", "0")
        cards_row.addWidget(self.card_projects, 0, 0)
        cards_row.addWidget(self.card_items, 0, 1)
        cards_row.addWidget(self.card_missing_cost, 0, 2)
        cards_row.addWidget(self.card_stale, 0, 3)
        layout.addLayout(cards_row)

        # ---- Bento row: three equal cards side by side. The same widgets as
        # before, just arranged as a grid instead of one wide status box above
        # a full-width stale list. ----
        bento = QGridLayout()
        bento.setSpacing(12)
        self.bento = bento
        self._bento_columns = None

        status_card = QFrame()
        self.status_card = status_card
        status_card.setObjectName("statCard")
        status_box = QVBoxLayout(status_card)
        status_box.setContentsMargins(14, 12, 14, 12)
        status_box.setSpacing(8)
        status_box.addWidget(QLabel("<b>Items by Status</b>"))
        # A horizontal breakdown rather than a pie: this app's data can sit
        # entirely in one status (everything "Not requested"), and a pie then
        # draws a meaningless full circle while the bars stay informative and
        # actually fill the card.
        self.status_rows_layout = QVBoxLayout()
        self.status_rows_layout.setSpacing(7)
        self.status_rows_layout.addStretch()
        status_box.addLayout(self.status_rows_layout, 1)
        status_card.setMinimumWidth(260)
        bento.addWidget(status_card, 0, 0)

        value_card = QFrame()
        self.value_card = value_card
        value_card.setObjectName("statCard")
        value_box = QVBoxLayout(value_card)
        value_box.setContentsMargins(14, 12, 14, 12)
        value_box.setSpacing(8)
        value_box.addWidget(QLabel("<b>Estimated Value by Currency</b>"))
        # Amounts as large legible rows, not a two-column table: measured,
        # the table put the currency code at x 35..57 and the amount at
        # x 374..397 - a ~317px void between them in a 12.5px font, so the
        # figures read as small and disconnected.
        self.value_rows_layout = QVBoxLayout()
        self.value_rows_layout.setSpacing(12)
        self.value_rows_layout.addStretch()
        value_box.addLayout(self.value_rows_layout, 1)
        value_card.setMinimumWidth(240)
        bento.addWidget(value_card, 0, 1)

        stale_card = QFrame()
        self.stale_card = stale_card
        stale_card.setObjectName("statCard")
        stale_box = QVBoxLayout(stale_card)
        stale_box.setContentsMargins(14, 12, 14, 12)
        stale_box.setSpacing(8)
        stale_label = QLabel(
            "<b>Possibly Forgotten</b><br>still \u201cNot requested\u201d with no activity "
            "for 14+ days. Double-click to open."
        )
        stale_label.setObjectName("breadcrumb")
        stale_label.setWordWrap(True)
        stale_box.addWidget(stale_label)
        self.stale_table = EmptyStateTable("\U0001F389 Nothing forgotten \u2014 every item has had recent activity.")
        self.stale_table.setColumnCount(4)
        self.stale_table.setHorizontalHeaderLabels(["Item Name", "Project", "Area", "Days Untouched"])
        # "Days Untouched" values are right-aligned - the header should match.
        self.stale_table.horizontalHeaderItem(3).setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.stale_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.stale_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.stale_table.verticalHeader().setVisible(False)
        configure_interactive_table(self.stale_table, first_col_width=200)
        # Every column stays user-draggable (Interactive) - ResizeToContents
        # both locked the headers AND let a single long project name claim
        # 688px, squeezing Item Name down to 264px / four wrapped lines.
        stale_header = self.stale_table.horizontalHeader()
        stale_header.setStretchLastSection(False)
        for _col in range(4):
            stale_header.setSectionResizeMode(_col, QHeaderView.Interactive)
        self._watch_column_resize(self.stale_table)
        self.stale_table.doubleClicked.connect(self._open_stale_item)
        stale_card.setMinimumWidth(300)
        stale_box.addWidget(self.stale_table, 1)

        # Fixed arrangement, chosen for this app's real data: the stale
        # list can hold thousands of rows, so it gets the full width below
        # two summary cards. A 3-up row squeezed its 4 columns into ~400px
        # on a 1913px window and made the list unreadable.
        self.bento.addWidget(self.status_card, 0, 0)
        self.bento.addWidget(self.value_card, 0, 1)
        self.bento.addWidget(self.stale_card, 1, 0, 1, 2)
        # The status breakdown is the wider card (it carries bars and
        # labels); "value by currency" usually holds one or two rows, so it
        # only needs a narrow column. The stale list then spans both.
        self.bento.setColumnStretch(0, 2)
        self.bento.setColumnStretch(1, 1)
        self.bento.setRowStretch(0, 2)
        self.bento.setRowStretch(1, 3)
        layout.addLayout(self.bento, 1)

        self._stale_items = []
        self._status_rows = []
        self._value_rows = []

    # ------------------------------------------------------------------ #
    # Column sizing
    # ------------------------------------------------------------------ #
    #: Starting widths as fractions of the visible width. Deliberately NOT
    #: content-driven: one unusually long value would otherwise claim the
    #: whole column (measured on the user's data: the Project column took
    #: 688px because of a single long name, leaving Item Name 264px).
    _STALE_COL_WEIGHTS = (0.46, 0.22, 0.18, 0.14)

    def _watch_column_resize(self, table):
        """Remembers that the user has sized this table's columns by hand, so
        automatic fitting stops fighting them."""
        table._cols_user_resized = False
        table._cols_fitting = False

        def _on_resized(*_args):
            if not getattr(table, "_cols_fitting", False):
                table._cols_user_resized = True

        table.horizontalHeader().sectionResized.connect(_on_resized)

    def _fit_columns(self, table, weights, force=False):
        """Applies the starting widths, unless the user has already dragged
        the columns themselves."""
        if getattr(table, "_cols_user_resized", False) and not force:
            return
        width = table.viewport().width()
        if width <= 0:
            return
        total = sum(weights)
        table._cols_fitting = True
        try:
            for col, weight in enumerate(weights):
                table.setColumnWidth(col, max(90, int(width * weight / total)))
        finally:
            table._cols_fitting = False

    def _fit_dashboard_columns(self):
        self._fit_columns(self.stale_table, self._STALE_COL_WEIGHTS)

    def showEvent(self, event):
        super().showEvent(event)
        # The viewport width is only final once the layout has settled.
        QTimer.singleShot(0, self._fit_dashboard_columns)

    # ------------------------------------------------------------------ #
    def _set_all_checked(self, checked):
        state = Qt.Checked if checked else Qt.Unchecked
        self.project_tree.blockSignals(True)
        for i in range(self.project_tree.topLevelItemCount()):
            top = self.project_tree.topLevelItem(i)
            top.setCheckState(0, state)
            for j in range(top.childCount()):
                top.child(j).setCheckState(0, state)
        self.project_tree.blockSignals(False)
        self._recompute()

    def _export_checked_projects(self):
        project_ids = self._selected_project_ids()
        if project_ids is None:
            QMessageBox.information(self, "No projects checked",
                                     "Check one or more projects in the list on the left first.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export Checked Projects to Excel",
                                               "Combined Export.xlsx", "Excel Files (*.xlsx)")
        if not path:
            return

        original_text = self.export_checked_btn.text()
        self.export_checked_btn.setEnabled(False)
        self.export_checked_btn.setText("\u23F3 Exporting\u2026")

        def _do_export():
            export_projects_combined_to_excel(self.db, project_ids, path)

        def _on_ok():
            self.export_checked_btn.setEnabled(True)
            self.export_checked_btn.setText(original_text)
            QMessageBox.information(self, "Done",
                                     f"Exported {len(project_ids)} project(s) into one sheet:\n{path}")
            self._export_worker = None

        def _on_err(err):
            self.export_checked_btn.setEnabled(True)
            self.export_checked_btn.setText(original_text)
            QMessageBox.critical(self, "Export failed", err)
            self._export_worker = None

        worker = ExportWorker(_do_export)
        worker.finished_ok.connect(_on_ok)
        worker.finished_err.connect(_on_err)
        self._export_worker = worker  # keep a reference so it isn't garbage-collected mid-run
        worker.start()

    def _export_for_cost_update(self):
        project_ids = self._selected_project_ids()
        if project_ids is None:
            QMessageBox.information(self, "No projects checked",
                                     "Check one or more projects in the list on the left first.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export Items for Cost Update",
                                               "Cost Update.xlsx", "Excel Files (*.xlsx)")
        if not path:
            return

        original_text = self.export_costs_btn.text()
        self.export_costs_btn.setEnabled(False)
        self.export_costs_btn.setText("\u23F3 Exporting\u2026")

        def _do_export():
            export_items_for_cost_update(self.db, project_ids, path)

        def _on_ok():
            self.export_costs_btn.setEnabled(True)
            self.export_costs_btn.setText(original_text)
            QMessageBox.information(
                self, "Done",
                f"Exported items from {len(project_ids)} project(s) to:\n{path}\n\n"
                f"Fill in the Unit Cost column, save, then use \u201cImport Cost Updates\u201d."
            )
            self._cost_export_worker = None

        def _on_err(err):
            self.export_costs_btn.setEnabled(True)
            self.export_costs_btn.setText(original_text)
            QMessageBox.critical(self, "Export failed", err)
            self._cost_export_worker = None

        worker = ExportWorker(_do_export)
        worker.finished_ok.connect(_on_ok)
        worker.finished_err.connect(_on_err)
        self._cost_export_worker = worker
        worker.start()

    def _import_cost_updates(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import Cost Updates", "", "Excel Files (*.xlsx)")
        if not path:
            return

        original_text = self.import_costs_btn.text()
        self.import_costs_btn.setEnabled(False)
        self.import_costs_btn.setText("\u23F3 Importing\u2026")

        result_holder = {}

        def _do_import():
            result_holder["result"] = import_cost_updates_from_excel(self.db, path)

        def _on_ok():
            self.import_costs_btn.setEnabled(True)
            self.import_costs_btn.setText(original_text)
            r = result_holder["result"]
            lines = [f"\u2705 Updated {r['updated']} item(s)."]
            if r["skipped_blank"]:
                lines.append(f"\u2013 {r['skipped_blank']} left unchanged (blank Unit Cost).")
            if r["not_found"]:
                lines.append(f"\u26A0 {r['not_found']} row(s) referred to an item that no longer exists.")
            QMessageBox.information(self, "Import complete", "\n".join(lines))
            self.reload()
            self._cost_import_worker = None

        def _on_err(err):
            self.import_costs_btn.setEnabled(True)
            self.import_costs_btn.setText(original_text)
            QMessageBox.critical(self, "Import failed", err)
            self._cost_import_worker = None

        worker = ExportWorker(_do_import)
        worker.finished_ok.connect(_on_ok)
        worker.finished_err.connect(_on_err)
        self._cost_import_worker = worker
        worker.start()

    def _current_scope_label(self):
        """A readable label for whatever's currently checked — a Group
        name, a single project's name, "All Projects", or a generic
        "Custom Selection" fallback — used as the report's subtitle and
        as part of the suggested filename."""
        project_ids = self._selected_project_ids()
        if project_ids is None:
            return "All Projects"
        if len(project_ids) == 1:
            p = self.db.get_project(project_ids[0])
            return p["name"] if p else "Selected Project"
        for g in self.db.get_project_groups():
            members = {p["id"] for p in self.db.get_projects_in_group(g["id"])}
            if members and members == set(project_ids):
                return g["name"]
        return f"Custom Selection ({len(project_ids)} projects)"

    def _export_summary_pdf(self):
        project_ids = self._selected_project_ids()
        scope_label = self._current_scope_label()
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Dashboard Summary", f"Dashboard Summary - {scope_label}.pdf", "PDF Files (*.pdf)"
        )
        if not path:
            return

        original_text = self.export_summary_pdf_btn.text()
        self.export_summary_pdf_btn.setEnabled(False)
        self.export_summary_pdf_btn.setText("\u23F3 Generating\u2026")

        def _do_export():
            export_dashboard_summary_to_pdf(self.db, project_ids, path, scope_label)

        def _on_ok():
            self.export_summary_pdf_btn.setEnabled(True)
            self.export_summary_pdf_btn.setText(original_text)
            QMessageBox.information(self, "Done", f"Saved:\n{path}")
            self._summary_pdf_worker = None

        def _on_err(err):
            self.export_summary_pdf_btn.setEnabled(True)
            self.export_summary_pdf_btn.setText(original_text)
            QMessageBox.critical(self, "Export failed", err)
            self._summary_pdf_worker = None

        worker = ExportWorker(_do_export)
        worker.finished_ok.connect(_on_ok)
        worker.finished_err.connect(_on_err)
        self._summary_pdf_worker = worker
        worker.start()

    def _export_stale_pdf(self):
        project_ids = self._selected_project_ids()
        scope_label = self._current_scope_label()
        stale_items = self.db.get_dashboard_summary(project_ids=project_ids)["stale_items"]
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Possibly Forgotten", f"Possibly Forgotten - {scope_label}.pdf", "PDF Files (*.pdf)"
        )
        if not path:
            return

        original_text = self.export_stale_pdf_btn.text()
        self.export_stale_pdf_btn.setEnabled(False)
        self.export_stale_pdf_btn.setText("\u23F3 Generating\u2026")

        def _do_export():
            export_stale_items_to_pdf(self.db, stale_items, path, scope_label)

        def _on_ok():
            self.export_stale_pdf_btn.setEnabled(True)
            self.export_stale_pdf_btn.setText(original_text)
            QMessageBox.information(self, "Done", f"Saved:\n{path}")
            self._stale_pdf_worker = None

        def _on_err(err):
            self.export_stale_pdf_btn.setEnabled(True)
            self.export_stale_pdf_btn.setText(original_text)
            QMessageBox.critical(self, "Export failed", err)
            self._stale_pdf_worker = None

        worker = ExportWorker(_do_export)
        worker.finished_ok.connect(_on_ok)
        worker.finished_err.connect(_on_err)
        self._stale_pdf_worker = worker
        worker.start()

    def _export_stale_excel(self):
        project_ids = self._selected_project_ids()
        scope_label = self._current_scope_label()
        stale_items = self.db.get_dashboard_summary(project_ids=project_ids)["stale_items"]
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Possibly Forgotten", f"Possibly Forgotten - {scope_label}.xlsx", "Excel Files (*.xlsx)"
        )
        if not path:
            return

        original_text = self.export_stale_excel_btn.text()
        self.export_stale_excel_btn.setEnabled(False)
        self.export_stale_excel_btn.setText("\u23F3 Exporting\u2026")

        def _do_export():
            export_stale_items_to_excel(stale_items, path, scope_label)

        def _on_ok():
            self.export_stale_excel_btn.setEnabled(True)
            self.export_stale_excel_btn.setText(original_text)
            QMessageBox.information(self, "Done", f"Saved:\n{path}")
            self._stale_excel_worker = None

        def _on_err(err):
            self.export_stale_excel_btn.setEnabled(True)
            self.export_stale_excel_btn.setText(original_text)
            QMessageBox.critical(self, "Export failed", err)
            self._stale_excel_worker = None

        worker = ExportWorker(_do_export)
        worker.finished_ok.connect(_on_ok)
        worker.finished_err.connect(_on_err)
        self._stale_excel_worker = worker
        worker.start()

    def _selected_project_ids(self):
        """None means 'no filter — every project', matching the hint
        text next to the picker. Only leaf (project) items carry a
        project id in Qt.UserRole; group/Ungrouped header items don't,
        so this naturally only ever collects real project ids."""
        ids = []

        def walk(item):
            pid = item.data(0, Qt.UserRole)
            if isinstance(pid, int) and item.checkState(0) == Qt.Checked:
                ids.append(pid)
            for i in range(item.childCount()):
                walk(item.child(i))

        for i in range(self.project_tree.topLevelItemCount()):
            walk(self.project_tree.topLevelItem(i))
        return ids or None

    def _build_group_node(self, label, members, previously_checked, italic=False):
        node = QTreeWidgetItem([label])
        node.setFlags(node.flags() | Qt.ItemIsUserCheckable)
        node.setData(0, Qt.UserRole, None)
        font = node.font(0)
        font.setBold(not italic)
        font.setItalic(italic)
        node.setFont(0, font)

        any_checked = False
        all_checked = bool(members)
        for p in members:
            child = QTreeWidgetItem([p["name"]])
            child.setFlags(child.flags() | Qt.ItemIsUserCheckable)
            child.setData(0, Qt.UserRole, p["id"])
            checked = p["id"] in previously_checked
            child.setCheckState(0, Qt.Checked if checked else Qt.Unchecked)
            node.addChild(child)
            any_checked = any_checked or checked
            all_checked = all_checked and checked

        if all_checked:
            node.setCheckState(0, Qt.Checked)
        elif any_checked:
            node.setCheckState(0, Qt.PartiallyChecked)
        else:
            node.setCheckState(0, Qt.Unchecked)
        node.setExpanded(True)
        return node

    def _reload_project_tree(self):
        previously_checked = set(self._selected_project_ids() or [])
        self.project_tree.blockSignals(True)
        self.project_tree.clear()

        groups = {g["id"]: g["name"] for g in self.db.get_project_groups()}
        by_group = {}
        ungrouped = []
        for p in self.db.get_projects():
            if p["group_id"] is not None and p["group_id"] in groups:
                by_group.setdefault(p["group_id"], []).append(p)
            else:
                ungrouped.append(p)

        for group_id, name in sorted(groups.items(), key=lambda kv: kv[1].lower()):
            node = self._build_group_node(name, by_group.get(group_id, []), previously_checked)
            self.project_tree.addTopLevelItem(node)

        if ungrouped:
            node = self._build_group_node("Ungrouped", ungrouped, previously_checked, italic=True)
            self.project_tree.addTopLevelItem(node)

        self.project_tree.blockSignals(False)

    def _on_tree_item_changed(self, item, _column):
        if self._tree_updating:
            return
        self._tree_updating = True
        try:
            state = item.checkState(0)
            if item.childCount() > 0:
                # A group/Ungrouped header was (un)checked directly —
                # cascade to every project under it. PartiallyChecked is
                # never something the user sets directly (it's only ever
                # computed here from the children below), so there's
                # nothing to cascade in that case.
                if state in (Qt.Checked, Qt.Unchecked):
                    for i in range(item.childCount()):
                        item.child(i).setCheckState(0, state)
            else:
                parent = item.parent()
                if parent is not None:
                    states = [parent.child(i).checkState(0) for i in range(parent.childCount())]
                    if all(s == Qt.Checked for s in states):
                        parent.setCheckState(0, Qt.Checked)
                    elif all(s == Qt.Unchecked for s in states):
                        parent.setCheckState(0, Qt.Unchecked)
                    else:
                        parent.setCheckState(0, Qt.PartiallyChecked)
        finally:
            self._tree_updating = False
        self._recompute()

    def reload(self):
        """Full refresh: re-syncs the project checklist from the database
        (in case a project was added/deleted elsewhere) and recomputes
        the summary. Used by the Refresh button and when this tab is
        opened."""
        self._reload_project_tree()
        self._recompute()

    def _recompute(self):
        """Recomputes the summary for whatever's currently checked,
        without touching the project list itself — used on every
        checkbox toggle so ticking one box doesn't rebuild/flicker the
        whole list."""
        project_ids = self._selected_project_ids()
        summary = self.db.get_dashboard_summary(project_ids=project_ids)
        total_items = summary["item_count"]

        self.val_projects.setText(str(summary["project_count"]))
        self.val_items.setText(str(total_items))

        missing_cost = summary["missing_cost_count"]
        pct = f" ({missing_cost * 100 // total_items}%)" if total_items else ""
        self.val_missing_cost.setText(f"{missing_cost}{pct}")
        self._set_card_severity(self.card_missing_cost,
                                 "bad" if total_items and missing_cost == total_items
                                 else "warn" if missing_cost else None)

        stale_count = len(summary["stale_items"])
        self.val_stale.setText(str(stale_count))
        self._set_card_severity(self.card_stale, "warn" if stale_count else None)

        self._update_status_breakdown(summary["status_counts"])

        self._update_value_list(summary["value_by_currency"])

        self._stale_items = summary["stale_items"]
        self.stale_table.setSortingEnabled(False)  # otherwise a live re-sort mid-loop can scatter
                                                     # a row's later columns onto the wrong row
        self.stale_table.setRowCount(len(self._stale_items))
        for row, it in enumerate(self._stale_items):
            name_item = QTableWidgetItem(it["item_name"])
            name_item.setData(Qt.UserRole, (it["project_id"], it["id"]))
            self.stale_table.setItem(row, 0, name_item)
            self.stale_table.setItem(row, 1, QTableWidgetItem(it["project_name"]))
            self.stale_table.setItem(row, 2, QTableWidgetItem(it["pump_station"] or "-"))
            days_item = QTableWidgetItem(str(it["days_stale"]))
            days_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.stale_table.setItem(row, 3, days_item)
        self.stale_table.setSortingEnabled(True)
        self.stale_table.resizeRowsToContents()
        self.stale_table.viewport().update()
        self._fit_dashboard_columns()

    def _update_value_list(self, value_by_currency):
        """One row per currency: the code, then the amount in a large bold
        figure. Reads clearly with a single row (the usual case here)."""
        for row_widget in self._value_rows:
            row_widget.setParent(None)
        self._value_rows = []

        if not value_by_currency:
            empty = QLabel(tr("value_no_data"))
            empty.setObjectName("breadcrumb")
            self.value_rows_layout.insertWidget(self.value_rows_layout.count() - 1, empty)
            self._value_rows.append(empty)
            return

        for currency, value in sorted(value_by_currency.items(), key=lambda kv: -kv[1]):
            label = currency if currency and currency != "?" else "(No currency set)"

            wrapper = QWidget()
            line = QHBoxLayout(wrapper)
            line.setContentsMargins(0, 0, 0, 0)
            line.setSpacing(10)

            code = QLabel(label)
            code.setObjectName("breadcrumb")
            line.addWidget(code)
            line.addStretch()

            amount = QLabel(f"{value:,.2f}")
            amount.setStyleSheet("font-size: 17px; font-weight: 700; background: transparent;")
            amount.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            line.addWidget(amount)

            self.value_rows_layout.insertWidget(self.value_rows_layout.count() - 1, wrapper)
            self._value_rows.append(wrapper)

    def _update_status_breakdown(self, status_counts):
        """One row per status: colour dot, name, a bar proportional to its
        share, the count and the percentage.

        Deliberately not a pie chart - most projects here sit in a single
        status, and a one-slice pie says nothing while leaving the card
        almost empty."""
        ordered = sorted(status_counts.items(), key=lambda kv: -kv[1])
        total = sum(count for _status, count in ordered) or 1

        for row_widget in self._status_rows:
            row_widget.setParent(None)
        self._status_rows = []

        for i, (status, count) in enumerate(ordered):
            color = _STATUS_PIE_COLORS.get(status) or _FALLBACK_COLORS[i % len(_FALLBACK_COLORS)]

            wrapper = QWidget()
            line = QHBoxLayout(wrapper)
            line.setContentsMargins(0, 0, 0, 0)
            line.setSpacing(8)

            line.addWidget(_color_swatch(color))

            # RTL-aware: the label keeps its text and Qt mirrors the row.
            name = QLabel(status)
            name.setObjectName("breadcrumb")
            name.setMinimumWidth(120)
            line.addWidget(name)

            bar = QProgressBar()
            bar.setRange(0, total)
            bar.setValue(count)
            bar.setTextVisible(False)
            bar.setFixedHeight(6)
            line.addWidget(bar, 1)

            count_label = QLabel(f"{count:,}")
            count_label.setObjectName("breadcrumb")
            count_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            count_label.setMinimumWidth(56)
            line.addWidget(count_label)

            pct_label = QLabel(f"{count * 100 // total}%")
            pct_label.setObjectName("breadcrumb")
            pct_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            pct_label.setMinimumWidth(42)
            line.addWidget(pct_label)

            self.status_rows_layout.insertWidget(self.status_rows_layout.count() - 1, wrapper)
            self._status_rows.append(wrapper)


    def _set_card_severity(self, card, severity):
        card.setProperty("severity", severity or "")
        card.style().unpolish(card)
        card.style().polish(card)

    def _open_stale_item(self, index):
        name_item = self.stale_table.item(index.row(), 0)
        if name_item is None:
            return
        project_id, item_id = name_item.data(Qt.UserRole)
        self.item_opened.emit(project_id, item_id)

