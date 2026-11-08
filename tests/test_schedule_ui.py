"""Visible month header, scrolling alignment, and schedule theme regressions."""
import datetime
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import unittest

from PySide6.QtCore import QPoint, Qt, QCoreApplication, QEvent
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

import constants
import i18n
from database import Database
from ui.schedule_page import SchedulePage, GanttTimeline, _month_label
from ui.styles import get_stylesheet


class ScheduleUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(constants.set_theme, constants.get_theme())
        self.addCleanup(i18n.set_language, i18n.get_language())
        self.addCleanup(self.app.setStyleSheet, self.app.styleSheet())
        self.db = Database(os.path.join(self.tmp.name, "db.sqlite"),
                           os.path.join(self.tmp.name, "attachments"))
        self.pid = self.db.add_project("Schedule")
        for index in range(25):
            self.db.add_schedule_activity(self.pid, f"Activity {index + 1}", phase="Construction",
                                          start_date="2026-01-01", end_date="2026-03-31",
                                          progress=25)
        self.page = SchedulePage(self.db)
        self.addCleanup(self._dispose)
        self.page.resize(1000, 560)
        self.page.open_project(self.pid)
        self.page.show()
        self.app.processEvents()

    def _dispose(self):
        self.page.close()
        self.page.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def assert_header_aligned(self):
        header = self.page.timeline_header
        canvas = self.page.timeline
        self.assertTrue(header.isVisibleTo(self.page))
        self.assertFalse(header.isWindow())
        self.assertEqual(header.width(), canvas.width())
        self.assertEqual(header.mapTo(self.page, QPoint()).x(),
                         canvas.mapTo(self.page, QPoint()).x())
        clip = header.parentWidget()
        viewport = self.page.timeline_scroll.viewport()
        self.assertEqual(clip.width(), viewport.width())
        self.assertEqual(clip.mapTo(self.page, QPoint()).y() + clip.height(),
                         viewport.mapTo(self.page, QPoint()).y())

    def test_month_header_visible_and_fixed_during_vertical_scroll(self):
        self.assert_header_aligned()
        header_y = self.page.timeline_header.mapTo(self.page, QPoint()).y()
        bar = self.page.timeline_scroll.verticalScrollBar()
        self.assertGreater(bar.maximum(), 0)
        bar.setValue(bar.maximum())
        self.app.processEvents()
        self.assert_header_aligned()
        self.assertEqual(self.page.timeline_header.mapTo(self.page, QPoint()).y(), header_y)

    def test_header_tracks_horizontal_scroll_resize_and_direction(self):
        for direction in (Qt.LeftToRight, Qt.RightToLeft):
            with self.subTest(direction=direction):
                self.page.setLayoutDirection(direction)
                self.page.reload()
                self.page.timeline.setMinimumWidth(1500)
                self.app.processEvents()
                bar = self.page.timeline_scroll.horizontalScrollBar()
                self.assertGreater(bar.maximum(), 0)
                for value in (0, bar.maximum() // 2, bar.maximum()):
                    bar.setValue(value)
                    self.app.processEvents()
                    self.assert_header_aligned()
                self.page.resize(1200, 620)
                self.app.processEvents()
                self.assert_header_aligned()

    def test_header_stays_aligned_when_vertical_scrollbar_disappears(self):
        self.assertGreater(self.page.timeline_scroll.verticalScrollBar().maximum(), 0)
        empty = self.db.add_project("Empty")
        self.page.open_project(empty)
        self.app.processEvents()
        self.assertEqual(self.page.timeline_scroll.verticalScrollBar().maximum(), 0)
        self.assert_header_aligned()

    def test_canvas_and_header_use_theme_background_not_system_palette(self):
        # Use an unmistakable platform background to catch accidental palette use.
        for widget in (self.page.timeline, self.page.timeline_header):
            palette = widget.palette()
            palette.setColor(QPalette.Window, QColor("#ff00ff"))
            widget.setPalette(palette)
        for theme in ("dark", "light", "dark"):
            with self.subTest(theme=theme):
                constants.set_theme(theme)
                self.app.setStyleSheet(get_stylesheet(theme))
                self.app.processEvents()
                expected = QColor(constants.schedule_colors(theme)["panel"])
                header = self.page.timeline_header.grab().toImage()
                body = self.page.timeline.grab().toImage()
                self.assertEqual(header.pixelColor(4, 4), expected)
                # Just after the phase row, left of any activity text.
                self.assertEqual(body.pixelColor(4, GanttTimeline.PHASE_HEIGHT + 6), expected)

    def test_language_and_dates_propagate_to_visible_header(self):
        for lang, direction in (("en", Qt.LeftToRight), ("ar", Qt.RightToLeft)):
            with self.subTest(lang=lang):
                i18n.set_language(lang)
                self.page.setLayoutDirection(direction)
                self.page.reload()
                self.app.processEvents()
                header = self.page.timeline_header
                self.assertEqual(header._lang, lang)
                self.assertEqual(header._rtl, direction == Qt.RightToLeft)
                self.assertEqual(header._start, datetime.date(2026, 1, 1))
                self.assertEqual(header._end, datetime.date(2026, 3, 31))
                self.assert_header_aligned()
        self.assertEqual(_month_label(datetime.date(2026, 1, 1), "en"), "Jan 2026")
        self.assertEqual(_month_label(datetime.date(2026, 1, 1), "ar"), "يناير 2026")

    def test_final_day_bar_stays_inside_month_scale_in_both_directions(self):
        canvas = self.page.timeline
        activity = canvas._activities[0]
        for rtl in (False, True):
            canvas.set_model([activity], rtl, "ar" if rtl else "en")
            rect = canvas._bar_rect(activity, canvas.width())
            self.assertAlmostEqual(rect.left(), canvas.NAME_WIDTH)
            self.assertAlmostEqual(rect.right(), canvas.width())
