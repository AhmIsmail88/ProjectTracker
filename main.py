"""
Project Tracker - main application entry point.

Run with:
    python main.py

Requires: PySide6, openpyxl, reportlab, matplotlib, python-dotenv, requests
(see requirements.txt)
"""

import logging
import os
import shutil
import sqlite3
import sys
import tempfile
import zipfile
from datetime import datetime

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QMessageBox, QFileDialog, QStackedWidget
)
from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QShortcut, QKeySequence

import config
from app_paths import get_app_dir
from constants import APP_VERSION
from database import Database
import backup
from ui.styles import DARK_THEME, LIGHT_THEME
from ui.widgets import UndoBar
from ui.table_utils import ExportWorker
from ui.projects_page import ProjectsPage
from ui.items_page import TrackerPage
from ui.suppliers_page import SuppliersPage
from ui.ai_page import AIPage
from ui.dashboard_page import DashboardPage
from ui.global_search_dialog import GlobalSearchDialog
import i18n
from i18n import tr

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, db, data_dir):
        super().__init__()
        self.db = db
        self.data_dir = data_dir
        self._settings = QSettings("ProjectTracker", "MainWindow")

        self.current_theme = self._settings.value("theme", "dark")
        i18n.set_language(self._settings.value("language", "ar"))
        QApplication.instance().setLayoutDirection(
            Qt.RightToLeft if i18n.get_language() == "ar" else Qt.LeftToRight
        )

        self.resize(1360, 800)
        self.setMinimumSize(1024, 620)
        self._build_central_widget()
        self._apply_theme(self.current_theme)
        self._restore_window_state()
        self._reopen_last_project()

    def _reopen_last_project(self):
        last_id = config.load_last_project_id()
        if last_id is None:
            return
        project = self.db.get_project(last_id)
        if project is not None:  # None if deleted, or a different/empty data folder now
            self._open_project(last_id)

    # ------------------------------------------------------------------ #
    def _build_central_widget(self):
        self.setWindowTitle(f"{tr('app_title')} v{APP_VERSION}")

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setCentralWidget(central)

        self._build_top_bar(root)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        root.addLayout(body, 1)

        self.undo_bar = UndoBar()

        # ---- Pages ----
        self.stack = QStackedWidget()
        self.projects_page = ProjectsPage(self.db, self.undo_bar)
        self.projects_page.project_opened.connect(self._open_project)
        self.tracker_page = TrackerPage(self.db, self.undo_bar)
        self.tracker_page.back_requested.connect(lambda: self._navigate(0, "projects"))
        self.suppliers_page = SuppliersPage(self.db, self.undo_bar)
        self.ai_page = AIPage(self.db)
        self.dashboard_page = DashboardPage(self.db)
        self.dashboard_page.item_opened.connect(self._open_project_and_item)

        self.stack.addWidget(self.projects_page)   # 0
        self.stack.addWidget(self.tracker_page)     # 1
        self.stack.addWidget(self.suppliers_page)   # 2
        self.stack.addWidget(self.ai_page)           # 3
        self.stack.addWidget(self.dashboard_page)    # 4
        body.addWidget(self.stack, 1)

        root.addWidget(self.undo_bar)
        self._pad_undo_bar()

        self._navigate(0, "projects")
        self._build_menu_bar()
        self._update_status_bar()

    def _build_top_bar(self, root):
        """A single compact horizontal bar replaces the old tall, mostly
        empty sidebar: page navigation on the left, theme/language on the
        right — all in one row instead of a whole side column."""
        bar = QWidget()
        bar.setObjectName("toolbarFrame")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(6)

        # Company logo (user branding) - hidden when none is set.
        self.logo_label = QLabel()
        self.logo_label.setObjectName("logoLabel")
        self._apply_logo()
        layout.addWidget(self.logo_label)

        self.nav_buttons = {}
        for key, page_index, label_key in [
            ("projects", 0, "projects"),
            ("suppliers", 2, "suppliers"),
            ("ai", 3, "ai_assistant"),
            ("dashboard", 4, "dashboard"),
        ]:
            btn = QPushButton(tr(label_key))
            btn.setObjectName("navButton")
            btn.setCheckable(True)
            btn.clicked.connect(lambda _checked, idx=page_index, k=key: self._navigate(idx, k))
            layout.addWidget(btn)
            self.nav_buttons[key] = btn

        search_btn = QPushButton("\U0001F50D Search All Projects")
        search_btn.setToolTip("Find an item by name across every project (Ctrl+Shift+F)")
        search_btn.clicked.connect(self._open_global_search)
        layout.addWidget(search_btn)
        QShortcut(QKeySequence("Ctrl+Shift+F"), self, self._open_global_search)

        layout.addStretch()

        self.theme_btn = QPushButton(tr("light_mode") if self.current_theme == "dark" else tr("dark_mode"))
        self.theme_btn.setToolTip("Switch between Dark and Light mode")
        self.theme_btn.clicked.connect(self._toggle_theme)
        layout.addWidget(self.theme_btn)

        self.lang_btn = QPushButton(tr("language"))
        self.lang_btn.setToolTip("Switch interface language")
        self.lang_btn.clicked.connect(self._toggle_language)
        layout.addWidget(self.lang_btn)

        root.addWidget(bar)

    def _pad_undo_bar(self):
        # Give the floating undo bar a little breathing room from the edges.
        self.undo_bar.setContentsMargins(0, 0, 0, 0)
        self.undo_bar.setStyleSheet(self.undo_bar.styleSheet())

    def _navigate(self, index, key):
        self.stack.setCurrentIndex(index)
        for k, btn in self.nav_buttons.items():
            btn.setChecked(k == key)
        if key == "suppliers":
            self.suppliers_page.reload()
        elif key == "ai":
            self.ai_page.refresh_projects()
        elif key == "projects":
            self.projects_page.reload()
        elif key == "dashboard":
            self.dashboard_page.reload()

    def _open_project(self, project_id):
        self.tracker_page.open_project(project_id)
        self.stack.setCurrentIndex(1)
        for btn in self.nav_buttons.values():
            btn.setChecked(False)
        config.save_last_project_id(project_id)

    def _open_project_and_item(self, project_id, item_id):
        """Same as _open_project, but also selects/scrolls to a specific
        item — used by the Dashboard's stale-items list and by
        Search All Projects."""
        self.tracker_page.open_project(project_id, select_item_id=item_id)
        self.stack.setCurrentIndex(1)
        for btn in self.nav_buttons.values():
            btn.setChecked(False)
        config.save_last_project_id(project_id)

    def _open_global_search(self):
        dlg = GlobalSearchDialog(self, self.db)
        dlg.result_chosen.connect(self._open_project_and_item)
        dlg.exec()

    # ---------------------------------------------------------------
    # Theme / language
    # ---------------------------------------------------------------
    def _toggle_theme(self):
        new_theme = "light" if self.current_theme == "dark" else "dark"
        self._apply_theme(new_theme)

    def _apply_theme(self, theme):
        self.current_theme = theme
        self._settings.setValue("theme", theme)
        if theme == "dark":
            QApplication.instance().setStyleSheet(DARK_THEME)
            self.theme_btn.setText(tr("light_mode"))
        else:
            QApplication.instance().setStyleSheet(LIGHT_THEME)
            self.theme_btn.setText(tr("dark_mode"))

    def _toggle_language(self):
        new_lang = "en" if i18n.get_language() == "ar" else "ar"
        i18n.set_language(new_lang)
        self._settings.setValue("language", new_lang)
        QApplication.instance().setLayoutDirection(Qt.RightToLeft if new_lang == "ar" else Qt.LeftToRight)
        # Simplest reliable way to re-translate every screen: rebuild the UI.
        current_project = self.tracker_page.project
        self._build_central_widget()
        self._apply_theme(self.current_theme)
        if current_project:
            self._open_project(current_project["id"])

    # ---------------------------------------------------------------
    # Window state persistence
    # ---------------------------------------------------------------
    def _restore_window_state(self):
        geometry = self._settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)

    def closeEvent(self, event):
        self._settings.setValue("geometry", self.saveGeometry())
        super().closeEvent(event)

    # ---------------------------------------------------------------
    # Menu bar / status bar / data folder management
    # ---------------------------------------------------------------
    def _build_menu_bar(self):
        menubar = self.menuBar()
        menubar.clear()
        file_menu = menubar.addMenu(tr("menu_file"))

        open_folder_action = file_menu.addAction(tr("menu_open_data_folder"))
        open_folder_action.triggered.connect(self._open_data_folder)

        logo_action = file_menu.addAction(tr("menu_company_logo"))
        logo_action.triggered.connect(self._change_company_logo)

        remove_logo_action = file_menu.addAction(tr("menu_remove_logo"))
        remove_logo_action.triggered.connect(self._remove_company_logo)

        change_folder_action = file_menu.addAction(tr("menu_change_data_folder"))
        change_folder_action.triggered.connect(self._change_data_folder)

        file_menu.addSeparator()
        self.backup_action = file_menu.addAction(tr("menu_backup_now"))
        self.backup_action.triggered.connect(self._backup_now)

        file_menu.addSeparator()
        exit_action = file_menu.addAction(tr("menu_exit"))
        exit_action.triggered.connect(self.close)

        help_menu = menubar.addMenu(tr("menu_help"))
        shortcuts_action = help_menu.addAction(tr("menu_keyboard_shortcuts"))
        shortcuts_action.triggered.connect(self._show_shortcuts)

    def _show_shortcuts(self):
        rows = [
            ("Global", [
                ("Ctrl+Shift+F", "Search All Projects"),
            ]),
            ("Items screen", [
                ("Ctrl+N", "Add Item"),
                ("Ctrl+E", "Edit Item"),
                ("Delete", "Delete selected item(s)"),
                ("Ctrl+D", "Duplicate selected item(s)"),
                ("Enter", "Open Edit for the selected item"),
                ("Double-click / F2", "Edit Unit Cost / Requested Qty / Delivered Qty directly in the table"),
                ("Alt+\u2191 / Alt+\u2193", "Move selected item(s) up/down"),
                ("Ctrl+Alt+\u2191 / Ctrl+Alt+\u2193", "Move selected item(s) to Top/Bottom"),
                ("Ctrl+G", "Move selected item(s) to a specific row number"),
            ]),
            ("Projects screen", [
                ("Enter", "Open the selected project"),
            ]),
            ("Suppliers screen", [
                ("Enter", "Edit the selected supplier"),
            ]),
        ]
        html = ""
        for section, entries in rows:
            html += f"<p><b>{section}</b></p><table cellpadding='4'>"
            for key, desc in entries:
                html += f"<tr><td><code>{key}</code></td><td>{desc}</td></tr>"
            html += "</table>"
        box = QMessageBox(self)
        box.setWindowTitle("Keyboard Shortcuts")
        box.setTextFormat(Qt.RichText)
        box.setText(html)
        box.exec()

    def _update_status_bar(self):
        last_backup = backup.last_backup_datetime(self.data_dir)
        backup_text = last_backup.strftime("%Y-%m-%d %H:%M") if last_backup else tr("never_yet")
        self.statusBar().showMessage(
            f"{tr('data_folder')}: {self.data_dir}    |    {tr('last_auto_backup')}: {backup_text}"
        )

    def _apply_logo(self):
        """Shows the company logo in the top bar (scaled to 28px height),
        or hides the placeholder entirely when no logo is set."""
        from PySide6.QtGui import QPixmap
        path = config.logo_path()
        if path:
            pm = QPixmap(path)
            if not pm.isNull():
                pm = pm.scaledToHeight(56, Qt.SmoothTransformation)
                if pm.width() > 300:
                    pm = pm.scaledToWidth(300, Qt.SmoothTransformation)
                self.logo_label.setPixmap(pm)
                self.logo_label.setVisible(True)
                return
        self.logo_label.setVisible(False)

    def _change_company_logo(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose company logo (PNG / JPG)", "", "Images (*.png *.jpg *.jpeg *.bmp)")
        if not path:
            return
        if config.set_company_logo(path):
            self._apply_logo()
            logger.info("Company logo set from %s", path)
        else:
            QMessageBox.warning(self, "Company Logo", "Could not copy the logo file.")

    def _remove_company_logo(self):
        config.remove_company_logo()
        self._apply_logo()

    def _open_data_folder(self):
        if sys.platform.startswith("win"):
            os.startfile(self.data_dir)  # noqa: only exists on Windows
        elif sys.platform == "darwin":
            import subprocess
            subprocess.run(["open", self.data_dir], check=False)
        else:
            import subprocess
            subprocess.run(["xdg-open", self.data_dir], check=False)

    def _change_data_folder(self):
        new_dir = QFileDialog.getExistingDirectory(
            self, "Choose a new folder for Project Tracker data", self.data_dir
        )
        if not new_dir:
            return

        new_db_path = config.db_path_for(new_dir)
        new_attachments_dir = config.attachments_dir_for(new_dir)
        moving_existing_data = os.path.exists(new_db_path)

        if not moving_existing_data:
            confirm = QMessageBox.question(
                self, "Move data",
                "Copy your current projects, items and attachments into this new folder?\n\n"
                "Choose 'No' only if this folder already has its own Project Tracker data "
                "you want to switch to instead."
            )
            if confirm == QMessageBox.Yes:
                try:
                    shutil.copy2(self.db.db_path, new_db_path)
                    if os.path.isdir(self.db.attachments_dir):
                        shutil.copytree(self.db.attachments_dir, new_attachments_dir, dirs_exist_ok=True)
                except OSError as exc:
                    QMessageBox.critical(self, "Copy failed", str(exc))
                    return

        self.db = Database(new_db_path, new_attachments_dir)
        self.data_dir = new_dir
        config.save_data_dir(new_dir)
        self._update_status_bar()
        self._build_central_widget()
        self._apply_theme(self.current_theme)
        QMessageBox.information(self, "Data folder changed", f"Now using:\n{new_dir}")

    def _backup_now(self):
        default_name = f"project_tracker_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        path, _ = QFileDialog.getSaveFileName(self, "Save backup as", default_name, "Zip Files (*.zip)")
        if not path:
            return

        db_path = self.db.db_path
        attachments_dir = self.db.attachments_dir
        self.backup_action.setEnabled(False)
        original_title = self.windowTitle()
        self.setWindowTitle(original_title + "  \u2014  backing up\u2026")

        def _do_backup():
            # Snapshot the database with SQLite's own backup API first, so
            # the zip always contains a transactionally consistent,
            # fully-restorable database even if the app writes to the live
            # database while the backup is running.
            fd, staged_db = tempfile.mkstemp(prefix="pt_backup_", suffix=".db")
            os.close(fd)
            try:
                src = sqlite3.connect(db_path)
                try:
                    dst = sqlite3.connect(staged_db)
                    try:
                        with dst:
                            src.backup(dst)
                    finally:
                        dst.close()
                finally:
                    src.close()
                with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
                    zf.write(staged_db, arcname="project_tracker.db")
                    for root, _dirs, files in os.walk(attachments_dir):
                        for fname in files:
                            full_path = os.path.join(root, fname)
                            arcname = os.path.join("attachments", os.path.relpath(full_path, attachments_dir))
                            zf.write(full_path, arcname=arcname)
            finally:
                try:
                    os.remove(staged_db)
                except OSError:
                    pass

        def _on_ok():
            self.backup_action.setEnabled(True)
            self.setWindowTitle(original_title)
            QMessageBox.information(self, "Backup complete", f"Backup saved:\n{path}")
            logger.info("Backup saved to %s", path)
            self._backup_worker = None

        def _on_err(err):
            self.backup_action.setEnabled(True)
            self.setWindowTitle(original_title)
            logger.exception("Backup failed")
            QMessageBox.critical(self, "Backup failed", err)
            self._backup_worker = None

        worker = ExportWorker(_do_backup)
        worker.finished_ok.connect(_on_ok)
        worker.finished_err.connect(_on_err)
        self._backup_worker = worker  # keep a reference so it isn't garbage-collected mid-run
        worker.start()


def main():
    app_dir = get_app_dir()
    if not getattr(sys, "frozen", False) and app_dir not in sys.path:
        sys.path.insert(0, app_dir)

    app = QApplication(sys.argv)

    data_dir = config.load_data_dir()
    if not data_dir:
        QMessageBox.information(
            None, "Choose data folder",
            "Please choose a folder where Project Tracker should store its "
            "database and attachments (e.g. a folder on a shared drive)."
        )
        chosen = QFileDialog.getExistingDirectory(None, "Choose data folder", app_dir)
        data_dir = chosen or app_dir
        config.save_data_dir(data_dir)

    db = Database(config.db_path_for(data_dir), config.attachments_dir_for(data_dir))

    # Silent, automatic protection against corruption/accidental deletion —
    # at most once a day, never blocks startup on failure.
    backup.maybe_create_auto_backup(config.db_path_for(data_dir), data_dir)

    window = MainWindow(db, data_dir)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
