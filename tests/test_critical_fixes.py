"""Regression tests for the data-safety fixes of the November 2026 review.

Every test works in its own temporary folder; none touches the real data
folder, config.json or the real database.
"""
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import openpyxl
from PySide6.QtWidgets import QApplication, QMessageBox

import auth
import backup
import config
from database import Database
from export.excel_export import export_items_for_cost_update
from importers.excel_import import import_cost_updates_from_excel


class _TempDbCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        self.db_path = os.path.join(self.root, "project_tracker.db")
        self.db = Database(self.db_path, os.path.join(self.root, "attachments"))
        self.pid = self.db.add_project("Tower A")
        self.iid = self.db.add_item(self.pid, "Pipe 100mm", total_quantity=12.345,
                                    requested_quantity=0.125, unit_cost=3.14159,
                                    currency="ريال")

    def set_last_updated(self, value="2026-01-01 00:00:00"):
        with self.db._connect() as conn:
            conn.execute("UPDATE items SET last_updated = ? WHERE id = ?", (value, self.iid))

    def audit_count(self):
        with self.db._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM audit_log WHERE entity_type='item' "
                                "AND action='updated'").fetchone()[0]


class ItemDialogPrecisionTests(_TempDbCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def dialog(self):
        from ui.dialogs import ItemDialog
        return ItemDialog(None, item=self.db.get_item(self.iid), suppliers=[], db=None)

    def test_untouched_fields_keep_exact_values_and_currency(self):
        data = self.dialog().get_data()
        self.assertEqual(data["total_quantity"], 12.345)
        self.assertEqual(data["requested_quantity"], 0.125)
        self.assertEqual(data["unit_cost"], 3.14159)
        self.assertEqual(data["currency"], "ريال")

    def test_saving_unchanged_dialog_writes_nothing(self):
        self.set_last_updated()
        before = self.audit_count()
        self.db.update_item(self.iid, **self.dialog().get_data())
        self.assertEqual(self.db.get_item(self.iid)["last_updated"], "2026-01-01 00:00:00")
        self.assertEqual(self.audit_count(), before)

    def test_edited_field_is_saved(self):
        dlg = self.dialog()
        dlg.total_qty_spin.setValue(20)
        self.assertEqual(dlg.get_data()["total_quantity"], 20)
        self.assertEqual(dlg.get_data()["unit_cost"], 3.14159)


class UpdateItemNoOpTests(_TempDbCase):
    def test_same_value_update_keeps_last_updated_and_stale_flag(self):
        # Only "Not requested" items can be stale; use one.
        self.iid = self.db.add_item(self.pid, "Gate valve", total_quantity=4, unit_cost=50)
        self.set_last_updated()
        self.assertEqual(len(self.db.get_dashboard_summary()["stale_items"]), 1)
        self.db.update_item(self.iid, unit_cost=50.0, remarks=None, po_issued=False)
        self.assertEqual(len(self.db.get_dashboard_summary()["stale_items"]), 1)

    def test_real_change_is_written_and_audited(self):
        self.set_last_updated()
        before = self.audit_count()
        self.db.update_item(self.iid, unit_cost=5)
        item = self.db.get_item(self.iid)
        self.assertEqual(item["unit_cost"], 5)
        self.assertNotEqual(item["last_updated"], "2026-01-01 00:00:00")
        self.assertEqual(self.audit_count(), before + 1)

    def test_missing_item_raises_clear_error(self):
        with self.assertRaises(ValueError):
            self.db.update_item(999999, unit_cost=1)

    def test_unknown_columns_change_nothing(self):
        self.set_last_updated()
        self.db.update_item(self.iid, not_a_column=1)
        self.assertEqual(self.db.get_item(self.iid)["last_updated"], "2026-01-01 00:00:00")


class CostImportSafetyTests(_TempDbCase):
    def setUp(self):
        super().setUp()
        self.other = self.db.add_item(self.pid, "Valve", unit_cost=10)
        manager = self.db.add_user("boss", "password", role="manager")
        auth.login(self.db.get_user(manager), self.db)
        self.addCleanup(auth.logout)

    def exported(self, edit=None):
        path = os.path.join(self.root, "costs.xlsx")
        export_items_for_cost_update(self.db, [self.pid], path)
        if edit:
            wb = openpyxl.load_workbook(path)
            edit(wb.active)
            wb.save(path)
            wb.close()
        return path

    @staticmethod
    def row_of(ws, item_id):
        for row in ws.iter_rows(min_row=3):
            if row[0].value == item_id:
                return row
        raise AssertionError("item not in sheet")

    def test_round_trip_counts_unchanged_and_touches_nothing(self):
        self.set_last_updated()
        result = import_cost_updates_from_excel(self.db, self.exported())
        self.assertEqual((result["updated"], result["unchanged"]), (0, 2))
        self.assertEqual(self.db.get_item(self.iid)["last_updated"], "2026-01-01 00:00:00")

    def test_changed_price_is_applied(self):
        path = self.exported(lambda ws: setattr(self.row_of(ws, self.other)[7], "value", 42))
        result = import_cost_updates_from_excel(self.db, path)
        self.assertEqual(result["updated"], 1)
        self.assertEqual(self.db.get_item(self.other)["unit_cost"], 42)

    def test_dry_run_reports_changes_without_writing(self):
        path = self.exported(lambda ws: setattr(self.row_of(ws, self.other)[7], "value", 42))
        result = import_cost_updates_from_excel(self.db, path, dry_run=True)
        self.assertEqual([c["item_id"] for c in result["changes"]], [self.other])
        self.assertEqual(result["changes"][0]["old"], 10)
        self.assertEqual(self.db.get_item(self.other)["unit_cost"], 10)

    def test_id_pointing_at_a_different_item_is_refused(self):
        def edit(ws):
            row = self.row_of(ws, self.other)
            row[2].value = "Some item from another data folder"
            row[7].value = 999
        result = import_cost_updates_from_excel(self.db, self.exported(edit))
        self.assertEqual(result["updated"], 0)
        self.assertEqual(len(result["mismatched"]), 1)
        self.assertEqual(self.db.get_item(self.other)["unit_cost"], 10)

    def test_project_name_mismatch_is_refused(self):
        def edit(ws):
            row = self.row_of(ws, self.other)
            row[1].value = "Another project"
            row[7].value = 999
        result = import_cost_updates_from_excel(self.db, self.exported(edit))
        self.assertEqual(len(result["mismatched"]), 1)
        self.assertEqual(self.db.get_item(self.other)["unit_cost"], 10)


class StartupProtectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.join(self.tmp.name, "data with spaces")
        os.makedirs(self.root)
        self.db_path = config.db_path_for(self.root)
        cfg = patch.object(config, "CONFIG_PATH", os.path.join(self.tmp.name, "config.json"))
        cfg.start()
        self.addCleanup(cfg.stop)

    def make_db(self):
        Database(self.db_path, config.attachments_dir_for(self.root)).add_project("Real")

    def test_integrity_ok_for_healthy_database(self):
        self.make_db()
        self.assertEqual(backup.check_integrity(self.db_path), (True, ""))

    def test_integrity_fails_for_garbage_file(self):
        with open(self.db_path, "wb") as f:
            f.write(b"this is not a database" * 100)
        ok, _message = backup.check_integrity(self.db_path)
        self.assertFalse(ok)

    def test_no_pruning_when_database_is_damaged(self):
        self.make_db()
        backups_dir = backup.backups_dir_for(self.root)
        os.makedirs(backups_dir)
        for day in range(1, 21):
            sqlite3.connect(os.path.join(backups_dir, f"project_tracker_2026-01-{day:02d}_120000.db")).close()
        backup.maybe_create_auto_backup(self.db_path, self.root, prune=False)
        self.assertEqual(len(os.listdir(backups_dir)), 21)

    def test_backup_is_taken_before_database_is_opened(self):
        self.make_db()
        import main
        with patch.object(main, "Database") as opened:
            opened.side_effect = AssertionError("must not open before protection ran")
            self.assertTrue(main.protect_database_before_open(self.db_path, self.root))
        self.assertIsNotNone(backup.last_backup_datetime(self.root))

    def test_missing_data_folder_is_never_replaced_on_exit(self):
        import main
        missing = os.path.join(self.tmp.name, "unplugged drive")
        config.save_data_dir(missing)
        with patch.object(QMessageBox, "exec", return_value=0), \
                patch.object(QMessageBox, "clickedButton", return_value=None):
            self.assertIsNone(main.resolve_data_dir(self.tmp.name))
        self.assertEqual(config.configured_data_dir(), missing)
        self.assertFalse(os.path.exists(missing))

    def test_existing_folder_without_database_needs_confirmation(self):
        import main
        config.save_data_dir(self.root)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.No):
            self.assertIsNone(main.resolve_data_dir(self.tmp.name))
        self.assertFalse(os.path.exists(self.db_path))

    def test_normal_start_returns_configured_folder(self):
        import main
        self.make_db()
        config.save_data_dir(self.root)
        self.assertEqual(main.resolve_data_dir(self.tmp.name), self.root)


class ConfigFileSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "config.json")
        cfg = patch.object(config, "CONFIG_PATH", self.path)
        cfg.start()
        self.addCleanup(cfg.stop)

    def test_save_leaves_no_temporary_files(self):
        config.save_data_dir(self.tmp.name)
        config.save_items_view("open")
        self.assertEqual(sorted(os.listdir(self.tmp.name)), ["config.json"])
        self.assertEqual(config.load_data_dir(), self.tmp.name)

    def test_damaged_config_is_preserved(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write('{"data_dir": "E:/Data", "broken')
        self.assertIsNone(config.configured_data_dir())
        with open(self.path + ".corrupt", encoding="utf-8") as f:
            self.assertIn("E:/Data", f.read())


if __name__ == "__main__":
    unittest.main()
