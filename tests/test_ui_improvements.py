import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication

import config
import i18n
from database import Database
from ui.items_page import TrackerPage, COL_STATUS, COL_UNIT_COST, COL_PRPO
from ui.widgets import UndoBar
from ui.dashboard_page import DashboardPage
from ui.ai_page import AIPage


class UiImprovementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        config_patch = patch.object(config, "CONFIG_PATH", os.path.join(self.root, "config.json"))
        config_patch.start()
        self.addCleanup(config_patch.stop)
        language = i18n.get_language()
        self.addCleanup(i18n.set_language, language)
        i18n.set_language("ar")
        self.db = Database(os.path.join(self.root, "db.sqlite"), os.path.join(self.root, "attachments"))
        self.pid = self.db.add_project("A")
        self.pid2 = self.db.add_project("B")
        self.db.add_item(self.pid, "Pump", total_quantity=2, requested_quantity=2, delivered_quantity=2)
        self.db.add_item(self.pid, "Valve", total_quantity=1)

    def test_translated_status_filter_uses_stored_status_values(self):
        tracker = TrackerPage(self.db, UndoBar())
        tracker.open_project(self.pid)
        self.assertEqual(tracker.items_table.horizontalHeaderItem(1).text(), "اسم البند")
        tracker.status_filter.setCurrentIndex(tracker.status_filter.findData("Delivered"))
        rows = [row for row in range(tracker.items_table.rowCount()) if not tracker.items_table.isRowHidden(row)]
        self.assertEqual(len(rows), 1)
        cell = tracker.items_table.item(rows[0], COL_STATUS)
        self.assertEqual(cell.data(Qt.UserRole), "Delivered")
        self.assertIn("تم التوريد", cell.text())
        tracker._clear_filters()
        self.assertTrue(all(not tracker.items_table.isRowHidden(row) for row in range(2)))

    def test_table_view_is_remembered_and_all_columns_can_be_restored(self):
        tracker = TrackerPage(self.db, UndoBar())
        tracker.view_combo.setCurrentIndex(tracker.view_combo.findData("documents"))
        self.assertTrue(tracker.items_table.isColumnHidden(COL_UNIT_COST))
        self.assertFalse(tracker.items_table.isColumnHidden(COL_PRPO))
        reopened = TrackerPage(self.db, UndoBar())
        self.assertEqual(reopened.view_combo.currentData(), "documents")
        reopened.view_combo.setCurrentIndex(reopened.view_combo.findData("all"))
        self.assertTrue(all(not reopened.items_table.isColumnHidden(col) for col in range(15)))

    def test_dashboard_clear_is_empty_and_all_projects_is_explicit(self):
        settings = QSettings(os.path.join(self.root, "ui.ini"), QSettings.IniFormat)
        with patch("ui.dashboard_page.QSettings", return_value=settings):
            page = DashboardPage(self.db)
            page.reload()
            self.assertIsNone(page._selected_project_ids())
            page._set_all_checked(False)
            self.assertEqual(page._selected_project_ids(), [])
            self.assertEqual(page.val_items.text(), "0")
            self.assertIn("لم تُحدد مشاريع", page.scope_label.text())
            reopened = DashboardPage(self.db)
            reopened.reload()
            self.assertEqual(reopened._selected_project_ids(), [])
            reopened.all_projects_check.setChecked(True)
            self.assertIsNone(reopened._selected_project_ids())
            self.assertEqual(reopened.val_items.text(), "2")
            reopened._set_all_checked(True)
            self.assertEqual(set(reopened._selected_project_ids()), {self.pid, self.pid2})

    def test_delayed_ai_reply_is_saved_to_request_scope(self):
        page = AIPage(self.db)
        first = next(i for i in range(page.scope_combo.count()) if page.scope_combo.itemData(i) == ("project", self.pid))
        second = next(i for i in range(page.scope_combo.count()) if page.scope_combo.itemData(i) == ("project", self.pid2))
        page.scope_combo.setCurrentIndex(first)
        with patch("ui.ai_page.openrouter_client.is_configured", return_value=True), patch("ui.ai_page._ChatWorker"), \
                patch.object(page, "_confirm_data_sharing", return_value=True):
            page._ask("Question")
            self.assertFalse(page.scope_combo.isEnabled())
            self.assertFalse(page.new_conv_btn.isEnabled())
            page._ask("Second question while waiting")
            self.assertEqual(len(self.db.get_chat_history(self.pid)), 1)
            # Programmatic scope changes are possible even on a disabled combo.
            page.scope_combo.setCurrentIndex(second)
            page._on_reply("Answer about A")
        self.assertEqual(self.db.get_chat_history(self.pid)[-1]["content"], "Answer about A")
        self.assertEqual(self.db.get_chat_history(self.pid2), [])
        self.assertTrue(page.scope_combo.isEnabled())
