"""Shared-database lock waits, restoring an item inside a trashed project,
and test isolation from the real Windows settings."""
import os
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

import tests
from database import Database, is_database_busy_error


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Database(os.path.join(self.tmp.name, "project_tracker.db"),
                           os.path.join(self.tmp.name, "attachments"))
        self.pid = self.db.add_project("Tower A")


class BusyDatabaseTests(_Base):
    def test_write_waits_for_another_users_write_instead_of_failing(self):
        item = self.db.add_item(self.pid, "Pipe", unit_cost=1)
        locked = threading.Event()

        def other_computer():
            conn = sqlite3.connect(self.db.db_path)
            conn.execute("BEGIN IMMEDIATE")      # holds the write lock
            conn.execute("UPDATE projects SET notes = 'x'")
            locked.set()
            time.sleep(1.5)
            conn.commit()
            conn.close()

        t = threading.Thread(target=other_computer)
        t.start()
        locked.wait(5)
        self.db.update_item(item, unit_cost=2)  # must wait, not raise
        t.join()
        self.assertEqual(self.db.get_item(item)["unit_cost"], 2)

    def test_busy_error_detection(self):
        self.assertTrue(is_database_busy_error(sqlite3.OperationalError("database is locked")))
        self.assertFalse(is_database_busy_error(sqlite3.OperationalError("no such table: x")))
        self.assertFalse(is_database_busy_error(ValueError("locked")))

    def test_busy_error_shows_a_message_instead_of_a_traceback(self):
        QApplication.instance() or QApplication([])
        import main
        saved = sys.excepthook
        self.addCleanup(setattr, sys, "excepthook", saved)
        main._install_excepthook()
        with patch("main.QMessageBox.warning") as warning, \
                patch.object(sys, "__excepthook__") as default_hook:
            sys.excepthook(sqlite3.OperationalError, sqlite3.OperationalError("database is locked"), None)
        warning.assert_called_once()
        default_hook.assert_not_called()


class RestoreInsideTrashedProjectTests(_Base):
    def test_item_returns_with_its_project(self):
        keep = [self.db.add_item(self.pid, n) for n in ("A", "B")]
        item = self.db.add_item(self.pid, "C")
        self.db.delete_item(item)
        self.db.delete_project(self.pid)

        self.assertFalse(self.db.restore_item(item))      # project is in the trash
        self.assertTrue(self.db.get_item(item)["is_deleted"])

        self.db.restore_project(self.pid)
        items = self.db.get_items(self.pid)
        self.assertEqual(sorted(it["id"] for it in items), sorted(keep + [item]))
        self.assertEqual(sorted(it["sort_order"] for it in items), [1, 2, 3])

    def test_normal_restore_still_works(self):
        item = self.db.add_item(self.pid, "A")
        self.db.delete_item(item)
        self.assertTrue(self.db.restore_item(item))
        self.assertFalse(self.db.get_item(item)["is_deleted"])


class SettingsIsolationTests(unittest.TestCase):
    def test_app_settings_go_to_a_temporary_file_during_tests(self):
        settings = QSettings("ProjectTracker", "MainWindow")
        self.assertEqual(settings.format(), QSettings.IniFormat)
        self.assertTrue(os.path.normcase(settings.fileName()).startswith(
            os.path.normcase(tests.TEST_SETTINGS_DIR)))

    def test_explicit_file_settings_are_untouched(self):
        path = os.path.join(tempfile.mkdtemp(), "ui.ini")
        self.assertEqual(os.path.normcase(QSettings(path, QSettings.IniFormat).fileName()),
                         os.path.normcase(path))


if __name__ == "__main__":
    unittest.main()
