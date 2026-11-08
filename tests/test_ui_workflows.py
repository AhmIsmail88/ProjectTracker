import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile
import unittest
import threading
from unittest.mock import patch
from PySide6.QtCore import QSettings, Qt, QCoreApplication, QEvent, QThread, Signal
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

import config
import auth
import i18n
from database import Database
from ui.widgets import UndoBar
from ui.items_page import TrackerPage, COL_UNIT_COST, COL_TOTAL_COST, COL_REQUESTED_QTY, COL_STATUS
from ui.projects_page import ProjectsPage
from ui.attachments_dialog import AttachmentsDialog, PDF_PREVIEW_AVAILABLE
from ui.review_items_dialog import ReviewItemsDialog
from ui.dashboard_page import DashboardPage
from ui.project_picker import ProjectPicker
from ui.suppliers_page import SuppliersPage
from ui.ai_page import AIPage
from ui.table_utils import ExportWorker


class UiWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        context = patch.object(config, "CONFIG_PATH", os.path.join(self.root, "config.json"))
        context.start()
        self.addCleanup(context.stop)
        lang = i18n.get_language()
        self.addCleanup(i18n.set_language, lang)
        i18n.set_language("en")
        self.db = Database(os.path.join(self.root, "db.sqlite"), os.path.join(self.root, "attachments"))
        self.group = self.db.add_project_group("Main Site")
        self.p1 = self.db.add_project("Section A", project_number="A-01", group_id=self.group)
        self.p2 = self.db.add_project("Section B", group_id=self.group)
        self.p3 = self.db.add_project("Standalone")
        self.a = self.db.add_item(self.p1, "Pump", total_quantity=2, unit_cost=10, currency="SAR")
        self.b = self.db.add_item(self.p1, "Valve", total_quantity=3, unit_cost=20, currency="USD")
        self.c = self.db.add_item(self.p2, "Pipe", total_quantity=4)
        uid = self.db.add_user("boss", "pw", role="manager")
        auth.login(self.db.get_user(uid), self.db)
        self.addCleanup(auth.logout)
        self.widgets = []
        self.addCleanup(self._dispose)

    def _dispose(self):
        for widget in self.widgets:
            widget.close()
            widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def keep(self, widget):
        self.widgets.append(widget)
        return widget

    def attachment(self, item_id, category):
        path = os.path.join(self.root, category + ".txt")
        with open(path, "w") as stream:
            stream.write(category)
        return self.db.add_attachment(item_id, category, path)

    def test_group_tree_filters_children_and_opens_selected_leaf(self):
        page = self.keep(ProjectsPage(self.db, UndoBar()))
        node = page._tree_groups[self.group]
        self.assertEqual(node.childCount(), 2)
        page.project_tree.setCurrentItem(node)
        self.assertEqual(set(page._visible_project_ids()), {self.p1, self.p2})
        self.assertEqual(page.overview.context.text(), "2 projects")
        self.assertEqual(page.overview.metrics["items"].text(), "3")
        page.project_tree.setCurrentItem(page._tree_projects[self.p2])
        self.assertEqual(page.selected_project_id(), self.p2)
        opened = []
        page.project_opened.connect(opened.append)
        page._open_tree_project(page._tree_projects[self.p2], 0)
        self.assertEqual(opened, [self.p2])

    def test_tree_search_preserves_group_matches_and_supports_ungrouped(self):
        page = self.keep(ProjectsPage(self.db, UndoBar()))
        page.search_edit.setText("Main Site")
        self.assertFalse(page._tree_projects[self.p1].isHidden())
        self.assertTrue(page._tree_projects[self.p3].isHidden())
        page.search_edit.clear()
        page.project_tree.setCurrentItem(page._tree_groups[None])
        self.assertEqual(page._visible_project_ids(), [self.p3])
        page.select_project(self.p1)
        self.assertFalse(page._tree_projects[self.p1].isHidden())

    def test_tree_click_shows_project_dashboard_and_opens_that_project(self):
        self.db.update_item(self.a, delivered_quantity=2, requested_quantity=2)
        page = self.keep(ProjectsPage(self.db, UndoBar()))
        page.resize(1200, 800)
        page.show()
        self.app.processEvents()
        node = page._tree_projects[self.p1]
        QTest.mouseClick(page.project_tree.viewport(), Qt.LeftButton,
                         pos=page.project_tree.visualItemRect(node).center())
        self.assertEqual(page.overview.title.text(), "Section A")
        self.assertIn("A-01", page.overview.metadata.text())
        self.assertEqual(page.overview.metrics["items"].text(), "2")
        self.assertEqual(page.overview.progress.value(), 50)
        self.assertIn("20.00 SAR", page.overview.value.text())
        self.assertIn("60.00 USD", page.overview.value.text())
        self.assertEqual(page._visible_project_ids(), [self.p1])
        opened = []
        page.project_opened.connect(opened.append)
        QTest.mouseClick(page.overview.open_btn, Qt.LeftButton)
        self.assertEqual(opened, [self.p1])
        page.project_tree.setCurrentItem(page._tree_groups[self.group])
        self.assertEqual(page.overview.title.text(), "Main Site")
        self.assertEqual(page.overview.metrics["items"].text(), "3")
        self.assertTrue(page.overview.open_btn.isHidden())
        self.assertTrue(all(not action.isEnabled() for action in page.project_actions))

    def test_project_dashboard_clears_deleted_selection_and_restores_group_on_reload(self):
        page = self.keep(ProjectsPage(self.db, UndoBar()))
        page.project_tree.setCurrentItem(page._tree_groups[self.group])
        page.reload()
        self.assertEqual(page.selected_scope(), ("group", self.group))
        page.select_project(self.p1)
        page._delete_project()
        self.assertIsNone(page.selected_project_id())
        self.assertNotEqual(page.overview.title.text(), "Section A")
        self.assertNotIn(self.p1, page._visible_project_ids())

    def test_currency_totals_are_separate_and_filtered(self):
        page = self.keep(TrackerPage(self.db, UndoBar()))
        page.open_project(self.p1)
        self.assertIn("20.00 SAR", page.items_summary_label.text())
        self.assertIn("60.00 USD", page.items_summary_label.text())
        self.assertNotIn("80.00", page.items_summary_label.text())
        page.search_edit.setText("Pump")
        self.assertIn("20.00 SAR", page.items_summary_label.text())
        self.assertNotIn("USD", page.items_summary_label.text())

    def test_inline_edit_under_sort_does_not_overwrite_neighbor_cells(self):
        page = self.keep(TrackerPage(self.db, UndoBar()))
        page.open_project(self.p1)
        for column, value in ((COL_UNIT_COST, "100"), (COL_REQUESTED_QTY, "2")):
            page.items_table.sortItems(column, Qt.AscendingOrder)
            row = page._row_for_item_id(self.a)
            page.items_table.item(row, column).setText(value)
            for item_id in (self.a, self.b):
                item = self.db.get_item(item_id)
                row = page._row_for_item_id(item_id)
                self.assertEqual(float(page.items_table.item(row, COL_TOTAL_COST).text().replace(",", "")),
                                 item["total_quantity"] * item["unit_cost"])
                self.assertEqual(page.items_table.item(row, COL_STATUS).data(Qt.UserRole), item["status"])

    def test_filtered_out_item_cannot_be_deleted_through_current_row(self):
        page = self.keep(TrackerPage(self.db, UndoBar()))
        page.open_project(self.p1)
        page._select_rows_by_item_ids([self.a])
        page.search_edit.setText("Valve")
        with patch("ui.items_page.QMessageBox.information"):
            self.assertIsNone(page._current_item_id())
            page._delete_item()
        self.assertFalse(self.db.get_item(self.a)["is_deleted"])

    def test_filtered_out_project_cannot_be_deleted(self):
        page = self.keep(ProjectsPage(self.db, UndoBar()))
        page.select_project(self.p1)
        page.search_edit.setText("Standalone")
        with patch("ui.projects_page.QMessageBox.information"):
            page._delete_project()
        self.assertFalse(self.db.get_project(self.p1)["is_deleted"])

    def test_filtered_out_supplier_cannot_be_deleted(self):
        first = self.db.add_supplier("Alpha")
        self.db.add_supplier("Beta")
        page = self.keep(SuppliersPage(self.db, UndoBar()))
        page._select_row_by_id(first)
        page.search_edit.setText("Beta")
        with patch("ui.suppliers_page.QMessageBox.information"):
            page._delete_supplier()
        self.assertIn(first, [supplier["id"] for supplier in self.db.get_suppliers()])

    def test_legacy_attachment_categories_remain_accessible(self):
        self.attachment(self.a, "Legacy document")
        dialog = self.keep(AttachmentsDialog(None, self.db, self.a, "Pump"))
        self.assertEqual(dialog.list_widget.topLevelItemCount(), 1)
        dialog.list_widget.setCurrentItem(dialog.list_widget.topLevelItem(0).child(0))
        self.assertTrue(dialog.open_btn.isEnabled())
        self.assertEqual(dialog._selected_attachment()["category"], "Legacy document")

    def test_ai_connection_test_cannot_start_overlapping_workers(self):
        page = self.keep(AIPage(self.db))
        release = threading.Event()
        class Worker(QThread):
            result_ready = Signal(dict)
            def run(self):
                release.wait(5)
        worker = Worker()
        with patch("ui.ai_page.openrouter_client.is_configured", return_value=True), \
             patch("ui.ai_page._TestConnWorker", return_value=worker) as factory, \
             patch("ui.ai_page._ChatWorker") as chat:
            try:
                page._test_connection()
                page._test_connection()
                page._ask("Question during connection test")
                factory.assert_called_once()
                chat.assert_not_called()
                self.assertFalse(page.test_conn_btn.isEnabled())
                self.assertFalse(page.send_btn.isEnabled())
            finally:
                release.set()
                worker.wait(1000)
            page._on_test_connection_result({"ok": True, "seconds": 0, "reply": "OK",
                                            "model": "test", "env_path": "test", "env_exists": True})
            self.assertTrue(page.test_conn_btn.isEnabled())
            self.assertTrue(page.send_btn.isEnabled())

    def test_export_keeps_original_project_after_navigation(self):
        page = self.keep(TrackerPage(self.db, UndoBar()))
        for method, module in (("_export_excel", "export.excel_export.export_project_to_excel"),
                               ("_export_pdf", "export.pdf_export.export_project_to_pdf"),
                               ("_export_filtered_excel", "export.excel_export.export_project_to_excel")):
            page.open_project(self.p1)
            with patch("ui.items_page.QFileDialog.getSaveFileName", return_value=("report", "")), \
                 patch.object(page, "_run_export") as start, patch(module) as export:
                getattr(page, method)()
                pending_export = start.call_args.args[2]
                page.open_project(self.p2)
                pending_export()
                self.assertEqual(export.call_args.args[:2], (self.db, self.p1))

    def test_exports_cannot_replace_a_running_worker(self):
        page = self.keep(TrackerPage(self.db, UndoBar()))
        page.open_project(self.p1)
        release = threading.Event()
        executed = []
        def work():
            release.wait(5)
            executed.append("first")
        with patch("ui.items_page.QMessageBox.information"):
            page._run_export(page.excel_btn, "Excel", work, "Done")
            worker = page._export_worker
            try:
                page._run_export(page.pdf_btn, "PDF", lambda: executed.append("second"), "Done")
                self.assertIs(page._export_worker, worker)
                self.assertFalse(page.pdf_btn.isEnabled())
                self.assertIn(worker, ExportWorker.active_workers())
            finally:
                release.set()
                worker.wait(1000)
            self.app.processEvents()
            self.assertEqual(executed, ["first"])
            self.assertTrue(page.pdf_btn.isEnabled())
            self.assertIsNone(page._export_worker)

    def test_selection_bar_without_details_and_filter_chip_removal(self):
        page = self.keep(TrackerPage(self.db, UndoBar()))
        page.open_project(self.p1)
        page._select_rows_by_item_ids([self.a])
        self.assertFalse(hasattr(page, "details_panel"))
        self.assertFalse(hasattr(page, "details_btn"))
        page._select_rows_by_item_ids([self.a, self.b])
        self.assertIn("2", page.selection_label.text())
        page.missing_prpo_check.setChecked(True)
        self.assertEqual(page.filter_chips_layout.count(), 1)
        page.filter_chips_layout.itemAt(0).widget().click()
        self.assertFalse(page.missing_prpo_check.isChecked())

    def test_filtered_out_selection_does_not_remain_in_bulk_actions(self):
        page = self.keep(TrackerPage(self.db, UndoBar()))
        page.open_project(self.p1)
        page._select_rows_by_item_ids([self.a, self.b])
        page.search_edit.setText("Pump")
        self.assertEqual(page._selected_item_ids(), [self.a])

    def test_project_picker_has_group_headings_and_emits_only_leaf_ids(self):
        picker = self.keep(ProjectPicker(self.db))
        picker.set_project(self.p1)
        self.assertIn("A-01", picker.currentText())
        result = []
        picker.project_requested.connect(result.append)
        picker.setCurrentIndex(picker.findData(self.p2))
        picker._activated(picker.currentIndex())
        self.assertEqual(result, [self.p2])
        picker.setCurrentIndex(0)
        picker._activated(0)
        self.assertEqual(result, [self.p2])

    def test_attachment_groups_filter_and_delete_undo(self):
        self.attachment(self.a, "PR")
        self.attachment(self.a, "PO")
        dialog = self.keep(AttachmentsDialog(None, self.db, self.a, "Pump"))
        self.assertEqual(dialog.list_widget.topLevelItemCount(), 2)
        dialog.filter_combo.setCurrentIndex(dialog.filter_combo.findData("PO"))
        self.assertEqual(dialog.list_widget.topLevelItemCount(), 1)
        file = dialog.list_widget.topLevelItem(0).child(0)
        dialog.list_widget.setCurrentItem(file)
        self.assertTrue(dialog.open_btn.isEnabled())
        self.assertEqual(dialog.category_combo.currentData(), "PO")
        dialog._delete_selected()
        self.assertEqual(len(self.db.get_attachments(self.a, "PO")), 0)
        dialog.undo_bar._on_undo_clicked()
        self.assertEqual(len(self.db.get_attachments(self.a, "PO")), 1)

    def test_unconfigured_ai_preserves_question_and_does_not_create_report_history(self):
        page = self.keep(AIPage(self.db))
        page.input_edit.setText("What is pending?")
        with patch("ui.ai_page.openrouter_client.is_configured", return_value=False), patch.object(page, "_open_settings"):
            page._send()
            self.assertEqual(page.input_edit.text(), "What is pending?")
            page._generate_report()
        self.assertEqual(self.db.get_chat_history(None), [])
        self.assertIsNone(page._worker)

    def test_attachment_empty_state_and_missing_file_preview(self):
        dialog = self.keep(AttachmentsDialog(None, self.db, self.a, "Pump"))
        self.assertFalse(dialog.open_btn.isEnabled())
        self.assertIn("No attachments", dialog.preview_label.text())
        path = self.attachment(self.a, "PR")
        os.remove(path)
        dialog._reload_list()
        dialog.list_widget.setCurrentItem(dialog.list_widget.topLevelItem(0).child(0))
        self.assertIn("missing", dialog.preview_label.text())

    def test_attachment_long_title_leaves_space_for_preview_at_all_sizes(self):
        name = "AWCS Air Inlet Valve ø500 mm " * 30
        dialog = self.keep(AttachmentsDialog(None, self.db, self.a, name))
        dialog.show()
        for width, height in ((760, 520), (1200, 800)):
            dialog.resize(width, height)
            self.app.processEvents()
            self.assertEqual(dialog.size().width(), width)
            self.assertLess(dialog.item_title.height(), 60)
            self.assertGreater(dialog.splitter.height(), height * 0.55)
            self.assertEqual(dialog.item_title.toolTip(), name)
            self.assertIn("…", dialog.item_title.text())
        self.assertTrue(dialog.windowFlags() & Qt.WindowMaximizeButtonHint)
        self.assertTrue(dialog.windowFlags() & Qt.WindowMinimizeButtonHint)

    def test_attachment_image_refits_when_splitter_moves(self):
        from PySide6.QtGui import QPixmap
        path = os.path.join(self.root, "wide-image.png")
        pixmap = QPixmap(1600, 300)
        pixmap.fill(Qt.blue)
        pixmap.save(path)
        self.db.add_attachment(self.a, "PR", path)
        dialog = self.keep(AttachmentsDialog(None, self.db, self.a, "Pump"))
        dialog.show()
        dialog.list_widget.setCurrentItem(dialog.list_widget.topLevelItem(0).child(0))
        self.app.processEvents()
        old_width = dialog.preview_label.pixmap().width()
        dialog.splitter.setSizes([650, 320])
        self.app.processEvents()
        self.assertLess(dialog.preview_label.pixmap().width(), old_width)
        self.assertLessEqual(dialog.preview_label.pixmap().width(), dialog.preview_label.width())

    @unittest.skipUnless(PDF_PREVIEW_AVAILABLE, "Qt PDF is unavailable")
    def test_multipage_attachment_exposes_all_pages(self):
        from reportlab.pdfgen.canvas import Canvas
        from PySide6.QtPdfWidgets import QPdfView
        path = os.path.join(self.root, "two-pages.pdf")
        canvas = Canvas(path)
        for text in ("First page", "Second page"):
            canvas.drawString(60, 700, text)
            canvas.showPage()
        canvas.save()
        self.db.add_attachment(self.a, "PR", path)
        dialog = self.keep(AttachmentsDialog(None, self.db, self.a, "Pump"))
        dialog.list_widget.setCurrentItem(dialog.list_widget.topLevelItem(0).child(0))
        self.assertEqual(dialog.pdf_document.pageCount(), 2)
        self.assertIs(dialog.preview_stack.currentWidget(), dialog.pdf_view)
        self.assertEqual(dialog.pdf_view.pageMode(), QPdfView.PageMode.MultiPage)

    def test_review_dialog_criteria_and_scope_match_dashboard_cards(self):
        self.attachment(self.a, "PR")
        self.attachment(self.a, "PO")
        costs = self.keep(ReviewItemsDialog(self.db, [self.p2], "missing_cost"))
        self.assertEqual(costs.table.rowCount(), 1)
        documents = self.keep(ReviewItemsDialog(self.db, [self.p1], "missing_documents"))
        self.assertEqual(documents.table.rowCount(), 1)
        self.assertEqual(documents.table.item(0, 0).data(Qt.UserRole), (self.p1, self.b))
        empty = self.keep(ReviewItemsDialog(self.db, [], "missing_cost"))
        self.assertEqual(empty.table.rowCount(), 0)
        settings = QSettings(os.path.join(self.root, "ui.ini"), QSettings.IniFormat)
        with patch("ui.dashboard_page.QSettings", return_value=settings):
            page = self.keep(DashboardPage(self.db))
            page.reload()
            self.assertEqual(page.val_documents.text(), "2")
            with patch("ui.dashboard_page.ReviewItemsDialog") as dialog:
                page.card_missing_cost.clicked.emit()
                self.assertEqual(dialog.call_args.args[2], "missing_cost")
                dialog.return_value.exec.assert_called_once()

    def test_group_status_review_excludes_other_projects_and_statuses(self):
        held = self.db.add_item(self.p1, "Held", manual_hold=True)
        self.db.add_item(self.p3, "Other held", manual_hold=True)
        page = self.keep(ProjectsPage(self.db, UndoBar()))
        page.restore_scope(("group", self.group))
        with patch("ui.projects_page.ReviewItemsDialog") as factory:
            page._open_metric("blocked")
            self.assertEqual(set(factory.call_args.args[1]), {self.p1, self.p2})
            self.assertEqual(factory.call_args.kwargs["status"], "On Hold")
        dialog = self.keep(ReviewItemsDialog(self.db, [self.p1, self.p2], status="On Hold"))
        self.assertEqual(dialog.table.rowCount(), 1)
        self.assertEqual(dialog.table.item(0, 0).data(Qt.UserRole), (self.p1, held))
