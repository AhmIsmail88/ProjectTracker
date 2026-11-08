"""Account isolation, revocation, and cross-project import regressions."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import unittest
from unittest.mock import patch

import openpyxl
from PySide6.QtCore import QCoreApplication, QEvent, QSettings
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

import auth
import config
import i18n
import main
from database import Database
from importers.excel_import import import_cost_updates_from_excel
from ui.bulk_edit_dialog import BulkEditDialog
from ui.attachments_dialog import AttachmentsDialog
from ui.dashboard_page import DashboardPage
from ui.projects_page import TrashDialog
from ui.login_dialog import LoginDialog
from ui.users_dialog import _UserEditDialog, _PasswordDialog, _AssignProjectsDialog


class AuthRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        self.addCleanup(i18n.set_language, i18n.get_language())
        i18n.set_language("en")
        self.settings = QSettings(os.path.join(self.root, "ui.ini"), QSettings.IniFormat)
        for target, value in (
            ("config.CONFIG_PATH", os.path.join(self.root, "config.json")),
            ("main.QSettings", lambda *a, **k: self.settings),
            ("ui.dashboard_page.QSettings", lambda *a, **k: self.settings),
            ("ui.login_dialog.QSettings", lambda *a, **k: self.settings),
        ):
            context = patch(target, value)
            context.start()
            self.addCleanup(context.stop)
        self.db = Database(config.db_path_for(self.root), config.attachments_dir_for(self.root))
        self.manager = self.db.add_user("manager", "manager-password", role="manager")
        self.engineer = self.db.add_user("engineer", "engineer-password")
        self.assigned = self.db.add_project("Assigned")
        self.other = self.db.add_project("Other")
        self.db.set_project_assignee(self.assigned, self.engineer)
        self.item_a = self.db.add_item(self.assigned, "A", unit_cost=10)
        self.item_b = self.db.add_item(self.other, "B", unit_cost=20)
        auth.logout()
        self.addCleanup(auth.logout)
        self.widgets = []
        self.addCleanup(self._dispose)

    def _dispose(self):
        for widget in reversed(self.widgets):
            widget.close()
            widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def keep(self, widget):
        self.widgets.append(widget)
        return widget

    def login(self, user_id):
        auth.login(self.db.get_user(user_id), self.db)

    def cost_file(self):
        path = os.path.join(self.root, "costs.xlsx")
        wb = openpyxl.Workbook()
        wb.active.append(["Item ID", "Unit Cost"])
        wb.active.append([self.item_a, 100])
        wb.active.append([self.item_b, 200])
        wb.save(path)
        wb.close()
        return path

    def target_db(self):
        directory = os.path.join(self.root, "target")
        os.makedirs(directory, exist_ok=True)
        db = Database(config.db_path_for(directory), config.attachments_dir_for(directory))
        # Same numeric id as the source manager, different account and password.
        db.add_user("target-engineer", "target-password")
        project = db.add_project("Target")
        return directory, db, project

    def test_session_cannot_authorize_another_database_with_same_user_id(self):
        _, target, project = self.target_db()
        self.login(self.manager)
        self.assertFalse(auth.is_manager(target))
        self.assertFalse(auth.can_edit_project(target, project))

    def test_demotion_refreshes_rights_without_signing_out(self):
        self.login(self.manager)
        self.db.update_user(self.manager, role="user")
        self.assertFalse(auth.is_manager())
        self.assertFalse(auth.can_edit_project(self.db, self.other))
        self.db.set_project_assignee(self.assigned, self.manager)
        self.assertTrue(auth.can_edit_project(self.db, self.assigned))

    def test_disabled_engineer_cannot_edit_assigned_project(self):
        self.login(self.engineer)
        self.db.update_user(self.engineer, is_active=0)
        self.assertFalse(auth.can_edit_project(self.db, self.assigned))
        self.assertIsNone(auth.current_user())
        self.db.update_user(self.engineer, is_active=1)
        self.assertFalse(auth.can_edit_project(self.db, self.assigned))

    def test_deleted_account_loses_session(self):
        self.db.add_user("backup-manager", "pw", role="manager")
        self.login(self.manager)
        self.db.delete_user(self.manager)
        self.assertFalse(auth.is_manager())
        self.assertIsNone(auth.current_user())

    def test_password_reset_invalidates_existing_session(self):
        self.login(self.engineer)
        self.db.set_password(self.engineer, "replacement")
        self.assertFalse(auth.can_edit_project(self.db, self.assigned))

    def test_inactive_creation_is_saved_and_cannot_log_in(self):
        self.login(self.manager)
        dialog = self.keep(_UserEditDialog(None, self.db))
        dialog.username_edit.setText("inactive")
        dialog.password_edit.setText("password")
        dialog.confirm_edit.setText("password")
        dialog.active_check.setChecked(False)
        dialog._on_accept()
        self.assertEqual(dialog.result(), QDialog.Accepted)
        self.assertEqual(self.db.get_user_by_username("inactive")["is_active"], 0)
        self.assertIsNone(self.db.verify_user("inactive", "password"))

    def test_cost_import_engineer_only_changes_assigned_project(self):
        self.login(self.engineer)
        result = import_cost_updates_from_excel(self.db, self.cost_file())
        self.assertEqual((result["updated"], result["forbidden"]), (1, 1))
        self.assertEqual(self.db.get_item(self.item_a)["unit_cost"], 100)
        self.assertEqual(self.db.get_item(self.item_b)["unit_cost"], 20)

    def test_cost_import_manager_changes_both_projects(self):
        self.login(self.manager)
        result = import_cost_updates_from_excel(self.db, self.cost_file())
        self.assertEqual((result["updated"], result["forbidden"]), (2, 0))

    def test_dashboard_import_reports_forbidden_rows(self):
        self.login(self.engineer)
        page = self.keep(DashboardPage(self.db))
        path = self.cost_file()
        messages = []

        class Signal:
            def connect(self, callback):
                self.callback = callback

        class InlineWorker:
            def __init__(self, fn):
                self.fn = fn
                self.finished_ok = Signal()
                self.finished_err = Signal()

            def start(self):
                self.fn()
                self.finished_ok.callback()

        def capture_message(box):
            messages.append(box.text())
            return 0

        with patch("ui.dashboard_page.QFileDialog.getOpenFileName", return_value=(path, "")), \
                patch("ui.dashboard_page.ExportWorker", InlineWorker), \
                patch.object(DashboardPage, "_confirm_cost_changes", return_value=True), \
                patch("ui.dashboard_page.QMessageBox.exec", capture_message):
            page._import_cost_updates()
        self.assertEqual(self.db.get_item(self.item_a)["unit_cost"], 100)
        self.assertEqual(self.db.get_item(self.item_b)["unit_cost"], 20)
        self.assertEqual(len(messages), 1)
        self.assertIn("Skipped 1 item(s) because you do not have permission", messages[0])
        self.assertTrue(page.import_costs_btn.isEnabled())
        self.assertIsNone(page._cost_import_worker)

    def test_cost_import_without_session_changes_nothing(self):
        result = import_cost_updates_from_excel(self.db, self.cost_file())
        self.assertEqual((result["updated"], result["forbidden"]), (0, 2))
        self.assertEqual(self.db.get_item(self.item_a)["unit_cost"], 10)
        self.assertEqual(self.db.get_item(self.item_b)["unit_cost"], 20)

    def test_cost_import_rechecks_revocation_between_rows(self):
        self.login(self.manager)
        update = self.db.update_item

        def update_and_revoke(*args, **kwargs):
            update(*args, **kwargs)
            self.db.update_user(self.manager, is_active=0)

        with patch.object(self.db, "update_item", side_effect=update_and_revoke):
            result = import_cost_updates_from_excel(self.db, self.cost_file())
        self.assertEqual((result["updated"], result["forbidden"]), (1, 1))
        self.assertEqual(self.db.get_item(self.item_b)["unit_cost"], 20)

    def test_open_bulk_editor_cannot_save_after_reassignment(self):
        self.login(self.engineer)
        dialog = self.keep(BulkEditDialog(None, self.db, [self.item_a]))
        dialog.unit_check.setChecked(True)
        dialog.unit_edit.setText("forbidden-unit")
        before = self.db.get_item(self.item_a)["unit"]
        self.db.set_project_assignee(self.assigned, None)
        dialog._apply()
        self.assertEqual(self.db.get_item(self.item_a)["unit"], before)
        self.assertNotEqual(dialog.result(), QDialog.Accepted)

    def test_open_attachments_cannot_upload_after_disabling_account(self):
        self.login(self.engineer)
        dialog = self.keep(AttachmentsDialog(None, self.db, self.item_a, "A"))
        self.db.update_user(self.engineer, is_active=0)
        with patch("ui.attachments_dialog.QFileDialog.getOpenFileNames") as picker, \
                patch.object(self.db, "add_attachment") as save:
            dialog._upload_file()
        picker.assert_not_called()
        save.assert_not_called()

    def test_open_admin_dialogs_cannot_save_after_demotion(self):
        self.login(self.manager)
        user = self.db.get_user(self.engineer)
        edit = self.keep(_UserEditDialog(None, self.db, user))
        password = self.keep(_PasswordDialog(None, self.db, user))
        assignment = self.keep(_AssignProjectsDialog(None, self.db, user))
        edit.username_edit.setText("unauthorized-name")
        password.password_edit.setText("unauthorized-password")
        password.confirm_edit.setText("unauthorized-password")
        self.db.update_user(self.manager, role="user")
        with patch("ui.users_dialog.QMessageBox.warning"):
            for dialog in (edit, password, assignment):
                dialog._on_accept()
                self.assertNotEqual(dialog.result(), QDialog.Accepted)
        self.assertEqual(self.db.get_user(self.engineer)["username"], "engineer")
        self.assertIsNotNone(self.db.verify_user("engineer", "engineer-password"))

    def test_project_purge_rechecks_permissions_after_confirmation(self):
        self.login(self.manager)
        self.db.delete_project(self.other)
        dialog = self.keep(TrashDialog(None, self.db))
        dialog.list_widget.setCurrentRow(0)

        def confirm_after_demotion(*args):
            self.db.update_user(self.manager, role="user")
            return QMessageBox.Yes

        with patch("ui.projects_page.QMessageBox.question", side_effect=confirm_after_demotion), \
                patch.object(self.db, "purge_project") as purge:
            dialog._purge_selected()
        purge.assert_not_called()

    def test_cancel_folder_login_preserves_database_session_and_config(self):
        self.login(self.manager)
        window = self.keep(main.MainWindow(self.db, self.root))
        config.save_data_dir(self.root)
        directory, _, _ = self.target_db()
        old_page = window.projects_page
        with patch.object(LoginDialog, "exec", return_value=QDialog.Rejected):
            self.assertFalse(window._switch_to_data_dir(directory))
        self.assertIs(window.db, self.db)
        self.assertIs(window.projects_page, old_page)
        self.assertEqual(config.load_data_dir(), self.root)
        self.assertEqual(auth.current_user()["username"], "manager")
        self.assertTrue(auth.is_manager(self.db))

    def test_wrong_password_cannot_switch_database(self):
        self.login(self.manager)
        window = self.keep(main.MainWindow(self.db, self.root))
        directory, _, _ = self.target_db()

        def rejected_login(dialog):
            dialog.username_edit.setText("target-engineer")
            dialog.password_edit.setText("manager-password")
            dialog._on_accept()
            return dialog.result()

        with patch.object(LoginDialog, "exec", rejected_login), patch("ui.login_dialog.QMessageBox.warning"):
            self.assertFalse(window._switch_to_data_dir(directory))
        self.assertIs(window.db, self.db)
        self.assertTrue(auth.is_manager(self.db))

    def test_successful_switch_uses_target_accounts_and_rebuilds_permissions(self):
        self.login(self.manager)
        window = self.keep(main.MainWindow(self.db, self.root))
        directory, _, project = self.target_db()
        old_page = window.projects_page

        def accepted_login(dialog):
            self.assertFalse(dialog.establish_session)
            dialog.username_edit.setText("target-engineer")
            dialog.password_edit.setText("target-password")
            dialog._on_accept()
            self.assertEqual(auth.current_user()["username"], "manager")
            return dialog.result()

        with patch.object(LoginDialog, "exec", accepted_login):
            self.assertTrue(window._switch_to_data_dir(directory))
        self.assertEqual(auth.current_user()["username"], "target-engineer")
        self.assertFalse(auth.is_manager())
        self.assertFalse(auth.can_edit_project(window.db, project))
        self.assertIsNot(window.projects_page, old_page)
        self.assertEqual(config.load_data_dir(), directory)

    def test_empty_folder_requires_new_manager_setup(self):
        self.login(self.manager)
        window = self.keep(main.MainWindow(self.db, self.root))
        directory = os.path.join(self.root, "empty")
        os.makedirs(directory)

        def setup_manager(dialog):
            self.assertTrue(dialog.first_run)
            dialog.username_edit.setText("new-manager")
            dialog.password_edit.setText("new-password")
            dialog.confirm_edit.setText("new-password")
            dialog._on_accept()
            return dialog.result()

        with patch.object(LoginDialog, "exec", setup_manager):
            self.assertTrue(window._switch_to_data_dir(directory))
        self.assertEqual(auth.current_user()["username"], "new-manager")
        self.assertTrue(auth.is_manager(window.db))
        self.assertFalse(auth.is_manager(self.db))
