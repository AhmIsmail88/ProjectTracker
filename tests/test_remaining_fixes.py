"""Regression tests for review items 8-16 (permissions, backups, AI data,
currency, schema/startup writes, trash, attachment history, Excel links).
Everything runs in temporary folders against throw-away databases."""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, date
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import openpyxl
from PySide6.QtWidgets import QApplication

import auth
import backup
import i18n
from database import Database


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        self.db = Database(os.path.join(self.root, "project_tracker.db"),
                           os.path.join(self.root, "attachments"))
        self.pid = self.db.add_project("Tower A", currency="SAR")
        self.manager = self.db.get_user(self.db.add_user("boss", "password", role="manager"))
        self.engineer = self.db.get_user(self.db.add_user("eng", "password", role="user"))
        self.db.assign_projects_to_user(self.engineer["id"], [self.pid])
        self.addCleanup(auth.logout)

    def login(self, user):
        auth.login(user, self.db)


class PermissionTests(_Base):
    def setUp(self):
        super().setUp()
        self.sid = self.db.add_supplier("Acme")

    def page(self):
        from ui.suppliers_page import SuppliersPage
        from ui.widgets import UndoBar
        return SuppliersPage(self.db, UndoBar())

    def test_engineer_cannot_edit_or_delete_suppliers(self):
        self.login(self.engineer)
        page = self.page()
        self.assertFalse(page.edit_btn.isEnabled())
        self.assertFalse(page.delete_btn.isEnabled())
        page.table.selectRow(0)
        page._delete_supplier()
        self.assertEqual(len(self.db.get_suppliers()), 1)

    def test_engineer_can_still_add_a_supplier(self):
        self.login(self.engineer)
        page = self.page()
        with patch("ui.suppliers_page.SupplierDialog") as dialog:
            dialog.return_value.exec.return_value = True
            dialog.return_value.get_data.return_value = {"name": "New Co"}
            page._add_supplier()
        self.assertIn("New Co", [s["name"] for s in self.db.get_suppliers()])

    def test_manager_can_delete_suppliers(self):
        self.login(self.manager)
        page = self.page()
        self.assertTrue(page.delete_btn.isEnabled())
        page.table.selectRow(0)
        page._delete_supplier()
        self.assertEqual(self.db.get_suppliers(), [])

    def test_engineer_cannot_delete_items_forever(self):
        from ui.items_page import DeletedItemsDialog
        item = self.db.add_item(self.pid, "Pipe")
        self.db.delete_item(item)
        self.login(self.engineer)
        dialog = DeletedItemsDialog(None, self.db, self.pid)
        self.assertFalse(dialog.purge_btn.isEnabled())
        self.assertTrue(dialog.restore_btn.isEnabled())
        dialog.list_widget.setCurrentRow(0)
        with patch("ui.items_page.QMessageBox.question", return_value=0x4000):
            dialog._purge_selected()
        self.assertIsNotNone(self.db.get_item(item))


class BackupPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name

    def test_tiered_retention_keeps_weekly_and_monthly_history(self):
        today = date(2026, 11, 8)
        backups = [(datetime(2026, 11, 8) - timedelta(days=d), f"b{d}") for d in range(400)]
        keep = backup._backups_to_keep(backups, today=today)
        self.assertTrue({f"b{d}" for d in range(14)} <= keep)         # last 14 days
        kept_days = sorted(int(p[1:]) for p in keep)
        self.assertGreater(max(kept_days), 300)                          # ~11 months back
        self.assertLess(len(keep), 14 + KEEP_LIMIT)

    def test_mirror_is_incremental_and_add_only(self):
        att = os.path.join(self.root, "attachments", "item_1")
        os.makedirs(att)
        path = os.path.join(att, "po.pdf")
        Path(path).write_text("po")
        self.assertEqual(backup.mirror_attachments(os.path.dirname(att), self.root), 1)
        self.assertEqual(backup.mirror_attachments(os.path.dirname(att), self.root), 0)
        os.remove(path)  # e.g. "Delete Forever"
        backup.mirror_attachments(os.path.dirname(att), self.root)
        mirrored = os.path.join(backup.backups_dir_for(self.root), "attachments", "item_1", "po.pdf")
        self.assertTrue(os.path.isfile(mirrored))

    def test_copy_to_second_folder(self):
        src = os.path.join(self.root, "project_tracker_2026-11-08_090000.db")
        Path(src).write_text("x")
        extra = os.path.join(self.root, "usb")
        self.assertIsNone(backup.copy_to_extra_folder(src, extra))  # not connected
        os.makedirs(extra)
        self.assertTrue(os.path.isfile(backup.copy_to_extra_folder(src, extra)))


KEEP_LIMIT = backup.KEEP_WEEKLY + backup.KEEP_MONTHLY


class AITests(_Base):
    @unittest.skipUnless(sys.platform == "win32", "DPAPI is Windows-only")
    def test_key_is_not_stored_in_plain_text(self):
        from ai import settings
        target = Path(self.root) / "ai-settings.json"
        with patch("ai.settings.settings_path", return_value=target), \
                patch("ai.settings.get_app_dir", return_value=self.root), \
                patch.dict(os.environ, {}, clear=True):
            settings.save_settings("sk-or-secret-value", "m/x")
            raw = target.read_text(encoding="utf-8")
            self.assertNotIn("sk-or-secret-value", raw)
            self.assertNotIn('"api_key"', raw)
            self.assertEqual(settings.read_settings()["api_key"], "sk-or-secret-value")

    def test_legacy_plain_key_still_read(self):
        from ai import settings
        target = Path(self.root) / "ai-settings.json"
        target.write_text(json.dumps({"api_key": "old-key", "model": "m/x"}), encoding="utf-8")
        with patch("ai.settings.settings_path", return_value=target), \
                patch("ai.settings.get_app_dir", return_value=self.root), \
                patch.dict(os.environ, {}, clear=True):
            self.assertEqual(settings.read_settings()["api_key"], "old-key")

    def test_large_scope_is_summarized_and_flagged(self):
        from ui.ai_page import build_ai_data
        snapshot = [{"project": "P", "currency": "SAR", "items": [
            {"name": f"Item {i}" * 5, "supplier": None, "unit": "m", "total_qty": 1,
             "requested_qty": 0, "delivered_qty": 0, "status": "Not requested"} for i in range(3000)]}]
        text, note, truncated = build_ai_data(snapshot, max_chars=60_000)
        self.assertTrue(truncated)
        self.assertIn("SUMMARY", note)
        self.assertLessEqual(len(text), 60_000)
        small, note2, truncated2 = build_ai_data(snapshot[:0])
        self.assertFalse(truncated2)
        self.assertEqual(note2, "")


class CurrencyTests(_Base):
    def test_variance_report_uses_project_currency_when_item_has_none(self):
        self.db.add_item(self.pid, "Pipe", total_quantity=2, unit_cost=5, currency=None)
        rows = self.db.get_variance_report("area")
        self.assertEqual(rows[0]["values"], {"SAR": 10})


class StartupWriteTests(_Base):
    def test_clean_database_startup_writes_nothing_to_items(self):
        for name in ("A", "B", "C"):
            self.db.add_item(self.pid, name)
        statements = []
        original = self.db._open_connection

        def traced():
            conn = original()
            conn.set_trace_callback(statements.append)
            return conn

        with patch.object(self.db, "_open_connection", side_effect=traced):
            self.db._migrate_schema()
        self.assertFalse([s for s in statements if s.lstrip().upper().startswith("UPDATE ITEMS")])

    def test_schema_version_is_recorded(self):
        with self.db._connect() as conn:
            self.assertGreaterEqual(conn.execute("PRAGMA user_version").fetchone()[0], 1)


class AttachmentHistoryTests(_Base):
    def test_attachment_changes_appear_in_item_history(self):
        item = self.db.add_item(self.pid, "Pump")
        src = os.path.join(self.root, "po.pdf")
        Path(src).write_text("po")
        self.db.add_attachment(item, "PO", src)
        att = self.db.get_attachments(item)[0]["id"]
        self.db.delete_attachment(att)
        self.db.restore_attachment(att)
        actions = [r["action"] for r in self.db.get_activity(entity_type="item", entity_id=item)]
        for action in ("attachment_added", "attachment_deleted", "attachment_restored"):
            self.assertIn(action, actions)
        from ui.activity_widget import _format_row
        row = self.db.get_activity(entity_type="item", entity_id=item)[0]
        self.assertIn("po.pdf", _format_row(row)[0])


class TrashTests(_Base):
    def test_only_old_trash_is_counted_and_purged(self):
        keep_project = self.db.add_project("Recent")
        old_project = self.db.add_project("Old")
        old_item = self.db.add_item(self.pid, "Old item")
        new_item = self.db.add_item(self.pid, "New item")
        self.db.add_item(old_project, "Inside old project")
        long_ago = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d %H:%M:%S")
        with patch("database.now_str", return_value=long_ago):
            self.db.delete_project(old_project)
            self.db.delete_item(old_item)
        self.db.delete_project(keep_project)
        self.db.delete_item(new_item)

        summary = self.db.trash_summary(30)
        self.assertEqual((summary["projects"], summary["items_in_projects"], summary["loose_items"]),
                         (1, 1, 1))
        self.db.empty_trash_items_and_projects(30)
        self.assertIsNone(self.db.get_project(old_project))
        self.assertIsNone(self.db.get_item(old_item))
        self.assertIsNotNone(self.db.get_project(keep_project))
        self.assertIsNotNone(self.db.get_item(new_item))

    def test_trash_dialog_takes_backup_before_purging(self):
        from ui.projects_page import TrashDialog
        old = self.db.add_project("Old")
        long_ago = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d %H:%M:%S")
        with patch("database.now_str", return_value=long_ago):
            self.db.delete_project(old)
        self.login(self.manager)
        dialog = TrashDialog(None, self.db)
        with patch("ui.projects_page.QMessageBox.question", return_value=0x4000), \
                patch("ui.projects_page.QMessageBox.information"):
            dialog._empty_old_trash()
        self.assertIsNone(self.db.get_project(old))
        names = os.listdir(backup.backups_dir_for(self.root))
        self.assertTrue(any(n.startswith("before_empty_trash_") for n in names))

    def test_engineer_cannot_empty_trash(self):
        from ui.projects_page import TrashDialog
        self.login(self.engineer)
        dialog = TrashDialog(None, self.db)
        self.assertFalse(dialog.empty_btn.isEnabled())


class ExcelLinkTests(unittest.TestCase):
    def test_link_is_relative_inside_data_folder_and_absolute_outside(self):
        from export.excel_export import _attachment_link
        root = tempfile.mkdtemp()
        file_path = os.path.join(root, "attachments", "item_1", "po.pdf")
        self.assertEqual(_attachment_link(file_path, os.path.join(root, "report.xlsx")),
                         "attachments/item_1/po.pdf")
        outside = os.path.join(os.path.dirname(root), "elsewhere", "report.xlsx")
        self.assertTrue(os.path.isabs(_attachment_link(file_path, outside)))


class StartupTranslationTests(unittest.TestCase):
    def test_startup_messages_have_arabic(self):
        old = i18n.get_language()
        self.addCleanup(i18n.set_language, old)
        i18n.set_language("ar")
        for text in ("The data folder cannot be found:", "Create a new, EMPTY database here?",
                     "Choose data folder", "Managers only", "Second backup folder",
                     "SQLite reported a problem with the database file:", "Current:",
                     "No Project Tracker database was found in:",
                     "Trash emptied. Backup taken before deleting:",
                     "The latest backup was copied to:"):
            self.assertNotEqual(i18n.tr_text(text), text)


if __name__ == "__main__":
    unittest.main()
