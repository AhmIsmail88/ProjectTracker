"""Exercise popup opening and commands through mouse events, then check SQLite."""
import gc
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QCoreApplication, QEvent, QTimer, Qt
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QInputDialog, QPushButton

import config
import auth
import i18n
from database import Database
from ui.bulk_edit_dialog import BulkEditDialog
from ui.find_replace_dialog import FindReplaceDialog
from ui.icons import StandardIconFilter
from ui.items_page import TrackerPage, COL_ITEM_NAME
from ui.widgets import UndoBar


class ItemActionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        cfg = patch.object(config, "CONFIG_PATH", os.path.join(self.tmp.name, "config.json"))
        cfg.start()
        self.addCleanup(cfg.stop)
        self.addCleanup(i18n.set_language, i18n.get_language())
        i18n.set_language("en")
        self.db = Database(os.path.join(self.tmp.name, "test.db"), os.path.join(self.tmp.name, "files"))
        self.project = self.db.add_project("Actions")
        self.ids = [self.db.add_item(self.project, name, unit="old")
                    for name in ("Alpha", "Beta", "Gamma", "Delta")]
        uid = self.db.add_user("boss", "pw", role="manager")
        auth.login(self.db.get_user(uid), self.db)
        self.addCleanup(auth.logout)
        self.icon_filter = StandardIconFilter()
        self.app.installEventFilter(self.icon_filter)
        self.addCleanup(self.app.removeEventFilter, self.icon_filter)
        self.pages = []
        self.addCleanup(self.dispose)

    def dispose(self):
        for page in self.pages:
            page.close()
            page.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def page(self):
        page = TrackerPage(self.db, UndoBar())
        self.pages.append(page)
        page.open_project(self.project)
        page.resize(1400, 900)
        page.show()
        self.app.processEvents()
        gc.collect()  # Discarded construction-time buttons must not own popups.
        return page

    def select(self, page, ids):
        table = page.items_table
        table.clearSelection()
        for index, item_id in enumerate(ids):
            cell = next(table.item(row, COL_ITEM_NAME) for row in range(table.rowCount())
                        if table.item(row, COL_ITEM_NAME).data(Qt.UserRole) == item_id)
            QTest.mouseClick(table.viewport(), Qt.LeftButton,
                             Qt.ControlModifier if index else Qt.NoModifier,
                             table.visualItemRect(cell).center())
        self.assertEqual(set(page._selected_item_ids()), set(ids))

    def menu(self, page, label, more=False):
        caption = i18n.tr_text("More Actions" if more else label)
        button = next(b for b in page.findChildren(QPushButton) if b.text() == caption and b.isVisible())
        QTest.mouseClick(button, Qt.LeftButton)
        QTest.qWait(30)
        popup = button.menu()
        self.assertTrue(popup.isVisible(), "Clicking the button must actually show its menu")
        if more:
            action = next(a for a in popup.actions() if a.text() == i18n.tr_text(label))
            QTest.mouseClick(popup, Qt.LeftButton, pos=popup.actionGeometry(action).center())
            QTest.qWait(50)
            popup = action.menu()
            self.assertTrue(popup.isVisible(), "Clicking More Actions must open the submenu")
        return popup

    def command(self, menu, index, dialog_type=None, fill=None):
        self.assertTrue(menu.isVisible())
        errors, opened, accepted = [], [], []
        guard = QTimer()
        guard.setSingleShot(True)

        def dismiss():
            modal = self.app.activeModalWidget()
            if modal:
                modal.reject()

        def handle_dialog():
            try:
                dialog = self.app.activeModalWidget()
                self.assertIsInstance(dialog, dialog_type)
                opened.append(dialog)
                dialog.accepted.connect(lambda: accepted.append(True))
                fill(dialog)
            except Exception as exc:
                errors.append(exc)
                dismiss()

        if dialog_type:
            guard.timeout.connect(dismiss)
            guard.start(2000)
            QTimer.singleShot(30, handle_dialog)
        action = [a for a in menu.actions() if not a.isSeparator()][index]
        QTest.mouseClick(menu, Qt.LeftButton, pos=menu.actionGeometry(action).center())
        self.app.processEvents()
        guard.stop()
        if errors:
            raise errors[0]
        if dialog_type:
            self.assertEqual(len(opened), 1, "The action must open its real dialog")
            self.assertEqual(accepted, [True])

    def check_moves(self, more=False, multiple=False):
        page = self.page()
        selected = self.ids[1:3] if multiple else self.ids[1:2]
        rest = [item_id for item_id in self.ids if item_id not in selected]
        for index in range(5):
            with self.subTest(command=index, more=more, multiple=multiple):
                self.db.reorder_items(self.ids)
                page.reload_items()
                self.select(page, selected)
                popup = self.menu(page, "Move", more)
                if index == 4:
                    def position(dialog):
                        dialog.setIntValue(1)
                        ok = dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok)
                        QTest.mouseClick(ok, Qt.LeftButton)
                    self.command(popup, index, QInputDialog, position)
                else:
                    self.command(popup, index)
                expected = selected + rest if index in (0, 2, 4) else (
                    rest + selected if index == 3 or multiple else [rest[0], rest[1]] + selected + rest[2:])
                self.assertEqual([r["id"] for r in self.db.get_items(self.project)], expected)
                table_ids = [page.items_table.item(r, COL_ITEM_NAME).data(Qt.UserRole)
                             for r in range(page.items_table.rowCount())]
                self.assertEqual(table_ids, expected)
                self.assertEqual(set(page._selected_item_ids()), set(selected))

    def test_toolbar_all_move_commands_single_selection(self):
        self.check_moves()

    def test_toolbar_all_move_commands_multiple_selection(self):
        self.check_moves(multiple=True)

    def test_more_actions_does_not_repeat_selection_commands(self):
        page = self.page()
        self.select(page, self.ids[1:3])
        button = next(b for b in page.findChildren(QPushButton) if b.text() == "More Actions")
        QTest.mouseClick(button, Qt.LeftButton)
        self.assertTrue(button.menu().isVisible())
        self.assertEqual([a.text() for a in button.menu().actions() if not a.isSeparator()],
                         [i18n.tr("history"), i18n.tr("trash")])
        button.menu().close()

    def check_bulk(self, more=False):
        page = self.page()
        self.select(page, self.ids[1:3])
        def apply(dialog):
            QTest.mouseClick(dialog.unit_check, Qt.LeftButton)
            QTest.keyClicks(dialog.unit_edit, "pcs")
            QTest.mouseClick(dialog.findChild(QPushButton, "primaryButton"), Qt.LeftButton)
        self.command(self.menu(page, "Bulk Edit", more), 0, BulkEditDialog, apply)
        self.assertEqual([self.db.get_item(i)["unit"] for i in self.ids], ["old", "pcs", "pcs", "old"])
        self.assertEqual(set(page._selected_item_ids()), set(self.ids[1:3]))

    def test_toolbar_bulk_edit_applies_only_to_selected_rows(self):
        self.check_bulk()

    def test_history_action_requires_exactly_one_selected_item(self):
        page = self.page()
        self.assertFalse(page.history_action.isEnabled())
        self.select(page, self.ids[1:2])
        self.assertTrue(page.history_action.isEnabled())
        self.select(page, self.ids[1:3])
        self.assertFalse(page.history_action.isEnabled())

    def test_arabic_buttons_after_page_recreation(self):
        self.page().close()
        i18n.set_language("ar")
        self.check_bulk()
        self.check_moves()

    def test_find_replace_from_selection_menu_can_be_reused(self):
        page = self.page()
        for more in (False, True):
            self.select(page, self.ids[1:3])
            def apply(dialog):
                dialog.field_combo.setCurrentIndex(dialog.field_combo.findData("unit"))
                QTest.keyClicks(dialog.find_edit, "old" if not more else "pcs")
                QTest.keyClicks(dialog.replace_edit, "pcs" if not more else "new")
                QTest.mouseClick(dialog.apply_btn, Qt.LeftButton)
            # Suppress only the post-save notification; exercise the editor itself.
            with patch("ui.find_replace_dialog.QMessageBox.information"):
                self.command(self.menu(page, "Bulk Edit"), 1, FindReplaceDialog, apply)
            value = "pcs" if not more else "new"
            self.assertEqual([self.db.get_item(i)["unit"] for i in self.ids], ["old", value, value, "old"])

    def test_move_keyboard_shortcuts_preserve_selection(self):
        page = self.page()
        page.activateWindow()
        self.app.processEvents()
        for key, modifiers, expected in (
            (Qt.Key_Up, Qt.AltModifier, [2, 1, 3, 4]),
            (Qt.Key_Down, Qt.AltModifier, [1, 3, 2, 4]),
            (Qt.Key_Up, Qt.ControlModifier | Qt.AltModifier, [2, 1, 3, 4]),
            (Qt.Key_Down, Qt.ControlModifier | Qt.AltModifier, [1, 3, 4, 2]),
        ):
            self.db.reorder_items(self.ids)
            page.reload_items()
            self.select(page, [self.ids[1]])
            QTest.keyClick(page.items_table, key, modifiers)
            self.app.processEvents()
            self.assertEqual([r["id"] for r in self.db.get_items(self.project)],
                             [self.ids[n - 1] for n in expected])
            self.assertEqual(page._selected_item_ids(), [self.ids[1]])

    def test_context_menu_move_updates_database(self):
        page = self.page()
        self.select(page, [self.ids[1]])
        errors = []
        def choose():
            try:
                popup = self.app.activePopupWidget()
                self.assertIsNotNone(popup)
                action = next(a for a in popup.actions() if a.text() == i18n.tr("move_up"))
                self.assertTrue(popup.isVisible())
                QTest.mouseClick(popup, Qt.LeftButton, pos=popup.actionGeometry(action).center())
            except Exception as exc:
                errors.append(exc)
                if self.app.activePopupWidget():
                    self.app.activePopupWidget().close()
        QTimer.singleShot(30, choose)
        viewport = page.items_table.viewport()
        pos = page.items_table.visualItemRect(page.items_table.item(1, COL_ITEM_NAME)).center()
        event = QContextMenuEvent(QContextMenuEvent.Mouse, pos, viewport.mapToGlobal(pos))
        self.app.sendEvent(viewport, event)
        if errors:
            raise errors[0]
        self.assertEqual([r["id"] for r in self.db.get_items(self.project)],
                         [self.ids[1], self.ids[0], self.ids[2], self.ids[3]])
