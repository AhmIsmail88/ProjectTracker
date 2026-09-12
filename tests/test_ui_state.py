# -*- coding: utf-8 -*-
"""Regression: a saved items-table layout that hides # / Item Name (the
withdrawn frozen-columns build could save such a state) must never be
able to hide those two columns on the next launch."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication, QTableWidget, QHeaderView
    from PySide6.QtCore import Qt
    _HAS_QT = True
except ImportError:  # pragma: no cover
    _HAS_QT = False


@unittest.skipUnless(_HAS_QT, "PySide6 not available")
class TestPoisonedLayoutSelfHeal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_hidden_identity_columns_are_forced_visible(self):
        import config as app_config
        from ui.items_page import TrackerPage
        from ui.widgets import UndoBar
        from database import Database

        tmp = tempfile.mkdtemp(prefix="pt_layout_")
        app_config.CONFIG_PATH = os.path.join(tmp, "config.json")

        # Build a "poisoned" saved layout: # and Item Name hidden.
        probe = QTableWidget()
        probe.setColumnCount(15)
        probe.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        probe.setColumnHidden(0, True)
        probe.setColumnHidden(1, True)
        state_b64 = bytes(probe.horizontalHeader().saveState().toBase64()).decode("ascii")
        app_config.save_table_layout("items_table", state_b64)

        db = Database(os.path.join(tmp, "db.sqlite"), os.path.join(tmp, "att"))
        pid = db.add_project("Layout Test")
        db.add_item(pid, item_name="Pump", total_quantity=1)
        tracker = TrackerPage(db, UndoBar())
        tracker.open_project(pid)

        self.assertFalse(tracker.items_table.isColumnHidden(0), "# column was left hidden")
        self.assertFalse(tracker.items_table.isColumnHidden(1), "Item Name column was left hidden")
        # and the poisoned layout was discarded
        self.assertIsNone(app_config.load_table_layout("items_table"))


if __name__ == "__main__":
    unittest.main()
