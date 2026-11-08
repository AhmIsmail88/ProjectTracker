import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile
import threading
import unittest
from unittest.mock import patch

from PySide6.QtCore import QSettings, QThread, QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QCloseEvent
from PySide6.QtTest import QTest

import config
import auth
import i18n
import main
from database import Database
from ui.items_page import COL_UNIT_COST
from ui.ai_page import AIPage


class NavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        self.settings = QSettings(os.path.join(self.root, "ui.ini"), QSettings.IniFormat)
        self.settings.setValue("language", "ar")
        for target, value in (("config.CONFIG_PATH", os.path.join(self.root, "config.json")),
                              ("main.QSettings", lambda *args: self.settings),
                              ("ui.dashboard_page.QSettings", lambda *args: self.settings)):
            context = patch(target, value)
            context.start()
            self.addCleanup(context.stop)
        language = i18n.get_language()
        direction = self.app.layoutDirection()
        self.addCleanup(i18n.set_language, language)
        self.addCleanup(self.app.setLayoutDirection, direction)
        self.db = Database(os.path.join(self.root, "db.sqlite"), os.path.join(self.root, "attachments"))
        self.pid = self.db.add_project("Project A")
        self.pid2 = self.db.add_project("Project B")
        self.iid = self.db.add_item(self.pid, "Pump", total_quantity=2, unit_cost=12)
        uid = self.db.add_user("boss", "pw", role="manager")
        auth.login(self.db.get_user(uid), self.db)
        self.addCleanup(auth.logout)
        self.window = main.MainWindow(self.db, self.root)
        self.addCleanup(self._dispose_window)

    def _dispose_window(self):
        self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_language_change_stays_on_each_screen_with_project_open(self):
        self.window._open_project(self.pid)
        for index, key in enumerate(("projects", "items", "suppliers", "ai", "dashboard", "schedule")):
            for _ in range(2):
                with self.subTest(screen=key, language=i18n.get_language()):
                    self.window._navigate(index, key)
                    self.window._toggle_language()
                    self.assertEqual(self.window.stack.currentIndex(), index)
                    self.assertTrue(self.window.nav_buttons[key].isChecked())
                    self.assertEqual(self.window.tracker_page.project["id"], self.pid)
                    self.assertEqual(self.window.schedule_page.project["id"], self.pid)
                    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_projects_search_and_selection_survive_language_change(self):
        self.window._open_project(self.pid)
        self.window._navigate(0, "projects")
        self.window.projects_page.search_edit.setText("Project B")
        self.window.projects_page.select_project(self.pid2)
        self.window._toggle_language()
        self.assertEqual(self.window.stack.currentIndex(), 0)
        self.assertEqual(self.window.projects_page.search_edit.text(), "Project B")
        self.assertEqual(self.window.projects_page.selected_project_id(), self.pid2)

    def test_project_group_overview_survives_language_change(self):
        group = self.db.add_project_group("Main group")
        self.db.update_project(self.pid, group_id=group)
        self.window.projects_page.reload()
        self.window.projects_page.restore_scope(("group", group))
        self.window._toggle_language()
        self.assertEqual(self.window.projects_page.selected_scope(), ("group", group))
        self.assertEqual(self.window.projects_page.overview.title.text(), "Main group")

    def test_project_metric_click_opens_exact_status_and_clears_old_filters(self):
        self.db.add_item(self.pid, "Held", manual_hold=True)
        self.db.add_item(self.pid, "Delivered", total_quantity=1, requested_quantity=1, delivered_quantity=1)
        self.window.projects_page.reload()
        for key, status in (("pending", "Not requested"), ("blocked", "On Hold"),
                            ("delivered", "Delivered"), ("items", None)):
            self.window._navigate(0, "projects")
            self.window.projects_page.select_project(self.pid)
            self.window.tracker_page.search_edit.setText("old filter")
            self.window.show()
            self.app.processEvents()
            card = self.window.projects_page.overview.metric_cards[key]
            QTest.mouseClick(card, Qt.LeftButton)
            self.assertEqual(self.window.stack.currentIndex(), 1)
            self.assertEqual(self.window.tracker_page.project["id"], self.pid)
            self.assertEqual(self.window.tracker_page.search_edit.text(), "")
            self.assertEqual(self.window.tracker_page.status_filter.currentData(), status)
            visible = [r for r in range(self.window.tracker_page.items_table.rowCount())
                       if not self.window.tracker_page.items_table.isRowHidden(r)]
            self.assertEqual(len(visible), 3 if status is None else 1)

    def test_tracker_filters_selection_and_report_tab_survive_language_change(self):
        self.window._open_project(self.pid)
        tracker = self.window.tracker_page
        tracker.search_edit.setText("Pump")
        tracker.status_filter.setCurrentIndex(tracker.status_filter.findData("Not requested"))
        tracker.missing_prpo_check.setChecked(True)
        tracker.advanced_filters_btn.setChecked(True)
        tracker._select_rows_by_item_ids([self.iid])
        tracker.tabs.setCurrentIndex(1)
        self.window._toggle_language()
        tracker = self.window.tracker_page
        self.assertEqual(tracker.tabs.currentIndex(), 1)
        self.assertEqual(tracker.search_edit.text(), "Pump")
        self.assertEqual(tracker.status_filter.currentData(), "Not requested")
        self.assertTrue(tracker.missing_prpo_check.isChecked())
        self.assertTrue(tracker.advanced_filters_btn.isChecked())
        self.assertEqual(tracker._selected_item_ids(), [self.iid])

    def test_ai_scope_and_unsent_draft_survive_language_change(self):
        self.window._navigate(3, "ai")
        page = self.window.ai_page
        index = next(i for i in range(page.scope_combo.count()) if page.scope_combo.itemData(i) == ("project", self.pid))
        page.scope_combo.setCurrentIndex(index)
        page.input_edit.setText("Unsent question")
        self.window._toggle_language()
        self.assertEqual(self.window.stack.currentIndex(), 3)
        self.assertEqual(self.window.ai_page.scope_combo.currentData(), ("project", self.pid))
        self.assertEqual(self.window.ai_page.input_edit.text(), "Unsent question")

    def test_deleted_project_is_not_reopened_at_startup_or_navigation(self):
        config.save_last_project_id(self.pid)
        self.db.delete_project(self.pid)
        self.window._reopen_last_project()
        self.assertEqual(self.window.stack.currentIndex(), 0)
        self.assertIsNone(self.window.tracker_page.project)
        self.window._open_project(self.pid)
        self.window._open_project(99999)
        self.assertIsNone(self.window.tracker_page.project)
        self.window._open_project(self.pid2)
        self.db.delete_project(self.pid2)
        self.window._navigate(5, "schedule")
        self.assertEqual(self.window.stack.currentIndex(), 0)

    def test_ai_history_changes_when_deleted_scope_falls_back_to_all(self):
        self.db.save_chat_message(self.pid, "user", "Project-only question")
        self.db.save_chat_message(None, "user", "All-project question")
        page = AIPage(self.db)
        index = next(i for i in range(page.scope_combo.count()) if page.scope_combo.itemData(i) == ("project", self.pid))
        page.scope_combo.setCurrentIndex(index)
        self.db.delete_project(self.pid)
        page.refresh_projects()
        self.assertEqual(page.scope_combo.currentData(), ("all", None))
        self.assertEqual(page._history, [{"role": "user", "content": "All-project question"}])

    def test_programmatic_selection_updates_current_project_and_supplier(self):
        self.window.projects_page.select_project(self.pid2)
        with patch("ui.projects_page.QMessageBox.information") as message:
            self.assertEqual(self.window.projects_page.selected_project_id(), self.pid2)
            message.assert_not_called()
        sid = self.db.add_supplier("Supplier A")
        self.window.suppliers_page.reload()
        self.window.suppliers_page._select_row_by_id(sid)
        with patch("ui.suppliers_page.QMessageBox.information") as message:
            self.assertEqual(self.window.suppliers_page._selected_id(), sid)
            message.assert_not_called()

    def test_inline_edit_rejects_nan_and_infinity_without_changing_price(self):
        self.window._open_project(self.pid)
        with patch("ui.items_page.QMessageBox.warning") as warning:
            for value in ("NaN", "inf", "-inf"):
                tracker = self.window.tracker_page
                row = tracker._row_for_item_id(self.iid)
                tracker.items_table.item(row, COL_UNIT_COST).setText(value)
                self.assertEqual(self.db.get_item(self.iid)["unit_cost"], 12)
            self.assertEqual(warning.call_count, 3)

    def test_saved_scaled_columns_are_not_scaled_again_after_language_change(self):
        self.window._open_project(self.pid)
        self.window._set_interface_scale(1.3)
        table = self.window.tracker_page.items_table
        table.setColumnWidth(1, 312)
        state = bytes(table.horizontalHeader().saveState().toBase64()).decode("ascii")
        config.save_table_layout("items_table", state, scale=1.3)
        self.window._toggle_language()
        self.assertEqual(self.window.tracker_page.items_table.columnWidth(1), 312)

    def test_quick_project_switch_keeps_schedule_page_and_resets_old_filters(self):
        self.window._open_project(self.pid)
        self.window.tracker_page.search_edit.setText("Pump")
        self.window.tracker_page.missing_cost_check.setChecked(True)
        self.window._navigate(5, "schedule")
        picker = self.window.schedule_page.project_picker
        picker.setCurrentIndex(picker.findData(self.pid2))
        picker._activated(picker.currentIndex())
        self.assertEqual(self.window.stack.currentIndex(), 5)
        self.assertEqual(self.window.schedule_page.project["id"], self.pid2)
        self.assertEqual(self.window.tracker_page.project["id"], self.pid2)
        self.assertEqual(self.window.tracker_page.search_edit.text(), "")
        self.assertFalse(self.window.tracker_page.missing_cost_check.isChecked())

    def test_language_rebuild_waits_until_background_worker_finishes(self):
        release = threading.Event()
        class Worker(QThread):
            def run(self):
                release.wait(5)
        worker = Worker()
        def stop():
            release.set()
            worker.wait(1000)
        self.addCleanup(stop)
        self.window.ai_page._worker = worker
        old_page = self.window.ai_page
        worker.start()
        self.window._toggle_language()
        self.assertTrue(self.window._language_change_pending)
        self.assertEqual(i18n.get_language(), "ar")
        self.assertIs(self.window.ai_page, old_page)
        stop()
        self.window._complete_language_change()
        self.assertEqual(i18n.get_language(), "en")
        self.assertEqual(self.window.stack.currentIndex(), 0)
        self.assertIsNot(self.window.ai_page, old_page)

    def test_close_is_deferred_while_worker_is_running(self):
        release = threading.Event()
        class Worker(QThread):
            def run(self):
                release.wait(5)
        worker = Worker()
        self.window.ai_page._worker = worker
        worker.start()
        try:
            event = QCloseEvent()
            self.window.closeEvent(event)
            self.assertFalse(event.isAccepted())
            self.assertTrue(self.window._close_pending)
        finally:
            release.set()
            worker.wait(1000)
        with patch.object(self.window, "close") as close:
            self.window._retry_close()
            close.assert_called_once()

    def test_data_folder_cannot_switch_while_worker_owns_old_widgets(self):
        release = threading.Event()
        class Worker(QThread):
            def run(self):
                release.wait(5)
        worker = Worker()
        self.window.ai_page._worker = worker
        original_page = self.window.ai_page
        worker.start()
        try:
            self.assertFalse(self.window._switch_to_data_dir(os.path.join(self.root, "new")))
            self.assertIs(self.window.ai_page, original_page)
            self.assertIs(self.window.db, self.db)
        finally:
            release.set()
            worker.wait(1000)
