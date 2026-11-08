"""Accounts / session / permission tests for the user layer (phase 1)."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
from PySide6.QtCore import QSettings, QCoreApplication, QEvent

import auth
import config
import i18n
import main
from database import Database
from ui.login_dialog import LoginDialog, _login_language


class PasswordHashingTests(unittest.TestCase):
    def test_hash_and_verify(self):
        salt, digest = auth.hash_password("Secret123")
        self.assertNotEqual(salt, "")
        self.assertNotIn("Secret123", digest)
        self.assertTrue(auth.verify_password("Secret123", salt, digest))
        self.assertFalse(auth.verify_password("secret123", salt, digest))
        self.assertFalse(auth.verify_password("", salt, digest))

    def test_salt_is_random(self):
        salt1, digest1 = auth.hash_password("x")
        salt2, digest2 = auth.hash_password("x")
        self.assertNotEqual(salt1, salt2)
        self.assertNotEqual(digest1, digest2)


class UserStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Database(os.path.join(self.tmp.name, "db.sqlite"), os.path.join(self.tmp.name, "att"))

    def test_user_crud_and_verify(self):
        user_id = self.db.add_user("Ahmed", "pw1", role="manager", display_name="Ahmed")
        self.assertEqual(self.db.count_users(), 1)
        user = self.db.get_user(user_id)
        self.assertEqual(user["role"], "manager")
        self.assertEqual(user["username"], "Ahmed")
        self.assertNotIn("pw1", user["password_hash"])

        with self.assertRaises(ValueError):
            self.db.add_user("ahmed", "pw2")  # case-insensitive duplicate

        self.assertIsNotNone(self.db.verify_user("AHMED", "pw1"))
        self.assertIsNone(self.db.verify_user("Ahmed", "wrong"))

        self.db.set_password(user_id, "pw3")
        self.assertIsNone(self.db.verify_user("Ahmed", "pw1"))
        self.assertIsNotNone(self.db.verify_user("Ahmed", "pw3"))

        self.db.update_user(user_id, is_active=0)
        self.assertIsNone(self.db.verify_user("Ahmed", "pw3"))
        self.db.update_user(user_id, is_active=1, username="Ahmed2", role="user")
        self.assertIsNotNone(self.db.get_user_by_username("ahmed2"))
        self.assertEqual(self.db.get_user(user_id)["role"], "user")

        self.db.add_user("Sara", "pw", role="user")
        with self.assertRaises(ValueError):
            self.db.update_user(user_id, username="sara")

    def test_project_assignment(self):
        engineer = self.db.add_user("eng", "pw", role="user")
        project = self.db.add_project("P1")
        self.assertIsNone(self.db.get_project(project)["assigned_user_id"])
        self.db.set_project_assignee(project, engineer)
        self.assertEqual(self.db.get_project(project)["assigned_user_id"], engineer)

    def test_migration_adds_users_table_and_assignee_column(self):
        path = os.path.join(self.tmp.name, "old.sqlite")
        conn = sqlite3.connect(path)
        conn.execute("""
            CREATE TABLE projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                location TEXT,
                contractor TEXT,
                project_number TEXT,
                currency TEXT DEFAULT 'SAR',
                notes TEXT,
                created_date TEXT
            )
        """)
        conn.commit()
        conn.close()
        db = Database(path, os.path.join(self.tmp.name, "att2"))
        project_id = db.add_project("Old DB project")
        row = db.get_project(project_id)
        self.assertIn("assigned_user_id", row.keys())
        self.assertIsNone(row["assigned_user_id"])
        self.assertEqual(db.count_users(), 0)


class PermissionMatrixTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(auth.logout)
        self.db = Database(os.path.join(self.tmp.name, "db.sqlite"), os.path.join(self.tmp.name, "att"))
        self.manager = self.db.add_user("boss", "pw", role="manager")
        self.engineer = self.db.add_user("eng", "pw", role="user")
        self.other = self.db.add_user("other", "pw", role="user")
        self.assigned = self.db.add_project("Assigned project")
        self.unassigned = self.db.add_project("Unassigned project")
        self.db.set_project_assignee(self.assigned, self.engineer)

    def test_matrix(self):
        auth.logout()
        self.assertFalse(auth.can_edit_project(self.db, self.assigned))
        self.assertFalse(auth.is_manager())
        self.assertFalse(auth.can_manage_projects())
        self.assertFalse(auth.can_manage_users())

        auth.login(self.db.get_user(self.manager), self.db)
        self.assertTrue(auth.is_manager())
        self.assertTrue(auth.can_manage_projects())
        self.assertTrue(auth.can_manage_users())
        self.assertTrue(auth.can_edit_project(self.db, self.assigned))
        self.assertTrue(auth.can_edit_project(self.db, self.unassigned))

        auth.login(self.db.get_user(self.engineer), self.db)
        self.assertFalse(auth.is_manager())
        self.assertTrue(auth.can_edit_project(self.db, self.assigned))
        self.assertFalse(auth.can_edit_project(self.db, self.unassigned))

        auth.login(self.db.get_user(self.other), self.db)
        self.assertFalse(auth.can_edit_project(self.db, self.assigned))
        self.assertFalse(auth.can_edit_project(self.db, self.unassigned))
        self.assertFalse(auth.can_edit_project(self.db, None))


class LoginDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(auth.logout)
        ctx = patch.object(config, "CONFIG_PATH", os.path.join(self.tmp.name, "config.json"))
        ctx.start()
        self.addCleanup(ctx.stop)
        self.db = Database(os.path.join(self.tmp.name, "db.sqlite"), os.path.join(self.tmp.name, "att"))

    def test_first_run_dialog_creates_manager(self):
        dialog = LoginDialog(self.db, first_run=True)
        dialog.username_edit.setText("admin")
        dialog.password_edit.setText("pw123")
        dialog.confirm_edit.setText("pw123")
        with patch("ui.login_dialog.QMessageBox.warning"):
            dialog._on_accept()
        self.assertIsNotNone(auth.current_user())
        self.assertEqual(auth.current_user()["role"], "manager")
        self.assertEqual(self.db.count_users(), 1)

    def test_login_wrong_then_correct_password(self):
        self.db.add_user("admin", "pw123", role="manager")
        dialog = LoginDialog(self.db, first_run=False)
        dialog.username_edit.setText("admin")
        dialog.password_edit.setText("wrong")
        with patch("ui.login_dialog.QMessageBox.warning"):
            dialog._on_accept()
        self.assertIsNone(auth.current_user())
        dialog.password_edit.setText("pw123")
        with patch("ui.login_dialog.QMessageBox.warning"):
            dialog._on_accept()
        self.assertIsNotNone(auth.current_user())
        self.assertEqual(auth.current_user()["username"], "admin")


if __name__ == "__main__":
    unittest.main()

class ProjectsUsersMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(auth.logout)
        cfg = patch.object(config, "CONFIG_PATH", os.path.join(self.tmp.name, "config.json"))
        cfg.start()
        self.addCleanup(cfg.stop)
        self.addCleanup(i18n.set_language, i18n.get_language())
        i18n.set_language("en")
        self.db = Database(os.path.join(self.tmp.name, "db.sqlite"), os.path.join(self.tmp.name, "att"))

    def _users_actions(self, page):
        return [a for a in page.more_btn.menu().actions() if a.text().startswith("Users")]

    def test_users_menu_entry_visible_only_for_managers(self):
        from ui.projects_page import ProjectsPage
        from ui.widgets import UndoBar
        manager = self.db.add_user("boss", "pw", role="manager")
        engineer = self.db.add_user("eng", "pw", role="user")

        auth.login(self.db.get_user(manager), self.db)
        page = ProjectsPage(self.db, UndoBar())
        self.addCleanup(page.close)
        actions = self._users_actions(page)
        self.assertEqual(len(actions), 1)
        self.assertTrue(actions[0].isVisible())

        auth.login(self.db.get_user(engineer), self.db)
        page2 = ProjectsPage(self.db, UndoBar())
        self.addCleanup(page2.close)
        actions2 = self._users_actions(page2)
        self.assertEqual(len(actions2), 1)
        self.assertFalse(actions2[0].isVisible())

class LoginLanguageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(auth.logout)
        self.addCleanup(i18n.set_language, i18n.get_language())
        direction = self.app.layoutDirection()
        self.addCleanup(self.app.setLayoutDirection, direction)
        self.settings = QSettings(os.path.join(self.tmp.name, "ui.ini"), QSettings.IniFormat)
        cfg = patch.object(config, "CONFIG_PATH", os.path.join(self.tmp.name, "config.json"))
        cfg.start()
        self.addCleanup(cfg.stop)
        settings_patch = patch("ui.login_dialog.QSettings", lambda *args, **kwargs: self.settings)
        settings_patch.start()
        self.addCleanup(settings_patch.stop)
        self.db = Database(os.path.join(self.tmp.name, "db.sqlite"), os.path.join(self.tmp.name, "att"))
        i18n.set_language("en")

    def test_login_language_defaults_to_english(self):
        self.assertEqual(_login_language(), "en")
        self.settings.setValue("language", "ar")
        self.assertEqual(_login_language(), "ar")

    def test_switch_language_updates_texts_and_persists(self):
        dialog = LoginDialog(self.db, first_run=True)
        self.addCleanup(dialog.deleteLater)
        english_text = dialog.username_label.text()
        dialog._switch_language()
        self.assertEqual(i18n.get_language(), "ar")
        self.assertEqual(self.settings.value("language"), "ar")
        self.assertNotEqual(dialog.username_label.text(), english_text)
        dialog._switch_language()
        self.assertEqual(i18n.get_language(), "en")
        self.assertEqual(self.settings.value("language"), "en")
        self.assertEqual(dialog.username_label.text(), english_text)


class SignOutFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        self.settings = QSettings(os.path.join(self.root, "ui.ini"), QSettings.IniFormat)
        self.settings.setValue("language", "en")
        for target, value in (("config.CONFIG_PATH", os.path.join(self.root, "config.json")),
                              ("main.QSettings", lambda *args, **kwargs: self.settings),
                              ("ui.dashboard_page.QSettings", lambda *args, **kwargs: self.settings)):
            context = patch(target, value)
            context.start()
            self.addCleanup(context.stop)
        self.addCleanup(auth.logout)
        self.addCleanup(i18n.set_language, i18n.get_language())
        direction = self.app.layoutDirection()
        self.addCleanup(self.app.setLayoutDirection, direction)
        i18n.set_language("en")
        self.db = Database(os.path.join(self.root, "db.sqlite"), os.path.join(self.root, "att"))
        self.manager = self.db.add_user("boss", "pw", role="manager")
        self.engineer = self.db.add_user("eng", "pw", role="user")
        auth.login(self.db.get_user(self.manager), self.db)
        self.window = main.MainWindow(self.db, self.root)
        self.addCleanup(self._dispose_window)

    def _dispose_window(self):
        self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_sign_out_switches_user_and_rebuilds_ui(self):
        old_page = self.window.projects_page
        db = self.db
        engineer_id = self.engineer

        class FakeLoginDialog:
            def __init__(self, *args, **kwargs):
                pass

            def exec(self):
                auth.login(db.get_user(engineer_id), db)
                return QDialog.Accepted

        with patch("ui.login_dialog.LoginDialog", FakeLoginDialog), \
                patch("main.QMessageBox.question", return_value=QMessageBox.Yes):
            self.window._sign_out()

        self.assertIsNotNone(auth.current_user())
        self.assertEqual(auth.current_user()["username"], "eng")
        self.assertIsNot(self.window.projects_page, old_page)
        actions = [a for a in self.window.projects_page.more_btn.menu().actions()
                   if a.text().startswith("Users")]
        self.assertEqual(len(actions), 1)
        self.assertFalse(actions[0].isVisible())


class AccountAdminTests(unittest.TestCase):
    """Users screen: bulk project assignment and account deletion."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        cfg = patch.object(config, "CONFIG_PATH", os.path.join(self.tmp.name, "config.json"))
        cfg.start()
        self.addCleanup(cfg.stop)
        lang = i18n.get_language()
        self.addCleanup(i18n.set_language, lang)
        i18n.set_language("en")
        auth.logout()
        self.addCleanup(auth.logout)
        self.db = Database(os.path.join(self.tmp.name, "db.sqlite"), os.path.join(self.tmp.name, "att"))
        self.manager = self.db.add_user("boss", "pw", role="manager")
        self.engineer = self.db.add_user("eng", "pw", role="user")
        self.p1 = self.db.add_project("P One")
        self.p2 = self.db.add_project("P Two")

    def test_assign_projects_replaces_previous_set(self):
        self.db.assign_projects_to_user(self.engineer, [self.p1, self.p2])
        assigned = {p["id"] for p in self.db.get_projects() if p["assigned_user_id"] == self.engineer}
        self.assertEqual(assigned, {self.p1, self.p2})
        self.db.assign_projects_to_user(self.engineer, [self.p2])
        rows = {p["id"]: p for p in self.db.get_projects()}
        self.assertIsNone(rows[self.p1]["assigned_user_id"])
        self.assertEqual(rows[self.p2]["assigned_user_id"], self.engineer)

    def test_delete_user_unassigns_projects(self):
        self.db.assign_projects_to_user(self.engineer, [self.p1])
        self.db.delete_user(self.engineer)
        self.assertIsNone(self.db.get_user(self.engineer))
        rows = {p["id"]: p for p in self.db.get_projects()}
        self.assertIsNone(rows[self.p1]["assigned_user_id"])

    def test_last_active_manager_cannot_be_deleted(self):
        with self.assertRaises(ValueError):
            self.db.delete_user(self.manager)
        self.assertIsNotNone(self.db.get_user(self.manager))

    def test_users_dialog_has_assign_and_delete(self):
        from ui.users_dialog import UsersDialog
        auth.login(self.db.get_user(self.manager), self.db)
        dialog = UsersDialog(None, self.db)
        self.addCleanup(dialog.deleteLater)
        self.assertEqual(dialog.table.columnCount(), 4)
        self.assertTrue(dialog.assign_btn.isEnabled())
        self.assertTrue(dialog.delete_btn.isEnabled())
        self.assertEqual(dialog.table.rowCount(), 2)
        self.db.assign_projects_to_user(self.engineer, [self.p1, self.p2])
        dialog._reload()
        row = next(r for r in range(dialog.table.rowCount())
                   if dialog.table.item(r, 0).text() == "eng")
        self.assertEqual(dialog.table.item(row, 2).text(), "2")

    def test_assign_dialog_checks_current_assignment(self):
        from ui.users_dialog import _AssignProjectsDialog
        self.db.assign_projects_to_user(self.engineer, [self.p2])
        dialog = _AssignProjectsDialog(None, self.db, self.db.get_user(self.engineer))
        self.addCleanup(dialog.deleteLater)
        self.assertEqual(dialog._checked_ids(), [self.p2])
        self.assertEqual(dialog.list_widget.count(), 2)
