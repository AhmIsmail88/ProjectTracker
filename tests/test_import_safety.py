"""All-or-nothing imports/bulk edits, duplicate re-import warning, formula
cells without saved values, and restoring a purged item.

Everything runs against throw-away databases in temporary folders."""
import os
import tempfile
import threading
import unittest
from unittest.mock import patch

import openpyxl

import auth
from database import Database
from importers.excel_import import (
    count_existing_rows, import_cost_updates_from_excel, import_items_from_excel,
)

MAPPING = {"item_name": "Item", "pump_station": "Area", "unit": "Unit",
           "total_quantity": "Qty", "unit_cost": "Rate"}


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        self.db = Database(os.path.join(self.root, "project_tracker.db"),
                           os.path.join(self.root, "attachments"))
        self.pid = self.db.add_project("Tower A")
        manager = self.db.add_user("boss", "password", role="manager")
        auth.login(self.db.get_user(manager), self.db)
        self.addCleanup(auth.logout)

    def sheet(self, rows, name="boq.xlsx"):
        path = os.path.join(self.root, name)
        wb = openpyxl.Workbook()
        wb.active.append(["Item", "Area", "Unit", "Qty", "Rate"])
        for row in rows:
            wb.active.append(row)
        wb.save(path)  # openpyxl stores formulas WITHOUT a computed value
        wb.close()
        return path

    def import_(self, path, **kwargs):
        return import_items_from_excel(self.db, self.pid, path, None, 1, MAPPING, **kwargs)


class TransactionTests(_Base):
    def test_bulk_update_is_all_or_nothing(self):
        a = self.db.add_item(self.pid, "A", unit="m")
        with self.assertRaises(ValueError):
            self.db.bulk_update_items([a, 999999], unit="kg")
        self.assertEqual(self.db.get_item(a)["unit"], "m")

    def test_find_replace_is_all_or_nothing(self):
        a = self.db.add_item(self.pid, "Pipe old", remarks="")
        b = self.db.add_item(self.pid, "Valve old", remarks="")
        real_update = self.db.update_item
        calls = []

        def failing_update(item_id, **fields):
            calls.append(item_id)
            if len(calls) == 2:
                raise RuntimeError("disk full")
            real_update(item_id, **fields)

        with patch.object(self.db, "update_item", side_effect=failing_update):
            with self.assertRaises(RuntimeError):
                self.db.bulk_find_replace([a, b], "item_name", "old", "new")
        self.assertEqual(self.db.get_item(a)["item_name"], "Pipe old")

    def test_other_threads_do_not_share_the_transaction_connection(self):
        seen = {}
        with self.db.transaction():
            with self.db._connect() as mine:
                seen["main"] = mine

            def other():
                with self.db._connect() as conn:
                    seen["other"] = conn
            t = threading.Thread(target=other)
            t.start()
            t.join()
        self.assertIsNot(seen["main"], seen["other"])


class ItemImportTests(_Base):
    def test_failure_part_way_imports_nothing(self):
        path = self.sheet([["Pipe", "Z1", "m", 10, 5], ["Valve", "Z1", "no", 2, 7],
                           ["Pump", "Z2", "no", 1, 900]])
        real_add = self.db.add_item
        calls = []

        def failing_add(*args, **kwargs):
            calls.append(1)
            if len(calls) == 3:
                raise RuntimeError("power cut")
            return real_add(*args, **kwargs)

        with patch.object(self.db, "add_item", side_effect=failing_add):
            with self.assertRaises(RuntimeError):
                self.import_(path)
        self.assertEqual(self.db.get_items(self.pid), [])

    def test_formula_without_saved_value_is_not_imported_as_zero(self):
        path = self.sheet([["Pipe", "Z1", "m", "=2*5", 5], ["Valve", "Z1", "no", 3, 7]])
        result = self.import_(path)
        self.assertEqual(result["imported"], 1)
        self.assertEqual(len(result["skipped"]), 1)
        self.assertIn("formula without a saved value", result["skipped"][0])
        self.assertEqual([it["item_name"] for it in self.db.get_items(self.pid)], ["Valve"])

    def test_reimport_is_detected_and_can_be_skipped(self):
        path = self.sheet([["Pipe", "Z1", "m", 10, 5], ["Valve", "Z1", "no", 3, 7]])
        self.import_(path)
        self.assertEqual(count_existing_rows(self.db, self.pid, path, None, 1, MAPPING), 2)
        result = self.import_(path, skip_existing=True)
        self.assertEqual((result["imported"], result["skipped_existing"]), (0, 2))
        self.assertEqual(len(self.db.get_items(self.pid)), 2)

    def test_same_name_in_another_area_is_not_a_duplicate(self):
        self.import_(self.sheet([["Pipe", "Z1", "m", 10, 5]]))
        path = self.sheet([["Pipe", "Z2", "m", 10, 5]], name="other.xlsx")
        self.assertEqual(count_existing_rows(self.db, self.pid, path, None, 1, MAPPING), 0)


class CostImportFormulaTests(_Base):
    def test_unit_cost_formula_without_value_is_reported(self):
        item = self.db.add_item(self.pid, "Pipe", unit_cost=5)
        path = os.path.join(self.root, "costs.xlsx")
        wb = openpyxl.Workbook()
        wb.active.append(["Item ID", "Unit Cost"])
        wb.active.append([item, "=3*4"])
        wb.save(path)
        wb.close()
        result = import_cost_updates_from_excel(self.db, path)
        self.assertEqual((result["updated"], result["skipped_blank"]), (0, 0))
        self.assertIn("formula without a saved value", result["invalid"][0])
        self.assertEqual(self.db.get_item(item)["unit_cost"], 5)


class RestoreItemTests(_Base):
    def test_restore_after_purge_does_not_crash(self):
        item = self.db.add_item(self.pid, "Pipe")
        self.db.delete_item(item)
        self.db.purge_item(item)
        self.db.restore_item(item)  # e.g. Undo clicked after Delete Forever
        self.assertIsNone(self.db.get_item(item))


if __name__ == "__main__":
    unittest.main()
