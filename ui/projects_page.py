"""
ui/projects_page.py
Standalone "Projects" screen. Selecting/opening a project navigates the
main window into the Tracker (items) screen for that project.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QMessageBox, QDialog,
    QListWidget, QListWidgetItem, QStyle, QFileDialog, QProgressBar, QComboBox
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QShortcut, QKeySequence

from ui.dialogs import ProjectDialog, ManageGroupsDialog
from ui.table_utils import configure_interactive_table, ExportWorker, EmptyStateTable
from ui.activity_widget import ActivityDialog
from ui.import_excel_dialog import ImportExcelDialog
from export.excel_export import export_multiple_projects_to_excel
from i18n import tr

PROJECT_COLUMNS = ["Name", "Group", "Project Number", "Location", "Contractor", "Currency"]


class TrashDialog(QDialog):
    """Lists soft-deleted projects with Restore / Delete Forever actions."""

    def __init__(self, parent, db, on_change=None):
        super().__init__(parent)
        self.db = db
        self.on_change = on_change
        self.setWindowTitle(tr("trash"))
        self.setMinimumSize(460, 360)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr("trash")))
        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget)

        btn_row = QHBoxLayout()
        restore_btn = QPushButton(tr("undo"))
        restore_btn.clicked.connect(self._restore_selected)
        purge_btn = QPushButton("Delete Forever")
        purge_btn.setObjectName("dangerButton")
        purge_btn.clicked.connect(self._purge_selected)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(restore_btn)
        btn_row.addWidget(purge_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self._reload()

    def _reload(self):
        self.list_widget.clear()
        for p in self.db.get_projects(include_deleted=True):
            item = QListWidgetItem(f"{p['name']}  (deleted {p['deleted_at']})")
            item.setData(Qt.UserRole, p["id"])
            self.list_widget.addItem(item)

    def _selected_id(self):
        current = self.list_widget.currentItem()
        if not current:
            QMessageBox.information(self, "No selection", "Select a project first.")
            return None
        return current.data(Qt.UserRole)

    def _restore_selected(self):
        pid = self._selected_id()
        if pid is None:
            return
        self.db.restore_project(pid)
        self._reload()
        if self.on_change:
            self.on_change()

    def _purge_selected(self):
        pid = self._selected_id()
        if pid is None:
            return
        confirm = QMessageBox.question(self, "Delete forever", "This cannot be undone. Continue?")
        if confirm == QMessageBox.Yes:
            self.db.purge_project(pid)
            self._reload()
            if self.on_change:
                self.on_change()


class ProjectsPage(QWidget):
    project_opened = Signal(int)

    def __init__(self, db, undo_bar, parent=None):
        super().__init__(parent)
        self.db = db
        self.undo_bar = undo_bar

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)

        header_row = QHBoxLayout()
        title = QLabel(tr("projects"))
        title.setObjectName("pageTitle")
        header_row.addWidget(title)
        header_row.addStretch()
        manage_groups_btn = QPushButton("\U0001F4C1 Manage Groups\u2026")
        manage_groups_btn.clicked.connect(self._open_manage_groups)
        header_row.addWidget(manage_groups_btn)
        trash_btn = QPushButton("\U0001F5D1 " + tr("trash"))
        trash_btn.clicked.connect(self._open_trash)
        header_row.addWidget(trash_btn)
        layout.addLayout(header_row)

        filter_row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(tr("search_projects"))
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._apply_filter)
        filter_row.addWidget(self.search_edit, 1)
        filter_row.addWidget(QLabel("Group:"))
        self.group_filter = QComboBox()
        self.group_filter.currentIndexChanged.connect(self._apply_filter)
        filter_row.addWidget(self.group_filter)
        layout.addLayout(filter_row)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("+ " + tr("add"))
        add_btn.setObjectName("primaryButton")
        add_btn.clicked.connect(self._add_project)
        import_btn = QPushButton("\U0001F4E5 Import from Excel")
        import_btn.clicked.connect(self._open_import_excel)
        self.export_btn = QPushButton("\U0001F4E4 Export Filtered to Excel")
        self.export_btn.setToolTip(
            "Exports every project currently shown below (after your search) into ONE Excel "
            "file, each project on its own tab."
        )
        self.export_btn.clicked.connect(self._export_filtered_to_excel)
        edit_btn = QPushButton(tr("edit"))
        edit_btn.clicked.connect(self._edit_project)
        delete_btn = QPushButton(tr("delete"))
        delete_btn.setObjectName("dangerButton")
        delete_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon))
        delete_btn.clicked.connect(self._delete_project)
        history_btn = QPushButton("\U0001F553 " + tr("history"))
        history_btn.clicked.connect(self._open_history)
        open_btn = QPushButton(tr("open_project") + " \u2192")
        open_btn.setObjectName("primaryButton")
        open_btn.clicked.connect(self._open_selected_project)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(import_btn)
        btn_row.addWidget(self.export_btn)
        btn_row.addWidget(edit_btn)
        btn_row.addWidget(delete_btn)
        btn_row.addWidget(history_btn)
        btn_row.addStretch()
        btn_row.addWidget(open_btn)
        layout.addLayout(btn_row)

        self.table = EmptyStateTable("No projects yet \u2014 click \u201c+ Add\u201d to create one.")
        self.table.setColumnCount(len(PROJECT_COLUMNS))
        self.table.setHorizontalHeaderLabels(PROJECT_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        configure_interactive_table(self.table, first_col_width=280, layout_key="projects_table")
        self.table.doubleClicked.connect(lambda _i: self._open_selected_project())
        for key in (Qt.Key_Return, Qt.Key_Enter):
            enter_sc = QShortcut(QKeySequence(key), self.table)
            enter_sc.setContext(Qt.WidgetShortcut)
            enter_sc.activated.connect(self._open_selected_project)
        layout.addWidget(self.table)

        self.reload()

    # ------------------------------------------------------------ #
    def reload(self):
        self.table.setSortingEnabled(False)
        projects = list(self.db.get_projects())
        self._all_projects = projects
        self.table.setRowCount(len(projects))
        for row, p in enumerate(projects):
            values = [p["name"], p["group_name"] or "", p["project_number"] or "", p["location"] or "",
                      p["contractor"] or "", p["currency"] or ""]
            for col, val in enumerate(values):
                cell = QTableWidgetItem(val)
                if col == 0:
                    cell.setData(Qt.UserRole, p["id"])
                    cell.setData(Qt.UserRole + 1, p["group_id"])
                self.table.setItem(row, col, cell)
        self.table.setSortingEnabled(True)
        self.table.resizeRowsToContents()

        current_group = self.group_filter.currentData() if self.group_filter.count() else None
        self.group_filter.blockSignals(True)
        self.group_filter.clear()
        self.group_filter.addItem("All Groups", None)
        for g in self.db.get_project_groups():
            self.group_filter.addItem(g["name"], g["id"])
        idx = self.group_filter.findData(current_group)
        self.group_filter.setCurrentIndex(max(idx, 0))
        self.group_filter.blockSignals(False)

        self._apply_filter()

    def _apply_filter(self):
        text = self.search_edit.text().strip().lower()
        group_id = self.group_filter.currentData()
        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, 0)
            group_item = self.table.item(row, 1)
            number_item = self.table.item(row, 2)
            if not text:
                show = True
            else:
                show = (text in (name_item.text().lower() if name_item else "")
                        or text in (group_item.text().lower() if group_item else "")
                        or text in (number_item.text().lower() if number_item else ""))
            if show and group_id is not None:
                show = name_item and name_item.data(Qt.UserRole + 1) == group_id
            self.table.setRowHidden(row, not show)

    def _selected_project_id(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, tr("no_project_selected"), tr("select_project_first"))
            return None
        return self.table.item(row, 0).data(Qt.UserRole)

    def _add_project(self):
        dlg = ProjectDialog(self, db=self.db)
        if dlg.exec():
            data = dlg.get_data()
            new_id = self.db.add_project(**data)
            self.search_edit.clear()  # a stale search filter could hide the new project we're about to select
            self.reload()
            self._select_row_by_id(new_id)

    def _edit_project(self):
        pid = self._selected_project_id()
        if pid is None:
            return
        project = self.db.get_project(pid)
        dlg = ProjectDialog(self, project=project, db=self.db)
        if dlg.exec():
            self.db.update_project(pid, **dlg.get_data())
            self.reload()
            self._select_row_by_id(pid)

    def _delete_project(self):
        pid = self._selected_project_id()
        if pid is None:
            return
        project = self.db.get_project(pid)
        self.db.delete_project(pid)
        self.reload()

        def _undo():
            self.db.restore_project(pid)
            self.reload()

        self.undo_bar.show_message(f"Project '{project['name']}' deleted.", _undo)

    def _open_trash(self):
        dlg = TrashDialog(self, self.db, on_change=self.reload)
        dlg.exec()

    def _open_manage_groups(self):
        dlg = ManageGroupsDialog(self, self.db)
        dlg.exec()
        self.reload()  # a rename/delete may have changed what's shown

    def _open_history(self):
        pid = self._selected_project_id()
        if pid is None:
            return
        project = self.db.get_project(pid)
        dlg = ActivityDialog(self, self.db, f"{tr('history')} \u2014 {project['name']}",
                              entity_type="project", entity_id=pid)
        dlg.exec()

    def _open_import_excel(self):
        dlg = ImportExcelDialog(self, self.db)
        if dlg.exec():
            self.reload()
            project_id = dlg.imported_project_id()
            if project_id is not None:
                self.project_opened.emit(project_id)

    def _visible_project_ids(self):
        """Ids of every project row currently shown (i.e. not hidden by
        the search filter), in their current on-screen top-to-bottom
        order."""
        ids = []
        for row in range(self.table.rowCount()):
            if self.table.isRowHidden(row):
                continue
            name_item = self.table.item(row, 0)
            if name_item:
                ids.append(name_item.data(Qt.UserRole))
        return ids

    def _export_filtered_to_excel(self):
        project_ids = self._visible_project_ids()
        if not project_ids:
            QMessageBox.information(self, "Nothing to export",
                                     "No projects match the current search.")
            return

        default_name = "Projects Export.xlsx" if len(project_ids) > 1 else "Project Export.xlsx"
        path, _ = QFileDialog.getSaveFileName(self, "Export Filtered Projects to Excel",
                                               default_name, "Excel Files (*.xlsx)")
        if not path:
            return

        original_text = self.export_btn.text()
        self.export_btn.setEnabled(False)
        self.export_btn.setText("\u23F3 Exporting\u2026")

        def _do_export():
            export_multiple_projects_to_excel(self.db, project_ids, path)

        worker = ExportWorker(_do_export)

        def _on_ok():
            self.export_btn.setEnabled(True)
            self.export_btn.setText(original_text)
            QMessageBox.information(
                self, "Done",
                f"Exported {len(project_ids)} project(s) to Excel, one tab each:\n{path}"
            )
            self._export_worker = None

        def _on_err(err):
            self.export_btn.setEnabled(True)
            self.export_btn.setText(original_text)
            QMessageBox.critical(self, "Export failed", err)
            self._export_worker = None

        worker.finished_ok.connect(_on_ok)
        worker.finished_err.connect(_on_err)
        self._export_worker = worker  # keep a reference so it isn't garbage-collected mid-run
        worker.start()

    def _select_row_by_id(self, project_id):
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).data(Qt.UserRole) == project_id:
                self.table.selectRow(row)
                self.table.scrollToItem(self.table.item(row, 0))
                self.table.setFocus()
                break

    def _open_selected_project(self):
        pid = self._selected_project_id()
        if pid is None:
            return
        self.project_opened.emit(pid)
