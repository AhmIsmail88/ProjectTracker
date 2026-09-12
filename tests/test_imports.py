# -*- coding: utf-8 -*-
"""Smoke: every module imports cleanly (catches broken imports / refs)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MODULES = [
    "constants", "i18n", "app_paths", "config", "backup", "database",
    "ai.openrouter_client",
    "export.excel_export", "export.pdf_export", "export.dashboard_pdf_export",
    "importers.excel_import",
    "ui.styles", "ui.widgets", "ui.table_utils", "ui.pie_chart",
    "ui.dialogs", "ui.bulk_edit_dialog", "ui.find_replace_dialog",
    "ui.global_search_dialog", "ui.activity_widget", "ui.projects_page",
    "ui.items_page", "ui.suppliers_page", "ui.dashboard_page", "ui.ai_page",
]


class TestImports(unittest.TestCase):
    def test_all_modules_import(self):
        import importlib
        for name in MODULES:
            with self.subTest(module=name):
                importlib.import_module(name)

    def test_version_bumped(self):
        import constants
        self.assertEqual(constants.APP_VERSION, "2.31")

    def test_i18n_has_menu_keys(self):
        import i18n
        for key in ("menu_file", "menu_backup_now", "menu_keyboard_shortcuts",
                    "data_folder", "last_auto_backup", "never_yet"):
            self.assertIn(key, i18n.STRINGS)
            self.assertIn("ar", i18n.STRINGS[key])


if __name__ == "__main__":
    unittest.main()
