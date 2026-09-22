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
    QPushButton, QLabel, QMessageBox, QFileDialog, QStackedWidget, QFrame
)
from PySide6.QtCore import Qt, QSettings, QSize
from PySide6.QtGui import QIcon, QShortcut, QKeySequence

import config
from app_paths import get_app_dir, get_resource_dir
from constants import APP_VERSION
from database import Database
import backup
from ui.styles import get_stylesheet, DARK_TOKENS, LIGHT_TOKENS
from ui.icons import make_icon
from ui.command_palette import (
    CommandPalette, ACTION_ADD_ITEM, ACTION_EXPORT_PDF, ACTION_SEARCH_ALL,
    ACTION_TOGGLE_THEME, ACTION_TOGGLE_LANGUAGE,
)
import constants
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




#: Stable identity Windows uses to group this app's taskbar button. Without
#: an explicit one, a packaged app can inherit a generic identity and keep
#: showing a cached placeholder icon in the taskbar.
APP_USER_MODEL_ID = "ProjectTracker.DesktopApp"


def _set_windows_app_id():
    """Tell Windows which app this is, so the taskbar uses OUR icon.

    Windows-only and best-effort: any failure is logged and ignored, because
    a taskbar identity is never worth failing startup over."""
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:  # noqa: BLE001 - cosmetic only
        logger.warning("Could not set the Windows app id", exc_info=True)


def _app_icon():
    """The window / taskbar icon bundled with the app.

    Returns an empty QIcon when the asset is missing, so a missing icon can
    never stop the app from starting."""
    for name in ("app.ico", "app.png"):
        path = os.path.join(get_resource_dir(), "assets", name)
        if os.path.isfile(path):
            return QIcon(path)
    logger.warning("App icon not found next to %s", get_resource_dir())
    return QIcon()


class MainWindow(QMainWindow):
    def __init__(self, db, data_dir):
        super().__init__()
        self.db = db
        self.data_dir = data_dir
        self._settings = QSettings("ProjectTracker", "MainWindow")

        self.current_theme = self._settings.value("theme", "dark")
        # Collapsed by default: a hamburger menu that the user can open,
        # and the choice sticks for next time.
        self._sidebar_collapsed = self._settings.value("sidebar_collapsed", True, type=bool)
        i18n.set_language(self._settings.value("language", "ar"))
        QApplication.instance().setLayoutDirection(
            Qt.RightToLeft if i18n.get_language() == "ar" else Qt.LeftToRight
        )

        self.resize(1360, 800)
        self.setMinimumSize(1024, 620)
        self._build_central_widget()
        # Created once, on the window itself: rebuilding the central widget
        # on a language change must not register these shortcuts twice.
        QShortcut(QKeySequence("Ctrl+K"), self, self._open_command_palette)
        QShortcut(QKeySequence("Ctrl+Shift+F"), self, self._open_global_search)
        QShortcut(QKeySequence("Ctrl+B"), self, self._toggle_sidebar)
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
        # Sidebar is added FIRST so Qt puts it on the leading edge in both
        # directions: right under Arabic (RTL), left under English (LTR).
        self.sidebar = self._build_sidebar()
        body.addWidget(self.sidebar)
        body.addWidget(self.stack, 1)

        root.addWidget(self.undo_bar)
        self._pad_undo_bar()

        self._navigate(0, "projects")
        self._build_menu_bar()
        self._update_status_bar()

    def _build_sidebar(self):
        """Collapsible navigation rail.

        Expanded it shows the logo, the labelled page navigation and the
        global tools. Collapsed - the hamburger - it shrinks to an icon-only
        strip so the content area gets the width back. The state is
        remembered between runs."""
        side = QWidget()
        side.setObjectName("sidebar")
        self.sidebar = side

        layout = QVBoxLayout(side)
        layout.setContentsMargins(12, 14, 12, 14)
        layout.setSpacing(2)
        self._sidebar_layout = layout
        self._sidebar_labels = []

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)

        self.hamburger_btn = QPushButton()
        self.hamburger_btn.setObjectName("hamburgerButton")
        self.hamburger_btn.setCursor(Qt.PointingHandCursor)
        self.hamburger_btn.setIconSize(QSize(18, 18))
        self.hamburger_btn.setProperty("iconName", "menu")
        self.hamburger_btn.clicked.connect(self._toggle_sidebar)
        header.addWidget(self.hamburger_btn)

        self.logo_label = QLabel()
        self.logo_label.setObjectName("logoLabel")
        self._apply_logo()
        header.addWidget(self.logo_label)
        header.addStretch()
        layout.addLayout(header)
        layout.addSpacing(6)

        self.nav_buttons = {}
        self._add_sidebar_label(tr("side_section_nav"))
        for key, page_index, label_key, icon_name in [
            ("projects", 0, "projects", "grid"),
            ("suppliers", 2, "suppliers", "users"),
            ("ai", 3, "ai_assistant", "spark"),
            ("dashboard", 4, "dashboard", "chart"),
        ]:
            btn = QPushButton(tr(label_key))
            self._prepare_nav_button(btn, icon_name, checkable=True)
            btn.clicked.connect(lambda _checked, idx=page_index, k=key: self._navigate(idx, k))
            layout.addWidget(btn)
            self.nav_buttons[key] = btn

        self._add_sidebar_label(tr("side_section_open"))
        items_btn = QPushButton(tr("items_tracker"))
        self._prepare_nav_button(items_btn, "list", checkable=True, tooltip=tr("palette_hint"))
        items_btn.clicked.connect(lambda: self._navigate(1, "items"))
        layout.addWidget(items_btn)
        self.nav_buttons["items"] = items_btn

        layout.addStretch()

        self._add_sidebar_label(tr("side_section_tools"))

        self.search_btn = QPushButton(tr("search_all_projects"))
        self._prepare_nav_button(self.search_btn, "search", tooltip=tr("search_all_projects_tip"))
        self.search_btn.clicked.connect(self._open_global_search)
        layout.addWidget(self.search_btn)

        self.palette_btn = QPushButton(tr("command_palette"))
        self._prepare_nav_button(self.palette_btn, "command", tooltip=tr("palette_hint"))
        self.palette_btn.clicked.connect(self._open_command_palette)
        layout.addWidget(self.palette_btn)

        self.theme_btn = QPushButton(
            tr("light_mode") if self.current_theme == "dark" else tr("dark_mode"))
        self._prepare_nav_button(self.theme_btn, "theme")
        self.theme_btn.clicked.connect(self._toggle_theme)
        layout.addWidget(self.theme_btn)

        self.lang_btn = QPushButton(tr("language"))
        self._prepare_nav_button(self.lang_btn, "lang")
        self.lang_btn.clicked.connect(self._toggle_language)
        layout.addWidget(self.lang_btn)

        self._apply_sidebar_state()
        return side

    def _add_sidebar_label(self, text):
        label = self._section_label(text)
        self._sidebar_layout.addWidget(label)
        self._sidebar_labels.append(label)
        return label

    # ------------------------------------------------------------------ #
    # Collapse / expand
    # ------------------------------------------------------------------ #
    def _toggle_sidebar(self):
        self._sidebar_collapsed = not getattr(self, "_sidebar_collapsed", False)
        self._settings.setValue("sidebar_collapsed", self._sidebar_collapsed)
        self._apply_sidebar_state()

    def _sidebar_text(self, btn):
        """The label a sidebar button shows when the rail is expanded."""
        return btn.property("fullText") or btn.text()

    def _set_sidebar_button_text(self, btn, text):
        btn.setProperty("fullText", text)
        collapsed = getattr(self, "_sidebar_collapsed", False)
        btn.setText("" if collapsed else text)
        if collapsed:
            btn.setToolTip(text)

    def _apply_sidebar_state(self):
        """Collapsed = icon-only rail. Buttons keep their labels in a
        property, so nothing has to be rebuilt to switch states."""
        collapsed = getattr(self, "_sidebar_collapsed", False)
        side = getattr(self, "sidebar", None)
        if side is None:
            return
        side.setFixedWidth(64 if collapsed else 230)
        layout = getattr(self, "_sidebar_layout", None)
        if layout is not None:
            layout.setContentsMargins(8 if collapsed else 12, 14, 8 if collapsed else 12, 14)

        for label in getattr(self, "_sidebar_labels", []):
            label.setVisible(not collapsed)
        if hasattr(self, "logo_label"):
            self.logo_label.setVisible(not collapsed and config.logo_path() is not None)
        if hasattr(self, "hamburger_btn"):
            self.hamburger_btn.setToolTip(tr("menu_toggle_tip"))

        buttons = list(getattr(self, "nav_buttons", {}).values())
        for attr in ("search_btn", "palette_btn", "theme_btn", "lang_btn"):
            btn = getattr(self, attr, None)
            if btn is not None:
                buttons.append(btn)
        for btn in buttons:
            text = self._sidebar_text(btn)
            btn.setText("" if collapsed else text)
            if collapsed:
                btn.setToolTip(text)
            else:
                btn.setToolTip(btn.property("baseTip") or "")

        self._refresh_sidebar_icons()

    @staticmethod
    def _section_label(text):
        label = QLabel(text)
        label.setObjectName("sideSection")
        return label



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
            # Keep the user oriented: coming back from the items screen should
            # land on the project they were just working in.
            open_project = getattr(self.tracker_page, "project", None)
            if open_project:
                self.projects_page.select_project(open_project["id"])
        elif key == "dashboard":
            self.dashboard_page.reload()

    def _open_project(self, project_id):
        self.tracker_page.open_project(project_id)
        self.stack.setCurrentIndex(1)
        for btn in self.nav_buttons.values():
            btn.setChecked(False)
        self.nav_buttons["items"].setChecked(True)
        config.save_last_project_id(project_id)

    def _open_project_and_item(self, project_id, item_id):
        """Same as _open_project, but also selects/scrolls to a specific
        item — used by the Dashboard's stale-items list and by
        Search All Projects."""
        self.tracker_page.open_project(project_id, select_item_id=item_id)
        self.stack.setCurrentIndex(1)
        for btn in self.nav_buttons.values():
            btn.setChecked(False)
        self.nav_buttons["items"].setChecked(True)
        config.save_last_project_id(project_id)

    def _open_global_search(self):
        dlg = GlobalSearchDialog(self, self.db)
        dlg.result_chosen.connect(self._open_project_and_item)
        dlg.exec()

    # ------------------------------------------------------------------ #
    # Sidebar icons
    # ------------------------------------------------------------------ #
    def _prepare_nav_button(self, btn, icon_name, checkable=False, tooltip=""):
        """Wires a sidebar button to a drawn icon that re-colours itself for
        the active theme and for the checked state, and remembers its label so
        the rail can collapse to icons only without losing anything."""
        btn.setObjectName("navButton")
        btn.setProperty("iconName", icon_name)
        btn.setProperty("fullText", btn.text())
        btn.setProperty("baseTip", tooltip)
        btn.setIconSize(QSize(16, 16))
        btn.setCursor(Qt.PointingHandCursor)
        if checkable:
            btn.setCheckable(True)
            btn.toggled.connect(lambda _checked, b=btn: self._apply_button_icon(b))

    def _icon_colors(self):
        tokens = DARK_TOKENS if self.current_theme == "dark" else LIGHT_TOKENS
        return tokens["muted"], tokens["accent"]

    def _apply_button_icon(self, btn):
        name = btn.property("iconName")
        if not name:
            return
        muted, accent = self._icon_colors()
        active = btn.isCheckable() and btn.isChecked()
        btn.setIcon(make_icon(name, accent if active else muted))

    def _refresh_sidebar_icons(self):
        """Icons are pixmaps, not stylesheet rules, so they are regenerated
        whenever the theme changes and for every state change."""
        for btn in list(getattr(self, "nav_buttons", {}).values()):
            self._apply_button_icon(btn)
        # The hamburger lives in the same rail, so it needs its icon drawn
        # too - without this it was an invisible (but working) button.
        for attr in ("hamburger_btn", "search_btn", "palette_btn", "theme_btn", "lang_btn"):
            btn = getattr(self, attr, None)
            if btn is not None:
                self._apply_button_icon(btn)

    def _open_command_palette(self):
        """Ctrl+K: one box for projects, items and common actions."""
        palette = CommandPalette(self, self.db)
        palette.set_context(getattr(self.tracker_page, "project", None) is not None)
        palette.item_chosen.connect(self._open_project_and_item)
        palette.project_chosen.connect(self._open_project)
        palette.action_requested.connect(self._run_palette_action)
        # Kept alive for the lifetime of the popup.
        self._palette = palette
        palette.open_palette()

    def _run_palette_action(self, action_id):
        if action_id == ACTION_ADD_ITEM:
            self.tracker_page.add_item_from_palette()
        elif action_id == ACTION_EXPORT_PDF:
            self.tracker_page.export_pdf_from_palette()
        elif action_id == ACTION_SEARCH_ALL:
            self._open_global_search()
        elif action_id == ACTION_TOGGLE_THEME:
            self._toggle_theme()
        elif action_id == ACTION_TOGGLE_LANGUAGE:
            self._toggle_language()

    # ---------------------------------------------------------------
    # Theme / language
    # ---------------------------------------------------------------
    def _toggle_theme(self):
        new_theme = "light" if self.current_theme == "dark" else "dark"
        self._apply_theme(new_theme)

    def _apply_theme(self, theme):
        self.current_theme = theme
        self._settings.setValue("theme", theme)
        # Table chips are painted as cell brushes rather than through the
        # stylesheet, so the theme has to be published where they are built.
        constants.set_theme(theme)
        rtl = i18n.get_language() == "ar"
        QApplication.instance().setStyleSheet(get_stylesheet(theme, rtl=rtl))
        if hasattr(self, "theme_btn"):
            self._set_sidebar_button_text(
                self.theme_btn, tr("light_mode") if theme == "dark" else tr("dark_mode"))
        # ...and the already-open Items screen re-styles its rows now, so the
        # chips never lag behind the rest of the UI after a theme switch.
        tracker = getattr(self, "tracker_page", None)
        if tracker is not None:
            tracker.on_theme_changed()
        projects = getattr(self, "projects_page", None)
        if projects is not None:
            projects.on_theme_changed()
        self._refresh_sidebar_icons()



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
    _set_windows_app_id()
    app.setWindowIcon(_app_icon())

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
