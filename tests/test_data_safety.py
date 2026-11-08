import os
import shutil
import sqlite3
import tempfile
import unittest
import zipfile
from unittest.mock import patch
from contextlib import closing

import openpyxl

from backup import restore_backup, snapshot_database
from database import Database
from importers.excel_import import import_items_from_excel, import_cost_updates_from_excel


class DataSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        self.source = os.path.join(self.root, "source")
        os.makedirs(self.source)
        self.db = Database(os.path.join(self.source, "project_tracker.db"), os.path.join(self.source, "attachments"))
        self.pid = self.db.add_project("Safety")
        self.iid = self.db.add_item(self.pid, "Pump", unit_cost=12)

    def _attachment(self):
        file = os.path.join(self.root, "invoice.txt")
        with open(file, "w") as stream:
            stream.write("invoice")
        return self.db.add_attachment(self.iid, "Invoice", file)

    def test_project_restore_does_not_revive_item_deleted_in_same_second(self):
        active = self.db.add_item(self.pid, "Active")
        with patch("database.now_str", return_value="2026-10-08 12:00:00"):
            self.db.delete_item(self.iid)
            self.db.delete_project(self.pid)
        self.db.restore_project(self.pid)
        self.assertTrue(self.db.get_item(self.iid)["is_deleted"])
        self.assertEqual([item["id"] for item in self.db.get_items(self.pid)], [active])

    def test_cost_import_rejects_fractional_item_ids(self):
        path = os.path.join(self.root, "costs.xlsx")
        wb = openpyxl.Workbook()
        wb.active.append(["Item ID", "Unit Cost"])
        wb.active.append([self.iid + 0.9, 999])
        wb.save(path)
        wb.close()
        result = import_cost_updates_from_excel(self.db, path)
        self.assertEqual(self.db.get_item(self.iid)["unit_cost"], 12)
        self.assertEqual(result["updated"], 0)
        self.assertEqual(len(result["invalid"]), 1)

    def test_legacy_group_does_not_reappear_after_delete_and_restart(self):
        with self.db._connect() as conn:
            conn.execute("UPDATE projects SET project_group = 'Legacy' WHERE id = ?", (self.pid,))
        self.db._migrate_schema()
        group_id = self.db.get_project(self.pid)["group_id"]
        self.db.delete_project_group(group_id)
        self.db._migrate_schema()
        self.assertIsNone(self.db.get_project(self.pid)["group_id"])
        self.assertEqual(self.db.get_project_groups(), [])

    def test_legacy_project_stays_ungrouped_after_edit_and_restart(self):
        with self.db._connect() as conn:
            conn.execute("UPDATE projects SET project_group = 'Legacy' WHERE id = ?", (self.pid,))
        self.db._migrate_schema()
        self.db.update_project(self.pid, group_id=None)
        self.db._migrate_schema()
        self.assertIsNone(self.db.get_project(self.pid)["group_id"])

    def test_restored_legacy_attachment_opens_copy_and_purge_preserves_original(self):
        original = self._attachment()
        with self.db._connect() as conn:
            conn.execute("UPDATE attachments SET file_path = ?", (original,))
        archive_path = os.path.join(self.root, "backup.zip")
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.write(self.db.db_path, "project_tracker.db")
            archive.write(original, "attachments/" + os.path.relpath(original, self.db.attachments_dir).replace("\\", "/"))
        target = os.path.join(self.root, "restored")
        restored = Database(restore_backup(archive_path, target), os.path.join(target, "attachments"))
        copy = restored.get_attachments(self.iid)[0]["file_path"]
        self.assertTrue(os.path.isfile(copy))
        self.assertNotEqual(original, copy)
        restored.delete_item(self.iid)
        restored.purge_item(self.iid)
        self.assertTrue(os.path.isfile(original))
        self.assertFalse(os.path.exists(copy))

    def test_new_attachment_is_relative_and_survives_data_folder_move(self):
        original = self._attachment()
        with self.db._connect() as conn:
            stored = conn.execute("SELECT file_path FROM attachments").fetchone()[0]
        self.assertFalse(os.path.isabs(stored))
        target = os.path.join(self.root, "moved")
        shutil.copytree(self.source, target)
        moved = Database(os.path.join(target, "project_tracker.db"), os.path.join(target, "attachments"))
        self.assertEqual(moved.get_attachments(self.iid)[0]["file_path"], os.path.join(target, "attachments", *stored.split("/")))
        self.assertTrue(os.path.isfile(original))

    def test_purge_refuses_external_attachment_paths(self):
        external = os.path.join(self.root, "keep.txt")
        with open(external, "w") as stream:
            stream.write("keep")
        with self.db._connect() as conn:
            conn.execute("INSERT INTO attachments (item_id, category, file_path) VALUES (?, 'Invoice', ?)",
                         (self.iid, "../../keep.txt"))
        self.db.purge_item(self.iid)
        self.assertTrue(os.path.isfile(external))
        with self.assertRaises(ValueError):
            self.db.resolve_attachment_path(external)

    def test_snapshot_includes_committed_wal_data(self):
        source = os.path.join(self.root, "wal.db")
        conn = sqlite3.connect(source)
        self.addCleanup(conn.close)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE demo (value TEXT)")
        conn.execute("INSERT INTO demo VALUES ('committed')")
        conn.commit()
        target = os.path.join(self.root, "snapshot.db")
        snapshot_database(source, target)
        with closing(sqlite3.connect(target)) as copy:
            self.assertEqual(copy.execute("SELECT value FROM demo").fetchone()[0], "committed")

    def test_import_rejects_bad_quantities_with_row_and_column(self):
        path = os.path.join(self.root, "items.xlsx")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Item", "Quantity"])
        for value in ("typo", -2, "NaN", "inf", "1,200"):
            ws.append(["Pump", value])
        wb.save(path)
        wb.close()
        result = import_items_from_excel(self.db, self.pid, path, None, 1,
                                         {"item_name": "Item", "total_quantity": "Quantity"})
        self.assertEqual(result["imported"], 1)
        self.assertEqual(len(result["skipped"]), 4)
        self.assertIn("Row 2, column Quantity", result["skipped"][0])

    def test_invalid_cost_is_reported_and_does_not_overwrite_price(self):
        path = os.path.join(self.root, "costs.xlsx")
        wb = openpyxl.Workbook()
        wb.active.append(["Item ID", "Unit Cost"])
        wb.active.append([self.iid, "NaN"])
        wb.save(path)
        wb.close()
        result = import_cost_updates_from_excel(self.db, path)
        self.assertEqual(result["updated"], 0)
        self.assertEqual(result["skipped_blank"], 0)
        self.assertIn("Row 2, column Unit Cost", result["invalid"][0])
        self.assertEqual(self.db.get_item(self.iid)["unit_cost"], 12)
