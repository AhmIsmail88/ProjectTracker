# -*- coding: utf-8 -*-
"""Automatic backups (once/day, pruning, consistent snapshot) and the
config.json preference store (round trip + unwritable-path tolerance)."""
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backup
import config


class TestAutoBackup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pt_bk_")
        self.data_dir = os.path.join(self.tmp, "data")
        os.makedirs(self.data_dir)
        self.db_path = os.path.join(self.data_dir, "project_tracker.db")
        con = sqlite3.connect(self.db_path)
        con.execute("CREATE TABLE t (x INTEGER)")
        con.execute("INSERT INTO t VALUES (1)")
        con.commit()
        con.close()

    def test_creates_one_backup_per_day(self):
        first = backup.maybe_create_auto_backup(self.db_path, self.data_dir)
        self.assertIsNotNone(first)
        self.assertTrue(os.path.exists(first))
        second = backup.maybe_create_auto_backup(self.db_path, self.data_dir)
        self.assertIsNone(second)  # same day -> no duplicate

    def test_backup_is_a_valid_database(self):
        dest = backup.maybe_create_auto_backup(self.db_path, self.data_dir)
        con = sqlite3.connect(dest)
        try:
            self.assertEqual(con.execute("SELECT x FROM t").fetchone()[0], 1)
        finally:
            con.close()

    def test_no_db_means_no_backup(self):
        self.assertIsNone(
            backup.maybe_create_auto_backup(
                os.path.join(self.tmp, "missing.db"), self.data_dir))

    def test_prune_keeps_most_recent(self):
        bdir = backup.backups_dir_for(self.data_dir)
        os.makedirs(bdir, exist_ok=True)
        made = []
        for day in range(1, 7):
            p = os.path.join(bdir, f"project_tracker_2020-01-{day:02d}_000000.db")
            with open(p, "w") as f:
                f.write("x")
            made.append((datetime(2020, 1, day), p))
        with mock.patch.object(backup, "MAX_AUTO_BACKUPS", 3):
            backup._prune_old_backups(bdir, made)
        remaining = sorted(os.listdir(bdir))
        self.assertEqual(len(remaining), 3)
        self.assertIn("project_tracker_2020-01-06_000000.db", remaining)
        self.assertNotIn("project_tracker_2020-01-01_000000.db", remaining)

    def test_last_backup_datetime(self):
        self.assertIsNone(backup.last_backup_datetime(self.data_dir))
        backup.maybe_create_auto_backup(self.db_path, self.data_dir)
        self.assertIsNotNone(backup.last_backup_datetime(self.data_dir))


class TestConfigStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pt_cfg_")
        self._old_path = config.CONFIG_PATH
        config.CONFIG_PATH = os.path.join(self.tmp, "config.json")

    def tearDown(self):
        config.CONFIG_PATH = self._old_path

    def test_round_trip(self):
        existing_dir = self.tmp  # load_data_dir() only returns real dirs
        config.save_data_dir(existing_dir)
        config.save_last_project_id(42)
        config.save_table_layout("items_table", "abc123==")
        self.assertEqual(config.load_data_dir(), existing_dir)
        self.assertEqual(config.load_last_project_id(), 42)
        self.assertEqual(config.load_table_layout("items_table"), "abc123==")
        config.clear_table_layout("items_table")
        self.assertIsNone(config.load_table_layout("items_table"))

    def test_missing_file_returns_empty(self):
        self.assertIsNone(config.load_data_dir())
        self.assertIsNone(config.load_last_project_id())

    def test_unwritable_path_does_not_raise(self):
        # Point CONFIG_PATH at a DIRECTORY: writing must be tolerated
        # (logged, not raised) so a read-only install location never
        # crashes the app on save.
        config.CONFIG_PATH = self.tmp  # a directory, not a file
        try:
            config.save_data_dir("D:/Anywhere")
        except OSError as exc:
            self.fail(f"_save_config raised on unwritable path: {exc}")
        # persisting failed gracefully: nothing is remembered for the next
        # run, but the app did not crash
        self.assertIsNone(config.load_data_dir())
        config.CONFIG_PATH = os.path.join(self.tmp, "config.json")




class TestCompanyLogo(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp(prefix="pt_logo_")

    def test_set_get_remove_logo(self):
        import config as config_mod
        src = os.path.join(self.tmp, "logo.png")
        with open(src, "wb") as f:
            f.write(b"\x89PNG fake bytes")
        dest = os.path.join(self.tmp, "company_logo.png")
        with mock.patch.object(config_mod, "APP_DIR", self.tmp):
            self.assertTrue(config_mod.set_company_logo(src))
            self.assertEqual(config_mod.logo_path(), dest)
            self.assertTrue(os.path.exists(dest))
            config_mod.remove_company_logo()
            self.assertIsNone(config_mod.logo_path())

    def test_bad_source_returns_false(self):
        import config as config_mod
        with mock.patch.object(config_mod, "APP_DIR", self.tmp):
            self.assertFalse(config_mod.set_company_logo(os.path.join(self.tmp, "missing.png")))


class TestChatFormatting(unittest.TestCase):
    def test_markdown_bold_and_tables(self):
        from ui.ai_page import _format_chat_html
        raw = "**Bold part** and `x`\n| A | B |\n|---|---|\n| 1 | 2 |"
        out = _format_chat_html(raw)
        self.assertIn("<b>Bold part</b>", out)
        self.assertIn("<code>x</code>", out)
        self.assertNotIn("|---|", out)
        self.assertIn("A \u2014 B", out)
        self.assertIn("1 \u2014 2", out)

    def test_html_escaped_before_markdown(self):
        from ui.ai_page import _format_chat_html
        out = _format_chat_html("<b>&amp;")
        self.assertIn("&lt;b&gt;", out)
        self.assertNotIn("<b>&", out)

    def test_direction_detection(self):
        from ui.ai_page import _is_mostly_arabic
        self.assertTrue(_is_mostly_arabic("\u0645\u0631\u062d\u0628\u0627 \u0628\u0643"))
        self.assertFalse(_is_mostly_arabic("mostly english words here"))


if __name__ == "__main__":
    unittest.main()
