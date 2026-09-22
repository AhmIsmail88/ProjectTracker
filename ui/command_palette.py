"""
ui/command_palette.py
Ctrl+K "Command Console" palette: one box to jump to any project, any item
across every project, or run a common action — without hunting through the
sidebar first.

It deliberately reuses the very same database query the "Search All
Projects" dialog uses (Database.search_items_across_projects), so the two
surfaces can never disagree about what matches.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QFrame, QGraphicsDropShadowEffect
)
from PySide6.QtCore import Qt, Signal, QTimer, QPoint
from PySide6.QtGui import QColor

from i18n import tr


#: action ids the palette can emit through action_requested
ACTION_ADD_ITEM = "add_item"
ACTION_EXPORT_PDF = "export_pdf"
ACTION_SEARCH_ALL = "search_all"
ACTION_TOGGLE_THEME = "toggle_theme"
ACTION_TOGGLE_LANGUAGE = "toggle_language"

_ACTION_LABELS = [
    (ACTION_ADD_ITEM, "palette_action_add_item"),
    (ACTION_EXPORT_PDF, "palette_action_export_pdf"),
    (ACTION_SEARCH_ALL, "palette_action_search_all"),
    (ACTION_TOGGLE_THEME, "palette_action_toggle_theme"),
    (ACTION_TOGGLE_LANGUAGE, "palette_action_toggle_language"),
]

KIND_GROUP = 0
KIND_ITEM = 1
KIND_PROJECT = 2
KIND_ACTION = 3


class CommandPalette(QDialog):
    """Frameless quick-open palette.

    Signals:
      item_chosen(project_id, item_id) - an item result was picked
      project_chosen(project_id)       - a project result was picked
      action_requested(action_id)      - a command row was picked
    """

    item_chosen = Signal(int, int)
    project_chosen = Signal(int)
    action_requested = Signal(str)

    def __init__(self, parent, db):
        super().__init__(parent)
        self.db = db
        self._has_project_open = False

        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMinimumWidth(520)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self.panel = QFrame()
        self.panel.setObjectName("commandPalette")
        outer.addWidget(self.panel)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(48)
        shadow.setOffset(0, 14)
        shadow.setColor(QColor(0, 0, 0, 170))
        self.panel.setGraphicsEffect(shadow)

        body = QVBoxLayout(self.panel)
        body.setContentsMargins(12, 8, 12, 10)
        body.setSpacing(2)

        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("paletteSearch")
        self.search_edit.setPlaceholderText(tr("palette_placeholder"))
        self.search_edit.textChanged.connect(self._schedule_refresh)
        self.search_edit.installEventFilter(self)
        body.addWidget(self.search_edit)

        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet("background-color: rgba(128,128,128,0.25); border: none;")
        body.addWidget(divider)

        self.list_widget = QListWidget()
        self.list_widget.setObjectName("paletteList")
        self.list_widget.setUniformItemSizes(True)
        self.list_widget.itemActivated.connect(self._activate)
        self.list_widget.itemClicked.connect(self._activate)
        body.addWidget(self.list_widget, 1)

        hint = QHBoxLayout()
        self.hint_label = QLabel(tr("palette_hint"))
        self.hint_label.setObjectName("breadcrumb")
        hint.addWidget(self.hint_label)
        hint.addStretch()
        body.addLayout(hint)

        # Debounce: the item search scans every item of every project.
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(200)
        self._search_timer.timeout.connect(self._refresh)

        self._items = []
        self._projects = []

    # ------------------------------------------------------------------ #
    def set_context(self, has_project_open):
        """The palette offers "Add item"/"Export PDF" only when a project
        is actually open, so the command list never lies about what is
        currently possible."""
        self._has_project_open = bool(has_project_open)

    def open_palette(self):
        self._load_sources()
        self.search_edit.clear()
        self._refresh()
        self._show_centered()
        self.search_edit.setFocus()

    def _show_centered(self):
        parent = self.parentWidget()
        if parent is not None and parent.isVisible():
            top_left = parent.mapToGlobal(QPoint(0, 0))
            x = top_left.x() + max(0, (parent.width() - self.width()) // 2)
            y = top_left.y() + 90
            self.move(x, y)
        self.show()

    # ------------------------------------------------------------------ #
    def _load_sources(self):
        try:
            self._projects = list(self.db.get_projects())
        except Exception:
            self._projects = []

    def _schedule_refresh(self, _text):
        self._search_timer.start()

    def _add_row(self, kind, text, payload, subtitle=""):
        item = QListWidgetItem(text)
        item.setData(Qt.UserRole, (kind, payload))
        item.setFlags(item.flags() & ~Qt.ItemIsSelectable if kind == KIND_GROUP
                      else item.flags() | Qt.ItemIsSelectable)
        self.list_widget.addItem(item)
        return item

    def _refresh(self):
        query = self.search_edit.text().strip()
        self.list_widget.clear()
        q = query.lower()

        # ---- projects ----
        project_matches = [p for p in self._projects
                           if not q or q in (p["name"] or "").lower()
                           or q in (p["project_number"] or "").lower()]
        if project_matches:
            self._add_row(KIND_GROUP, tr("palette_group_projects"), None)
            for p in project_matches[:8]:
                number = p["project_number"] or ""
                label = f"{p['name']}    {number}" if number else p["name"]
                self._add_row(KIND_PROJECT, label, p["id"])

        # ---- items (only worth querying with a real query) ----
        item_matches = []
        if len(query) >= 2:
            try:
                fields = [key for key, _label in self.db.SEARCHABLE_ITEM_FIELDS]
                item_matches = self.db.search_items_across_projects(
                    query, fields=fields, project_ids=None, mode="include"
                )
            except Exception:
                item_matches = []
        self._items = item_matches
        if item_matches:
            self._add_row(KIND_GROUP, tr("palette_group_items"), None)
            for r in item_matches[:12]:
                label = f"{r['item_name']}    ·    {r['project_name']}"
                self._add_row(KIND_ITEM, label, (r["project_id"], r["id"]))

        # ---- actions ----
        actions = []
        for action_id, key in _ACTION_LABELS:
            if action_id in (ACTION_ADD_ITEM, ACTION_EXPORT_PDF) and not self._has_project_open:
                continue
            label = tr(key)
            if q and q not in label.lower():
                continue
            actions.append((action_id, label))
        if actions:
            self._add_row(KIND_GROUP, tr("palette_group_actions"), None)
            for action_id, label in actions:
                self._add_row(KIND_ACTION, label, action_id)

        if self.list_widget.count() == 0:
            self._add_row(KIND_GROUP, tr("palette_no_results"), None)
        else:
            self._select_first_selectable()

    def _select_first_selectable(self):
        for row in range(self.list_widget.count()):
            entry = self.list_widget.item(row)
            if entry.data(Qt.UserRole)[0] != KIND_GROUP:
                self.list_widget.setCurrentRow(row)
                return

    # ------------------------------------------------------------------ #
    def eventFilter(self, obj, event):
        if obj is self.search_edit and event.type() == event.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key_Down, Qt.Key_Up):
                self._move_selection(1 if key == Qt.Key_Down else -1)
                return True
            if key in (Qt.Key_Return, Qt.Key_Enter):
                self._activate_current()
                return True
            if key == Qt.Key_Escape:
                self.close()
                return True
        return super().eventFilter(obj, event)

    def _move_selection(self, step):
        count = self.list_widget.count()
        if count == 0:
            return
        row = self.list_widget.currentRow()
        for _ in range(count):
            row = (row + step) % count
            entry = self.list_widget.item(row)
            if entry is not None and entry.data(Qt.UserRole)[0] != KIND_GROUP:
                self.list_widget.setCurrentRow(row)
                return

    def _activate_current(self):
        entry = self.list_widget.currentItem()
        if entry is not None:
            self._activate(entry)

    def _activate(self, entry):
        payload = entry.data(Qt.UserRole)
        if not payload:
            return
        kind, value = payload
        if kind == KIND_ITEM:
            project_id, item_id = value
            self.close()
            self.item_chosen.emit(project_id, item_id)
        elif kind == KIND_PROJECT:
            self.close()
            self.project_chosen.emit(value)
        elif kind == KIND_ACTION:
            self.close()
            self.action_requested.emit(value)
