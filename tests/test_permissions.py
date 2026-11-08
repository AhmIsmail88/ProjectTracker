import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QAbstractItemView, QApplication

import auth
import config
import i18n
from database import Database
from ui.attachments_dialog import AttachmentsDialog
from ui.items_page import DeletedItemsDialog, TrackerPage
from ui.projects_page import ProjectsPage
from ui.schedule_page import SchedulePage
from ui.widgets import UndoBar


class _FakeItemDialog:
    """Minimal stand-in for ItemDialog that accepts without opening a window."""

    def __init__(self, *args, **kwargs):
        pass

    def exec(self):
        return 1

    def get_data(self):
        return {"item_name": "Engineer item"}


class PermissionEnforcementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        context = patch.object(config, "CONFIG_PATH", os.path.join(self.tmp.name, "config.json"))
        context.start()
        self.addCleanup(context.stop)
        lang = i18n.get_language()
        self.addCleanup(i18n.set_language, lang)
        i18n.set_language("en")
        auth.logout()
        self.addCleanup(auth.logout)
        self.db = Database(os.path.join(self.tmp.name, "db.sqlite"),
                           os.path.join(self.tmp.name, "attachments"))
        self.manager = self.db.add_user("boss", "pw", role="manager")
        self.engineer = self.db.add_user("eng", "pw", role="user")
        self.p_assigned = self.db.add_project("Assigned")
        self.p_other = self.db.add_project("Not assigned")
        self.db.set_project_assignee(self.p_assigned, self.engineer)
        self.item_a = self.db.add_item(self.p_assigned, "Pump", total_quantity=2)
        self.item_o = self.db.add_item(self.p_other, "Valve", total_quantity=1)
        self.pages = []
        self.addCleanup(self._dispose)

    def _dispose(self):
        for page in self.pages:
            page.close()
            page.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def login(self, user_id):
        auth.login(self.db.get_user(user_id), self.db)

    def tracker(self, project_id):
        page = TrackerPage(self.db, UndoBar())
        self.pages.append(page)
        page.open_project(project_id)
        page.resize(1400, 900)
        page.show()
        self.app.processEvents()
        return page

    # ------------------------------------------------------------------
    # items screen
    # ------------------------------------------------------------------
    def test_engineer_edits_assigned_project_only(self):
        self.login(self.engineer)
        page = self.tracker(self.p_assigned)
        self.assertTrue(page._can_edit())
        self.assertTrue(page.add_btn.isEnabled())
        self.assertTrue(page.edit_btn.isEnabled())
        self.assertFalse(page.readonly_label.isVisible())
        before = len(self.db.get_items(self.p_assigned))
        with patch("ui.items_page.ItemDialog", _FakeItemDialog):
            page._add_item()
        self.assertEqual(len(self.db.get_items(self.p_assigned)), before + 1)

    def test_engineer_blocked_on_unassigned_project(self):
        self.login(self.engineer)
        page = self.tracker(self.p_other)
        self.assertFalse(page._can_edit())
        self.assertFalse(page.add_btn.isEnabled())
        self.assertFalse(page.edit_btn.isEnabled())
        self.assertTrue(page.attach_btn.isEnabled())
        self.assertTrue(page.readonly_label.isVisible())
        self.assertEqual(page.items_table.editTriggers(),
                         QAbstractItemView.NoEditTriggers)
        before = len(self.db.get_items(self.p_other))
        page._add_item()
        page._delete_item()
        page._duplicate_item()
        self.assertEqual(len(self.db.get_items(self.p_other)), before)
        self.assertFalse(self.db.get_item(self.item_o)["is_deleted"])

    def test_manager_edits_any_project(self):
        self.login(self.manager)
        page = self.tracker(self.p_other)
        self.assertTrue(page._can_edit())
        self.assertTrue(page.add_btn.isEnabled())
        self.assertFalse(page.readonly_label.isVisible())
        before = len(self.db.get_items(self.p_other))
        with patch("ui.items_page.ItemDialog", _FakeItemDialog):
            page._add_item()
        self.assertEqual(len(self.db.get_items(self.p_other)), before + 1)

    def test_signed_out_is_read_only(self):
        page = self.tracker(self.p_assigned)
        self.assertFalse(page._can_edit())
        self.assertFalse(page.add_btn.isEnabled())

    # ------------------------------------------------------------------
    # projects screen
    # ------------------------------------------------------------------
    def test_engineer_cannot_manage_projects(self):
        self.login(self.engineer)
        page = ProjectsPage(self.db, UndoBar())
        self.pages.append(page)
        page.select_project(self.p_assigned)
        self.assertFalse(page.add_btn.isEnabled())
        edit_action, history_action, delete_action = (page.project_actions[0],
                                                      page.project_actions[1],
                                                      page.project_actions[2])
        self.assertFalse(edit_action.isEnabled())
        self.assertTrue(history_action.isEnabled())
        self.assertFalse(delete_action.isEnabled())
        self.assertFalse(page.groups_action.isEnabled())
        self.assertFalse(page.import_action.isEnabled())
        self.assertFalse(page.trash_action.isEnabled())
        before = len(self.db.get_projects())
        page._add_project()
        self.assertEqual(len(self.db.get_projects()), before)

    def test_manager_project_actions_enabled(self):
        self.login(self.manager)
        page = ProjectsPage(self.db, UndoBar())
        self.pages.append(page)
        page.select_project(self.p_assigned)
        self.assertTrue(page.add_btn.isEnabled())
        self.assertTrue(page.project_actions[0].isEnabled())
        self.assertTrue(page.project_actions[1].isEnabled())
        self.assertTrue(page.project_actions[2].isEnabled())
        self.assertTrue(page.groups_action.isEnabled())
        self.assertTrue(page.import_action.isEnabled())
        self.assertTrue(page.trash_action.isEnabled())

    # ------------------------------------------------------------------
    # schedule screen
    # ------------------------------------------------------------------
    def test_schedule_gating_follows_assignment(self):
        self.login(self.engineer)
        page = SchedulePage(self.db)
        self.pages.append(page)
        page.open_project(self.p_other)
        self.assertFalse(page.add_btn.isEnabled())
        self.assertFalse(page._can_edit())
        before = len(list(self.db.get_schedule_activities(self.p_other)))
        page._add_activity()
        self.assertEqual(len(list(self.db.get_schedule_activities(self.p_other))), before)
        page.open_project(self.p_assigned)
        self.assertTrue(page.add_btn.isEnabled())
        self.assertTrue(page._can_edit())
        self.assertTrue(page.export_btn.isEnabled())

    # ------------------------------------------------------------------
    # dialogs
    # ------------------------------------------------------------------
    def _attach_and_select(self, dlg):
        import os
        path = os.path.join(self.tmp.name, "sample.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("sample")
        self.db.add_attachment(self.item_o, "PR", path)
        dlg._reload_list()
        group = dlg.list_widget.topLevelItem(0)
        file_item = group.child(0) if group is not None and group.childCount() else None
        self.assertIsNotNone(file_item)
        dlg.list_widget.setCurrentItem(file_item)

    def test_attachments_dialog_read_only_mode(self):
        dlg = AttachmentsDialog(None, self.db, self.item_o, "Valve", read_only=True)
        self.addCleanup(dlg.deleteLater)
        self.assertFalse(dlg.upload_btn.isEnabled())
        self.assertFalse(dlg.delete_btn.isEnabled())
        self.assertFalse(dlg.category_combo.isEnabled())
        self.assertTrue(dlg.filter_combo.isEnabled())
        self._attach_and_select(dlg)
        self.assertTrue(dlg.open_btn.isEnabled())
        self.assertFalse(dlg.delete_btn.isEnabled())

    def test_attachments_dialog_normal_mode(self):
        dlg = AttachmentsDialog(None, self.db, self.item_o, "Valve")
        self.addCleanup(dlg.deleteLater)
        self.assertTrue(dlg.upload_btn.isEnabled())
        self.assertTrue(dlg.category_combo.isEnabled())
        self._attach_and_select(dlg)
        self.assertTrue(dlg.delete_btn.isEnabled())
        self.assertTrue(dlg.open_btn.isEnabled())

    def test_deleted_items_dialog_read_only_mode(self):
        self.db.delete_item(self.item_a)
        dlg = DeletedItemsDialog(None, self.db, self.p_assigned, read_only=True)
        self.addCleanup(dlg.deleteLater)
        self.assertFalse(dlg.restore_btn.isEnabled())
        self.assertFalse(dlg.purge_btn.isEnabled())
        self.assertTrue(self.db.get_item(self.item_a)["is_deleted"])
        dlg._restore_selected()
        self.assertTrue(self.db.get_item(self.item_a)["is_deleted"])


if __name__ == "__main__":
    unittest.main()
