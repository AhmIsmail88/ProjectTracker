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
    QFileDialog, QMessageBox, QTreeWidget, QTreeWidgetItem, QSplitter
)
from PySide6.QtCore import Qt, Signal, QByteArray
from PySide6.QtGui import QPainter

from ui.table_utils import configure_interactive_table, ExportWorker, EmptyStateTable
from ui.pie_chart import PieChartWidget
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

        # ---- Status breakdown (pie + legend) + value by currency, side by side ----
        mid_row = QHBoxLayout()
        mid_row.setSpacing(16)

        status_box = QVBoxLayout()
        status_box.addWidget(QLabel("<b>Items by Status</b>"))
        pie_row = QHBoxLayout()
        self.pie_chart = PieChartWidget()
        pie_row.addWidget(self.pie_chart)
        self.legend_layout = QVBoxLayout()
        self.legend_layout.setSpacing(4)
        self.legend_layout.addStretch()
        pie_row.addLayout(self.legend_layout, 1)
        status_box.addLayout(pie_row)
        mid_row.addLayout(status_box, 1)

        value_box = QVBoxLayout()
        value_box.addWidget(QLabel("<b>Estimated Value by Currency</b>"))
        self.value_table = QTableWidget()
        self.value_table.setColumnCount(2)
        self.value_table.setHorizontalHeaderLabels(["Currency", "Total Value"])
        self.value_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.value_table.verticalHeader().setVisible(False)
        self.value_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        value_box.addWidget(self.value_table)
        value_box.addStretch()
        mid_row.addLayout(value_box, 1)

        layout.addLayout(mid_row)

        # ---- Stale items ----
        layout.addWidget(QLabel(
            "<b>Possibly Forgotten</b> \u2014 still \u201cNot requested\u201d with no activity "
            "for 14+ days. Double-click to open."
        ))
        self.stale_table = EmptyStateTable("\U0001F389 Nothing forgotten \u2014 every item has had recent activity.")
        self.stale_table.setColumnCount(4)
        self.stale_table.setHorizontalHeaderLabels(["Item Name", "Project", "Area", "Days Untouched"])
        self.stale_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.stale_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.stale_table.verticalHeader().setVisible(False)
        configure_interactive_table(self.stale_table, first_col_width=280)
        self.stale_table.doubleClicked.connect(self._open_stale_item)
        layout.addWidget(self.stale_table, 1)

        self._stale_items = []
        self._legend_widgets = []

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

        self._update_status_pie(summary["status_counts"])

        value_by_currency = summary["value_by_currency"]
        self.value_table.setRowCount(len(value_by_currency))
        for row, (currency, value) in enumerate(sorted(value_by_currency.items())):
            label = currency if currency and currency != "?" else "(No currency set)"
            self.value_table.setItem(row, 0, QTableWidgetItem(label))
            value_item = QTableWidgetItem(f"{value:,.2f}")
            value_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.value_table.setItem(row, 1, value_item)
        _fit_table_height(self.value_table, len(value_by_currency))

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

    def _update_status_pie(self, status_counts):
        ordered = sorted(status_counts.items(), key=lambda x: -x[1])
        total = sum(c for _s, c in ordered) or 1

        slices = []
        for i, (status, count) in enumerate(ordered):
            color = _STATUS_PIE_COLORS.get(status) or _FALLBACK_COLORS[i % len(_FALLBACK_COLORS)]
            slices.append((status, count, color))
        self.pie_chart.set_data(slices)

        for w in self._legend_widgets:
            w.setParent(None)
        self._legend_widgets = []
        for status, count, color in slices:
            row = QHBoxLayout()
            row.addWidget(_color_swatch(color))
            label = QLabel(f"{status} \u2014 {count} ({count * 100 // total}%)")
            row.addWidget(label, 1)
            wrapper = QWidget()
            wrapper.setLayout(row)
            self.legend_layout.insertWidget(self.legend_layout.count() - 1, wrapper)
            self._legend_widgets.append(wrapper)

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

