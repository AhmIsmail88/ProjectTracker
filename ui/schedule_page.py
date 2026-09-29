"""
ui/schedule_page.py
The project time schedule: activities laid out on a month-scale timeline.

The name column and the timeline are painted in ONE widget, so they can never
drift apart while scrolling - the classic two-widget sync bug. Everything is
RTL-aware (dates run right-to-left under Arabic) and the colours come from the
theme, so the bars follow dark/light.
"""

import calendar
import datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from PySide6.QtCore import QDate, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

import constants
import i18n
from constants import schedule_colors
from i18n import tr
from ui.dialogs import ScheduleActivityDialog


def _parse_date(text):
    """'YYYY-MM-DD[ HH:MM:SS]' -> datetime.date, or None."""
    if not text:
        return None
    try:
        return datetime.date.fromisoformat(str(text)[:10])
    except ValueError:
        return None


def _add_months(date, count):
    """The same day-of-month shifted by *count* months, clamped to the month."""
    index = date.month - 1 + count
    year = date.year + index // 12
    month = index % 12 + 1
    return datetime.date(year, month, min(date.day, calendar.monthrange(year, month)[1]))


def _month_starts(start, end):
    """The first day of every month covering [start, end]."""
    months = []
    cursor = datetime.date(start.year, start.month, 1)
    while cursor <= end:
        months.append(cursor)
        cursor = _add_months(cursor, 1)
    return months


_ARABIC_MONTHS = {1: "يناير", 2: "فبراير", 3: "مارس", 4: "أبريل", 5: "مايو", 6: "يونيو",
                  7: "يوليو", 8: "أغسطس", 9: "سبتمبر", 10: "أكتوبر", 11: "نوفمبر", 12: "ديسمبر"}


def _month_label(date, lang):
    if lang == "ar":
        return f"{_ARABIC_MONTHS[date.month]} {date.year}"
    return f"{calendar.month_abbr[date.month]} {date.year}"


def _duration_days(activity):
    start = _parse_date(activity["start_date"])
    end = _parse_date(activity["end_date"])
    if not start or not end:
        return None
    return max(0, (end - start).days)


def _write_schedule_excel(activities, project_name, output_path, lang="ar"):
    """The schedule as one sheet: a row per activity with duration and dates.
    Follows the app's house Excel style (header fill, frozen panes, widths)."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Schedule" if lang != "ar" else "الجدول"

    headers = [
        tr("schedule_col_activity"), tr("schedule_col_phase"),
        tr("schedule_col_start"), tr("schedule_col_end"),
        tr("schedule_col_duration"), tr("schedule_col_progress"),
        tr("schedule_col_milestone"), tr("schedule_col_notes"),
    ]

    sheet.merge_cells("A1:H1")
    title = sheet.cell(row=1, column=1, value=f"{tr('schedule')} - {project_name}")
    title.font = Font(name="Calibri", bold=True, size=14)

    for index, label in enumerate(headers, start=1):
        cell = sheet.cell(row=3, column=index, value=label)
        cell.font = Font(name="Calibri", bold=True, size=10)
        cell.fill = PatternFill("solid", fgColor="DCE6F1")
        cell.alignment = Alignment(horizontal="center", vertical="center")
    sheet.freeze_panes = "A4"

    for offset, activity in enumerate(activities):
        row = 4 + offset
        duration = _duration_days(activity)
        values = [
            activity["name"] or "",
            activity["phase"] or "",
            activity["start_date"] or "",
            activity["end_date"] or "",
            duration if duration is not None else "",
            int(activity["progress"] or 0),
            "◆" if activity["milestone"] else "",
            activity["notes"] or "",
        ]
        for index, value in enumerate(values, start=1):
            cell = sheet.cell(row=row, column=index, value=value)
            cell.font = Font(name="Calibri", size=10)
            if index in (5, 6):
                cell.alignment = Alignment(horizontal="right")

    for index, width in enumerate((46, 18, 13, 13, 13, 11, 11, 40), start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width

    workbook.save(output_path)
    return output_path


def paint_month_bands(painter, width, height, start, end, name_width, rtl, lang,
                      with_labels=True):
    """Draws the month bands across the timeline area.

    Shared by the header (with labels) and the body (bands only), so the two
    can never disagree about where a month starts.
    """
    if start is None or end is None:
        return
    colors = schedule_colors(constants.get_theme())
    total_days = max(1, (end - start).days)
    timeline_width = max(1.0, width - name_width)

    def band_x(day):
        ratio = (day - start).days / total_days
        if rtl:
            ratio = 1.0 - ratio
        return name_width + ratio * timeline_width

    painter.fillRect(QRectF(name_width, 0, timeline_width, height),
                     QColor(colors["panel"]))

    font = QFont(painter.font())
    font.setPointSizeF(8.0)
    font.setBold(True)
    painter.setFont(font)

    for month in _month_starts(start, end):
        following = _add_months(month, 1)
        if following > end:
            following = end + datetime.timedelta(days=1)
        x1, x2 = band_x(month), band_x(following)
        left, right = min(x1, x2), max(x1, x2)
        if right - left < 1:
            continue
        painter.fillRect(QRectF(left, 0, right - left, height), QColor(colors["grid"]))
        if with_labels:
            painter.setPen(QColor(colors["text"]))
            painter.drawText(QRectF(left, 0, right - left, height), Qt.AlignCenter,
                             _month_label(month, lang))
            painter.setPen(QColor(colors["muted"]))


class TimelineHeader(QWidget):
    """The month scale drawn above the bars."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._start = self._end = None
        self._name_width = 300
        self._rtl = False
        self._lang = "ar"
        self.setFixedHeight(26)

    def set_model(self, start, end, name_width, rtl, lang):
        self._start, self._end = start, end
        self._name_width, self._rtl, self._lang = name_width, rtl, lang
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.palette().window())
        paint_month_bands(painter, self.width(), self.height(), self._start,
                          self._end, self._name_width, self._rtl, self._lang,
                          with_labels=True)
        painter.end()


class GanttTimeline(QWidget):
    """Activity names on one side, their bars on the timeline."""

    rowSelected = Signal(int)
    activityDoubleClicked = Signal(int)

    NAME_WIDTH = 300
    ROW_HEIGHT = 30
    PHASE_HEIGHT = 26

    def __init__(self, parent=None):
        super().__init__(parent)
        self._activities = []
        self._row_model = []
        self._start = None
        self._end = None
        self._selected_id = None
        self._rtl = False
        self._lang = "ar"

    # ------------------------------------------------------------------ #
    def set_model(self, activities, rtl, lang):
        """Groups activities by phase (keeping schedule order) and lays out the
        rows. Selection is kept when that activity still exists."""
        self._activities = list(activities)
        self._rtl = rtl
        self._lang = lang

        groups, order = {}, []
        for activity in self._activities:
            phase = (activity["phase"] or "").strip()
            if phase not in groups:
                groups[phase] = []
                order.append(phase)
            groups[phase].append(activity)

        self._row_model = []
        for phase in order:
            self._row_model.append(("phase", phase))
            for activity in groups[phase]:
                self._row_model.append(("activity", activity))

        dates = []
        for activity in self._activities:
            for key in ("start_date", "end_date"):
                parsed = _parse_date(activity[key])
                if parsed:
                    dates.append(parsed)
        if dates:
            self._start = min(dates).replace(day=1)
            last = max(dates)
            self._end = _add_months(datetime.date(last.year, last.month, 1), 1) - datetime.timedelta(days=1)
        else:
            today = datetime.date.today()
            self._start = datetime.date(today.year, today.month, 1)
            self._end = _add_months(self._start, 3) - datetime.timedelta(days=1)

        if self._selected_id is not None and not any(
                a["id"] == self._selected_id for a in self._activities):
            self._selected_id = None

        height = 4
        for kind, _value in self._row_model:
            height += self.PHASE_HEIGHT if kind == "phase" else self.ROW_HEIGHT
        self.setMinimumHeight(height)
        self.update()

    def selected_activity_id(self):
        return self._selected_id

    def selected_activity(self):
        for activity in self._activities:
            if activity["id"] == self._selected_id:
                return activity
        return None

    # ------------------------------------------------------------------ #
    def _ratio_for(self, day):
        total_days = max(1, (self._end - self._start).days)
        ratio = (day - self._start).days / total_days
        return 1.0 - ratio if self._rtl else ratio

    def _bar_rect(self, activity, width):
        """The bar rectangle in widget coordinates (RTL-aware)."""
        start = _parse_date(activity["start_date"]) or self._start
        end = _parse_date(activity["end_date"]) or start
        left = self.NAME_WIDTH + self._ratio_for(start) * (width - self.NAME_WIDTH)
        right = self.NAME_WIDTH + self._ratio_for(end + datetime.timedelta(days=1)) * (width - self.NAME_WIDTH)
        return QRectF(min(left, right), 0, max(6.0, abs(right - left)), self.ROW_HEIGHT - 10)

    def _row_at(self, y):
        cursor = 2.0
        for kind, value in self._row_model:
            height = self.PHASE_HEIGHT if kind == "phase" else self.ROW_HEIGHT
            if cursor <= y <= cursor + height:
                return kind, value
            cursor += height
        return None

    # ------------------------------------------------------------------ #
    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.palette().window())
        colors = schedule_colors(constants.get_theme())
        width = self.width()

        # month bands behind everything (labels live in the header widget)
        paint_month_bands(painter, width, self.height(), self._start, self._end,
                          self.NAME_WIDTH, self._rtl, self._lang, with_labels=False)
        # separator between the name column and the timeline
        painter.fillRect(QRectF(self.NAME_WIDTH - 1, 0, 2, self.height()),
                         QColor(colors["accent_tint"]))

        today = datetime.date.today()
        if self._start <= today <= self._end:
            x = self.NAME_WIDTH + self._ratio_for(today) * (width - self.NAME_WIDTH)
            painter.setPen(QPen(QColor(colors["today"]), 2, Qt.DashLine))
            painter.drawLine(QPointF(x, 0), QPointF(x, self.height()))
            painter.setPen(QColor(colors["today"]))
            label_rect = QRectF(x + 4, 0, 90, 16) if not self._rtl else QRectF(x - 94, 0, 90, 16)
            painter.drawText(label_rect, Qt.AlignVCenter | Qt.AlignLeft, tr("schedule_today"))

        base_font = QFont(self.font())
        base_font.setPointSizeF(8.6)
        metrics = QFontMetrics(base_font)

        y = 2.0
        for kind, value in self._row_model:
            if kind == "phase":
                painter.fillRect(QRectF(0, y, width, self.PHASE_HEIGHT - 2),
                                 QColor(colors["accent_tint"]))
                painter.setPen(QColor(colors["phase"]))
                painter.setFont(base_font)
                painter.drawText(QRectF(8, y, width - 16, self.PHASE_HEIGHT - 2),
                                 Qt.AlignVCenter | (Qt.AlignRight if self._rtl else Qt.AlignLeft),
                                 value or "-")
                y += self.PHASE_HEIGHT
                continue

            activity = value
            if self._selected_id == activity["id"]:
                painter.fillRect(QRectF(0, y, width, self.ROW_HEIGHT),
                                 QColor(colors["accent_tint"]))

            painter.setFont(base_font)
            painter.setPen(QColor(colors["text"]))
            name = activity["name"] or ""
            if activity["milestone"]:
                name = "◆ " + name
            name_rect = QRectF(10, y, self.NAME_WIDTH - 24, self.ROW_HEIGHT)
            elided = metrics.elidedText(name, Qt.ElideRight, int(name_rect.width()))
            painter.drawText(name_rect,
                             Qt.AlignVCenter | (Qt.AlignRight if self._rtl else Qt.AlignLeft),
                             elided)

            # the bar, with the completed share filled in
            bar = self._bar_rect(activity, width)
            bar.moveTop(y + 5)
            progress = max(0, min(100, int(activity["progress"] or 0)))
            done_width = bar.width() * progress / 100.0

            painter.setPen(QPen(QColor(colors["done"]), 1))
            painter.setBrush(QBrush(QColor(colors["bar"])))
            painter.drawRoundedRect(bar, 4, 4)
            if done_width > 2:
                done_rect = (QRectF(bar.right() - done_width, bar.top(), done_width, bar.height())
                             if self._rtl else
                             QRectF(bar.left(), bar.top(), done_width, bar.height()))
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(QColor(colors["done"])))
                painter.drawRoundedRect(done_rect, 4, 4)

            painter.setPen(QColor(colors["text"]))
            text_rect = QRectF(bar.left() + 6, bar.top(), max(20.0, bar.width() - 12), bar.height())
            painter.drawText(text_rect,
                             Qt.AlignVCenter | (Qt.AlignLeft if self._rtl else Qt.AlignRight),
                             f"{progress}%")

            if activity["milestone"]:
                marker_x = bar.left() if self._rtl else bar.right()
                center_y = bar.center().y()
                size = 7.0
                painter.setBrush(QBrush(QColor(colors["milestone"])))
                painter.setPen(QPen(QColor(colors["milestone"]), 1))
                painter.drawPolygon(QPolygonF([
                    QPointF(marker_x - size / 2, center_y),
                    QPointF(marker_x, center_y - size / 2),
                    QPointF(marker_x + size / 2, center_y),
                    QPointF(marker_x, center_y + size / 2),
                ]))

            y += self.ROW_HEIGHT

        painter.end()

    # ------------------------------------------------------------------ #
    def mousePressEvent(self, event):
        row = self._row_at(event.position().y())
        if row and row[0] == "activity":
            self._selected_id = row[1]["id"]
            self.update()
            self.rowSelected.emit(self._selected_id)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        row = self._row_at(event.position().y())
        if row and row[0] == "activity":
            self._selected_id = row[1]["id"]
            self.update()
            self.activityDoubleClicked.emit(self._selected_id)
            return
        super().mouseDoubleClickEvent(event)


class SchedulePage(QWidget):
    """The project time schedule (Gantt) screen."""

    def __init__(self, db):
        super().__init__()
        self.db = db
        self.project = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        self.header = QLabel(tr("schedule_no_project"))
        self.header.setObjectName("breadcrumb")
        layout.addWidget(self.header)

        toolbar = QHBoxLayout()
        self.add_btn = QPushButton(tr("schedule_add"))
        self.add_btn.setObjectName("primaryButton")
        self.add_btn.clicked.connect(self._add_activity)
        self.edit_btn = QPushButton(tr("schedule_edit"))
        self.edit_btn.clicked.connect(self._edit_selected)
        self.delete_btn = QPushButton(tr("schedule_delete"))
        self.delete_btn.setObjectName("dangerButton")
        self.delete_btn.clicked.connect(self._delete_selected)
        self.up_btn = QPushButton(tr("schedule_move_up"))
        self.up_btn.clicked.connect(lambda: self._move(-1))
        self.down_btn = QPushButton(tr("schedule_move_down"))
        self.down_btn.clicked.connect(lambda: self._move(+1))
        self.export_btn = QPushButton(tr("schedule_export"))
        self.export_btn.clicked.connect(self._export_excel)
        for widget in (self.add_btn, self.edit_btn, self.delete_btn, self.up_btn,
                       self.down_btn, self.export_btn):
            toolbar.addWidget(widget)
        toolbar.addStretch()
        self.summary_label = QLabel("")
        self.summary_label.setObjectName("breadcrumb")
        toolbar.addWidget(self.summary_label)
        layout.addLayout(toolbar)

        self.timeline = GanttTimeline()
        self.timeline.rowSelected.connect(lambda _id: self._refresh_buttons())
        self.timeline.activityDoubleClicked.connect(lambda _id: self._edit_selected())
        self.timeline_header = TimelineHeader()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.timeline)
        scroll.setFrameShape(QFrame.NoFrame)
        layout.addWidget(scroll, 1)

        self._reload()

    # ------------------------------------------------------------------ #
    def open_project(self, project_id):
        """Called by the main window when a project is opened."""
        self.project = self.db.get_project(project_id)
        self._reload()

    def reload(self):
        self._reload()

    def _is_rtl(self):
        return self.layoutDirection() == Qt.RightToLeft

    def _refresh_buttons(self):
        has_project = self.project is not None
        has_selection = self.timeline.selected_activity_id() is not None
        self.add_btn.setEnabled(has_project)
        self.export_btn.setEnabled(has_project)
        for widget in (self.edit_btn, self.delete_btn, self.up_btn, self.down_btn):
            widget.setEnabled(has_project and has_selection)

    def _reload(self):
        rtl = self._is_rtl()
        lang = i18n.get_language()
        if self.project is None:
            self.header.setText(tr("schedule_no_project"))
            self.timeline.set_model([], rtl, lang)
        else:
            self.header.setText(f"{tr('schedule')}: {self.project['name']}")
            activities = list(self.db.get_schedule_activities(self.project["id"]))
            self.timeline.set_model(activities, rtl, lang)
            days = 0
            starts = [d for d in (_parse_date(a["start_date"]) for a in activities) if d]
            ends = [d for d in (_parse_date(a["end_date"]) for a in activities) if d]
            if starts and ends:
                days = (max(ends) - min(starts)).days
            self.summary_label.setText(
                tr("schedule_summary").format(count=len(activities), days=days))
        self.timeline_header.set_model(self.timeline._start, self.timeline._end,
                                       GanttTimeline.NAME_WIDTH, rtl, lang)
        self._refresh_buttons()

    # ------------------------------------------------------------------ #
    def _ask_activity(self, activity=None):
        phases = sorted({(a["phase"] or "").strip()
                         for a in self.db.get_schedule_activities(self.project["id"])} - {""})
        dialog = ScheduleActivityDialog(
            self, activity=activity, phases=phases,
            project_id=self.project["id"], db=self.db,
            default_start=QDate.currentDate(),
        )
        if dialog.exec() != ScheduleActivityDialog.Accepted:
            return None
        return dialog

    def _add_activity(self):
        if self.project is None:
            return
        dialog = self._ask_activity()
        if dialog is None:
            return
        values = dialog.values()
        self.db.add_schedule_activity(self.project["id"], values["name"],
                                      phase=values["phase"],
                                      start_date=values["start_date"],
                                      end_date=values["end_date"],
                                      progress=values["progress"],
                                      milestone=values["milestone"],
                                      notes=values["notes"])
        self._reload()

    def _edit_selected(self):
        activity = self.timeline.selected_activity()
        if activity is None:
            QMessageBox.information(self, tr("schedule_edit"), tr("schedule_no_selection"))
            return
        dialog = self._ask_activity(activity)
        if dialog is None:
            return
        self.db.update_schedule_activity(activity["id"], **dialog.values())
        self._reload()

    def _delete_selected(self):
        activity = self.timeline.selected_activity()
        if activity is None:
            return
        confirm = QMessageBox.question(
            self, tr("schedule_delete"),
            f"{tr('schedule_delete_confirm')}\n{activity['name']}")
        if confirm == QMessageBox.Yes:
            self.db.delete_schedule_activity(activity["id"])
            self._reload()

    def _move(self, direction):
        if self.project is None:
            return
        activity_id = self.timeline.selected_activity_id()
        if activity_id is None:
            return
        self.db.move_schedule_activity(self.project["id"], activity_id, direction)
        self._reload()
        self.timeline._selected_id = activity_id
        self.timeline.update()
        self._refresh_buttons()

    def _export_excel(self):
        if self.project is None:
            return
        activities = list(self.db.get_schedule_activities(self.project["id"]))
        if not activities:
            QMessageBox.information(self, tr("schedule_export"), tr("schedule_empty"))
            return
        default_name = f"schedule_{self.project['project_number'] or self.project['id']}.xlsx"
        path, _ = QFileDialog.getSaveFileName(self, tr("schedule_export"),
                                              default_name, "Excel (*.xlsx)")
        if not path:
            return
        try:
            _write_schedule_excel(activities, self.project["name"], path,
                                  "ar" if self._is_rtl() else "en")
        except Exception as exc:  # noqa: BLE001 - report it, never crash
            QMessageBox.critical(self, tr("schedule_export"), str(exc))
            return
        QMessageBox.information(self, tr("schedule_export"),
                                f"{tr('export_done')}\n{path}")
