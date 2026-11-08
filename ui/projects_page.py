"""Tree navigation and a scoped project overview."""
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QAbstractItemView, QMessageBox, QDialog, QListWidget, QListWidgetItem,
    QFileDialog, QTreeWidget, QTreeWidgetItem, QSplitter, QMenu, QScrollArea)
from PySide6.QtCore import Qt, Signal, QEvent
from PySide6.QtGui import QShortcut, QKeySequence, QFontMetrics
from ui.dialogs import ProjectDialog, ManageGroupsDialog
from ui.table_utils import ExportWorker
from ui.activity_widget import ActivityDialog
from ui.import_excel_dialog import ImportExcelDialog
from ui.project_overview import ProjectOverview
from ui.review_items_dialog import ReviewItemsDialog
from ui.users_dialog import UsersDialog
import auth
from export.excel_export import export_multiple_projects_to_excel
from i18n import tr, tr_text
from ui.icons import make_icon
from constants import get_theme
from ui.styles import DARK_TOKENS, LIGHT_TOKENS


class TrashDialog(QDialog):
    """Lists soft-deleted projects with Restore / Delete Forever actions."""

    def __init__(self, parent, db, on_change=None):
        super().__init__(parent)
        self.db = db
        self.on_change = on_change
        self.setWindowTitle(tr("trash"))
        self.setMinimumSize(640, 400)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr("trash")))
        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget)

        btn_row = QHBoxLayout()
        restore_btn = QPushButton(tr("undo"))
        restore_btn.clicked.connect(self._restore_selected)
        purge_btn = QPushButton(tr_text("Delete Forever"))
        purge_btn.setObjectName("dangerButton")
        purge_btn.clicked.connect(self._purge_selected)
        close_btn = QPushButton(tr_text("Close"))
        close_btn.clicked.connect(self.accept)
        self.empty_btn = QPushButton(tr_text("Empty old trash…"))
        self.empty_btn.setObjectName("dangerButton")
        self.empty_btn.clicked.connect(self._empty_old_trash)
        if not auth.is_manager(self.db):
            self.empty_btn.setEnabled(False)
            self.empty_btn.setToolTip(tr_text("Managers only"))
        btn_row.addWidget(restore_btn)
        btn_row.addWidget(purge_btn)
        btn_row.addWidget(self.empty_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self._reload()

    def _reload(self):
        self.list_widget.clear()
        for p in self.db.get_projects(include_deleted=True):
            item = QListWidgetItem(f"{tr_text('deleted')} ⁦{p['deleted_at']}⁩  —  {p['name']}")
            item.setToolTip(p["name"])
            item.setData(Qt.UserRole, p["id"])
            self.list_widget.addItem(item)

    def _selected_id(self):
        current = self.list_widget.currentItem()
        if not current:
            QMessageBox.information(self, "No selection", "Select a project first.")
            return None
        return current.data(Qt.UserRole)

    def _restore_selected(self):
        if not auth.is_manager(self.db):
            return
        pid = self._selected_id()
        if pid is None:
            return
        self.db.restore_project(pid)
        self._reload()
        if self.on_change:
            self.on_change()

    def _purge_selected(self):
        if not auth.is_manager(self.db):
            return
        pid = self._selected_id()
        if pid is None:
            return
        confirm = QMessageBox.question(self, "Delete forever", "This cannot be undone. Continue?")
        if confirm == QMessageBox.Yes and auth.is_manager(self.db):
            self.db.purge_project(pid)
            self._reload()
            if self.on_change:
                self.on_change()


    EMPTY_TRASH_AFTER_DAYS = 30

    def _empty_old_trash(self):
        """Permanently removes trash older than 30 days - deleted projects
        with their items, and items deleted one by one - after taking a
        dedicated backup that the automatic rotation never deletes."""
        if not auth.is_manager(self.db):
            return
        days = self.EMPTY_TRASH_AFTER_DAYS
        summary = self.db.trash_summary(days)
        if not summary["projects"] and not summary["loose_items"]:
            QMessageBox.information(self, tr("trash"), tr_text(
                "Nothing in the trash is older than {days} days.").format(days=days))
            return
        confirm = QMessageBox.question(
            self, tr("trash"),
            tr_text(
                "Permanently delete {projects} project(s) with {project_items} item(s), and "
                "{items} item(s) deleted individually, all deleted more than {days} days ago?\n\n"
                "A backup of the database is taken first and kept until you remove it."
            ).format(projects=summary["projects"], project_items=summary["items_in_projects"],
                     items=summary["loose_items"], days=days),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if confirm != QMessageBox.Yes or not auth.is_manager(self.db):
            return

        import os
        from datetime import datetime
        import backup
        data_dir = os.path.dirname(os.path.abspath(self.db.db_path))
        backups_dir = backup.backups_dir_for(data_dir)
        safety_copy = os.path.join(
            backups_dir, f"before_empty_trash_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.db")
        try:
            os.makedirs(backups_dir, exist_ok=True)
            backup.snapshot_database(self.db.db_path, safety_copy)
            backup.mirror_attachments(self.db.attachments_dir, data_dir)
        except Exception as exc:  # noqa: BLE001 - never purge without a backup
            QMessageBox.critical(self, tr("trash"),
                                 tr_text("The backup failed, so nothing was deleted.") + f"\n\n{exc}")
            return

        self.db.empty_trash_items_and_projects(days)
        self._reload()
        if self.on_change:
            self.on_change()
        QMessageBox.information(self, tr("trash"),
                                tr_text("Trash emptied. Backup taken before deleting:") + f"\n{safety_copy}")


class ProjectsPage(QWidget):
    project_opened = Signal(int)
    items_requested = Signal(int, str)
    item_opened = Signal(int, int)

    def __init__(self, db, undo_bar, parent=None):
        super().__init__(parent)
        self.db, self.undo_bar = db, undo_bar
        self._tree_projects, self._tree_groups = {}, {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        header = QHBoxLayout()
        title = QLabel(tr("projects"))
        title.setObjectName("pageTitle")
        header.addWidget(title)
        header.addStretch()
        self.add_btn = QPushButton("+ " + tr("add"))
        self.add_btn.setObjectName("primaryButton")
        self.add_btn.clicked.connect(self._add_project)
        header.addWidget(self.add_btn)
        self.more_btn = QPushButton(tr_text("More Actions"))
        menu = QMenu(self.more_btn)
        self.project_actions = [menu.addAction(tr("edit"), self._edit_project),
                                menu.addAction(tr("history"), self._open_history),
                                menu.addAction(tr("delete"), self._delete_project)]
        menu.addSeparator()
        self.groups_action = menu.addAction(tr_text("Manage Groups…"), self._open_manage_groups)
        users_action = menu.addAction(tr_text("Users\u2026"), self._open_users)
        users_action.setVisible(auth.is_manager(self.db))
        self.import_action = menu.addAction(tr_text("Import from Excel"), self._open_import_excel)
        self.export_btn = menu.addAction(tr_text("Export this scope to Excel"), self._export_filtered_to_excel)
        menu.addSeparator()
        self.trash_action = menu.addAction(tr("trash"), self._open_trash)
        if not auth.is_manager(self.db):
            self.add_btn.setEnabled(False)
            self.add_btn.setToolTip(tr_text("Only the manager can do this."))
            for action in (self.project_actions[0], self.project_actions[2],
                           self.groups_action, self.import_action, self.trash_action):
                action.setEnabled(False)
        self.more_btn.setMenu(menu)
        header.addWidget(self.more_btn)
        layout.addLayout(header)

        tree_panel = QWidget()
        self._tree_panel = tree_panel
        tree_layout = QVBoxLayout(tree_panel)
        tree_layout.setContentsMargins(0, 0, 0, 0)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(tr("search_projects"))
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._apply_filter)
        tree_layout.addWidget(self.search_edit)
        self.project_tree = QTreeWidget()
        self.project_tree.setObjectName("projectBrowser")
        self.project_tree.setHeaderHidden(True)
        self.project_tree.setColumnCount(2)
        self.project_tree.setColumnWidth(0, 285)
        self.project_tree.setColumnWidth(1, 45)
        # The name column is re-fitted to the panel width (see
        # _fit_name_column) so long project/group names stay fully visible
        # instead of being cut off with an ellipsis.
        self.project_tree.viewport().installEventFilter(self)
        self._fitting_tree_width = False
        self._tree_width_fitted = False
        self._fit_name_column()
        self.project_tree.setMinimumWidth(260)
        self.project_tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.project_tree.currentItemChanged.connect(self._on_tree_selected)
        self.project_tree.itemExpanded.connect(lambda *_: self._fit_name_column())
        self.project_tree.itemDoubleClicked.connect(self._open_tree_project)
        for key in (Qt.Key_Return, Qt.Key_Enter):
            shortcut = QShortcut(QKeySequence(key), self.project_tree)
            shortcut.setContext(Qt.WidgetShortcut)
            shortcut.activated.connect(self._open_selected_project)
        tree_layout.addWidget(self.project_tree, 1)
        self.overview = ProjectOverview()
        self.overview.open_requested.connect(self._open_selected_project)
        self.overview.metric_requested.connect(self._open_metric)
        scroll = QScrollArea()
        scroll.setObjectName("projectOverviewScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidget(self.overview)
        self.splitter = QSplitter(Qt.Horizontal)
        # Keep the browser on the left and the overview on the right in both languages.
        self.splitter.setLayoutDirection(Qt.LeftToRight)
        tree_panel.setLayoutDirection(self.layoutDirection())
        self.overview.setLayoutDirection(self.layoutDirection())
        self.splitter.addWidget(tree_panel)
        self.splitter.addWidget(scroll)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([460, 880])
        layout.addWidget(self.splitter, 1)
        self.reload()

    def _tree_content_width(self):
        """Width Qt needs to show every visible project/group name in full."""
        tree = self.project_tree
        hint = tree.sizeHintForColumn(0)
        if hint > 0:
            return hint
        cache = {}
        needed = 0
        for i in range(tree.topLevelItemCount()):
            top = tree.topLevelItem(i)
            nodes = [top] + [top.child(j) for j in range(top.childCount())]
            for node in nodes:
                font = node.font(0)
                fm = cache.get(font.key())
                if fm is None:
                    fm = cache[font.key()] = QFontMetrics(font)
                depth = 0
                parent = node.parent()
                while parent is not None:
                    depth += 1
                    parent = parent.parent()
                needed = max(needed, depth * tree.indentation() + 26
                             + fm.horizontalAdvance(node.text(0)))
        return needed

    def _fit_name_column(self):
        """Start from the smallest browser width that fits and widen it,
        step by step, until the longest project/group name is fully
        visible - names should never end in an ellipsis."""
        if getattr(self, "_fitting_tree_width", False):
            return
        self._fitting_tree_width = True
        try:
            self._fit_name_column_now()
        except RuntimeError:
            # The page can be torn down while a resize/fit is still queued.
            pass
        finally:
            self._fitting_tree_width = False

    def _fit_name_column_now(self):
        tree = self.project_tree
        viewport = tree.viewport().width()
        if viewport <= 0:
            return
        count_col = 45
        if tree.columnWidth(1) != count_col:
            tree.setColumnWidth(1, count_col)
        tree.setColumnWidth(0, max(140, viewport - count_col - 2))
        needed = self._tree_content_width()
        if not needed:
            return
        sizes = self.splitter.sizes()
        if len(sizes) != 2:
            return
        total = sum(sizes)
        if total <= 0:
            return
        needed_panel = needed + count_col + 40
        limit = max(280, total - 480)   # keep the overview usable
        min_width = min(needed_panel, limit)
        if getattr(self, "_tree_panel", None) is not None:
            self._tree_panel.setMinimumWidth(min_width)
        if not self._tree_width_fitted:
            self._tree_width_fitted = True
            if abs(sizes[0] - min_width) > 2:
                self.splitter.setSizes([min_width, total - min_width])
        elif sizes[0] < min_width - 2:
            self.splitter.setSizes([min_width, total - min_width])

    def eventFilter(self, obj, event):
        # Keep the browser fitted to its content; ignore late events that
        # can arrive while the page is being torn down.
        if event.type() == QEvent.Resize:
            try:
                is_viewport = obj is self.project_tree.viewport()
            except RuntimeError:
                return False
            if is_viewport:
                self._fit_name_column()
        return super().eventFilter(obj, event)

    def selected_scope(self):
        node = self.project_tree.currentItem()
        return node.data(0, Qt.UserRole) if node and not node.isHidden() else ("all", None)

    def restore_scope(self, scope):
        kind, ident = scope
        node = (self._tree_projects.get(ident) if kind == "project" else
                self._tree_groups.get(ident) if kind in ("group", "ungrouped") else self.all_node)
        self.project_tree.setCurrentItem(node or self.all_node)
        self._refresh_overview()

    def reload(self):
        scope = self.selected_scope()
        expanded = {self.project_tree.topLevelItem(i).data(0, Qt.UserRole)
                    for i in range(self.project_tree.topLevelItemCount())
                    if self.project_tree.topLevelItem(i).isExpanded()}
        first_load = self.project_tree.topLevelItemCount() == 0
        self._all_projects = list(self.db.get_projects())
        self.project_tree.blockSignals(True)
        self.project_tree.clear()
        self._tree_projects, self._tree_groups = {}, {}
        self.all_node = QTreeWidgetItem([tr_text("All Projects"), str(len(self._all_projects))])
        self.all_node.setData(0, Qt.UserRole, ("all", None))
        self.project_tree.addTopLevelItem(self.all_node)
        groups = [(g["id"], g["name"]) for g in self.db.get_project_groups()] + [(None, tr_text("Ungrouped"))]
        for group_id, name in groups:
            members = [p for p in self._all_projects if p["group_id"] == group_id]
            if group_id is None and not members:
                continue
            node = QTreeWidgetItem([name, str(len(members))])
            node.setToolTip(0, name)
            node.setData(0, Qt.UserRole, ("group", group_id) if group_id is not None else ("ungrouped", None))
            font = node.font(0)
            font.setBold(True)
            node.setFont(0, font)
            self.project_tree.addTopLevelItem(node)
            self._tree_groups[group_id] = node
            for project in members:
                child = QTreeWidgetItem([project["name"]])
                child.setData(0, Qt.UserRole, ("project", project["id"]))
                child.setToolTip(0, project["name"])
                node.addChild(child)
                self._tree_projects[project["id"]] = child
            node.setExpanded(first_load or node.data(0, Qt.UserRole) in expanded)
        kind, ident = scope
        node = self._tree_projects.get(ident) if kind == "project" else self._tree_groups.get(ident) if kind in ("group", "ungrouped") else self.all_node
        self.project_tree.setCurrentItem(node or self.all_node)
        self.project_tree.blockSignals(False)
        self._apply_filter()
        self.on_theme_changed()
        self._fit_name_column()

    def _apply_filter(self):
        text = self.search_edit.text().strip().lower()
        for project in getattr(self, "_all_projects", []):
            node = self._tree_projects[project["id"]]
            show = not text or any(text in str(project[key] or "").lower() for key in ("name", "group_name", "project_number"))
            node.setHidden(not show)
        for node in self._tree_groups.values():
            node.setHidden(bool(text) and not any(not node.child(i).isHidden() for i in range(node.childCount())))
            if text and not node.isHidden():
                node.setExpanded(True)
        current = self.project_tree.currentItem()
        if current and current.isHidden():
            self.project_tree.setCurrentItem(self.all_node)
        if hasattr(self, "overview"):
            self._refresh_overview()
        self._fit_name_column()

    def _on_tree_selected(self, item, _previous):
        self._refresh_overview()

    def _open_tree_project(self, item, _column):
        if item and not item.isHidden() and item.data(0, Qt.UserRole)[0] == "project":
            self.project_opened.emit(item.data(0, Qt.UserRole)[1])

    def _visible_project_ids(self):
        kind, ident = self.selected_scope()
        return [p["id"] for p in self._all_projects
                if not self._tree_projects[p["id"]].isHidden()
                and (kind == "all" or kind == "project" and p["id"] == ident
                     or kind == "group" and p["group_id"] == ident
                     or kind == "ungrouped" and p["group_id"] is None)]

    def _refresh_overview(self):
        kind, ident = self.selected_scope()
        project = self.db.get_project(ident) if kind == "project" else None
        group = self.db.get_project_group(ident) if kind == "group" else None
        ids = self._visible_project_ids()
        summary = self.db.get_dashboard_summary(project_ids=ids)
        title = project["name"] if project else group["name"] if group else tr_text("Ungrouped" if kind == "ungrouped" else "All Projects")
        context = (project["group_name"] or tr_text("Ungrouped")) if project else tr_text("{count} projects").format(count=len(ids))
        self.overview.show_summary(title, context, summary, project=project, group=group)
        is_manager = auth.is_manager(self.db)
        for action in self.project_actions:
            action.setEnabled(project is not None
                              and (is_manager or action is self.project_actions[1]))

    def on_theme_changed(self):
        tokens = DARK_TOKENS if get_theme() == "dark" else LIGHT_TOKENS
        for node in self._tree_groups.values():
            node.setIcon(0, make_icon("folder", tokens["accent"]))
        for node in self._tree_projects.values():
            node.setIcon(0, make_icon("list", tokens["muted"]))

    def _open_metric(self, key):
        status = {"items": "", "delivered": "Delivered", "pending": "Not requested",
                  "blocked": "On Hold"}[key]
        project_id = self.selected_project_id()
        if project_id is not None:
            self.items_requested.emit(project_id, status)
            return
        dialog = ReviewItemsDialog(self.db, self._visible_project_ids(), parent=self, status=status or None)
        dialog.item_opened.connect(self.item_opened)
        dialog.exec()

    def selected_project_id(self):
        kind, ident = self.selected_scope()
        return ident if kind == "project" else None

    def _selected_project_id(self):
        project_id = self.selected_project_id()
        if project_id is None:
            QMessageBox.information(self, tr("no_project_selected"), tr("select_project_first"))
        return project_id

    def select_project(self, project_id):
        node = self._tree_projects.get(project_id)
        if node is None:
            return False
        if node.isHidden():
            self.search_edit.clear()
        node.parent().setExpanded(True)
        self.project_tree.setCurrentItem(node)
        self.project_tree.scrollToItem(node)
        self._refresh_overview()
        return True

    def _open_selected_project(self):
        project_id = self._selected_project_id()
        if project_id is not None:
            self.project_opened.emit(project_id)

    def _add_project(self):
        if not auth.is_manager(self.db):
            return
        dlg = ProjectDialog(self, db=self.db)
        kind, ident = self.selected_scope()
        project = self.db.get_project(ident) if kind == "project" else None
        group_id = project["group_id"] if project else ident if kind == "group" else None
        if isinstance(group_id, int):
            dlg.group_combo.setCurrentIndex(max(0, dlg.group_combo.findData(group_id)))
        if dlg.exec() and auth.is_manager(self.db):
            data = dlg.get_data()
            new_id = self.db.add_project(**data)
            if auth.is_manager(self.db):
                self.db.set_project_assignee(new_id, dlg.selected_assignee_id())
            self.search_edit.clear()  # a stale search filter could hide the new project we're about to select
            self.reload()
            self.select_project(new_id)

    def _edit_project(self):
        if not auth.is_manager(self.db):
            return
        pid = self._selected_project_id()
        if pid is None:
            return
        project = self.db.get_project(pid)
        dlg = ProjectDialog(self, project=project, db=self.db)
        if dlg.exec() and auth.is_manager(self.db):
            self.db.update_project(pid, **dlg.get_data())
            if auth.is_manager(self.db):
                self.db.set_project_assignee(pid, dlg.selected_assignee_id())
            self.reload()
            self.select_project(pid)

    def _open_users(self):
        if not auth.is_manager(self.db):
            QMessageBox.information(self, tr_text("Users"), tr_text("Only the manager can manage user accounts."))
            return
        UsersDialog(self, self.db).exec()

    def _delete_project(self):
        if not auth.is_manager(self.db):
            return
        pid = self._selected_project_id()
        if pid is None:
            return
        project = self.db.get_project(pid)
        self.db.delete_project(pid)
        self.reload()

        def _undo():
            if not auth.is_manager(self.db):
                return
            self.db.restore_project(pid)
            self.reload()

        self.undo_bar.show_message(f"Project '{project['name']}' deleted.", _undo)

    def _open_trash(self):
        if not auth.is_manager(self.db):
            return
        dlg = TrashDialog(self, self.db, on_change=self.reload)
        dlg.exec()

    def _open_manage_groups(self):
        if not auth.is_manager(self.db):
            return
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
        if not auth.is_manager(self.db):
            return
        dlg = ImportExcelDialog(self, self.db)
        if dlg.exec():
            self.reload()
            project_id = dlg.imported_project_id()
            if project_id is not None:
                self.project_opened.emit(project_id)

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
