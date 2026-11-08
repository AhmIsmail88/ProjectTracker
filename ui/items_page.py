"""
ui/items_page.py
The "Tracker" screen for a single project: items table (BOQ), filters,
attachments, manual reordering, and the export/reports section.
"""

from i18n import tr_text

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox,
    QPushButton, QTableWidget, QTableWidgetItem, QAbstractItemView,
    QMessageBox, QMenu, QFileDialog, QTabWidget, QDialog, QListWidget,
    QListWidgetItem, QStyle, QInputDialog, QCheckBox
)
from PySide6.QtGui import QColor, QShortcut, QKeySequence
from PySide6.QtCore import Qt, Signal, QThread, QItemSelectionModel

from constants import STATUS_OPTIONS, STATUS_COLORS, STATUS_TEXT_COLORS, is_over_supplied, \
    OVER_SUPPLY_COLOR, OVER_SUPPLY_TEXT, remaining_to_request, remaining_to_deliver, \
    is_delivered_without_request, DELIVERED_NO_REQUEST_COLOR, DELIVERED_NO_REQUEST_TEXT, \
    is_over_requested, OVER_REQUEST_COLOR, OVER_REQUEST_TEXT, \
    status_chip_colors, special_chip_colors, warning_chip_colors
from ui.dialogs import ItemDialog, AttachmentsDialog
from ui.bulk_edit_dialog import BulkEditDialog
from ui.find_replace_dialog import FindReplaceDialog
from ui.table_utils import (
    NumericTableWidgetItem, configure_interactive_table, make_separator,
    ExportWorker as _ExportWorker, reset_table_layout,
)
from ui.activity_widget import ActivityListWidget, ActivityDialog
from i18n import tr
import config as app_config
import math
from collections import defaultdict
from ui.project_picker import ProjectPicker
from ui.widgets import FlowLayout
import auth

ITEM_COLUMNS = [
    "#", "Item Name", "Pump Station / Area", "Supplier", "Unit", "Currency",
    "Total Qty", "Requested Qty", "Delivered Qty", "Remaining to Request",
    "Remaining to Deliver", "Unit Cost", "Total Cost", "PR/PO", "Status",
]
COL_SORT = ITEM_COLUMNS.index("#")
COL_STATUS = ITEM_COLUMNS.index("Status")
COL_ITEM_NAME = ITEM_COLUMNS.index("Item Name")
COL_AREA = ITEM_COLUMNS.index("Pump Station / Area")
COL_SUPPLIER = ITEM_COLUMNS.index("Supplier")
COL_TOTAL_COST = ITEM_COLUMNS.index("Total Cost")
COL_UNIT_COST = ITEM_COLUMNS.index("Unit Cost")
COL_REQUESTED_QTY = ITEM_COLUMNS.index("Requested Qty")
COL_DELIVERED_QTY = ITEM_COLUMNS.index("Delivered Qty")
COL_PRPO = ITEM_COLUMNS.index("PR/PO")
INLINE_EDITABLE_COLS = {COL_UNIT_COST, COL_REQUESTED_QTY, COL_DELIVERED_QTY}
INLINE_EDIT_FIELD_BY_COL = {
    COL_UNIT_COST: "unit_cost",
    COL_REQUESTED_QTY: "requested_quantity",
    COL_DELIVERED_QTY: "delivered_quantity",
}
NUMERIC_COLS = {
    ITEM_COLUMNS.index(c) for c in
    ("#", "Total Qty", "Requested Qty", "Delivered Qty", "Remaining to Request",
     "Remaining to Deliver", "Unit Cost", "Total Cost")
}
AREA_REPEAT_MUTED_COLOR = "#94A3B8"  # dims an Area cell that just repeats the row above it


class DeletedItemsDialog(QDialog):
    def __init__(self, parent, db, project_id, on_change=None, read_only=False):
        super().__init__(parent)
        self.db = db
        self.project_id = project_id
        self.on_change = on_change
        self.read_only = read_only
        self.setWindowTitle(tr_text("Deleted Items"))
        self.setMinimumSize(720, 420)

        layout = QVBoxLayout(self)
        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget)

        btn_row = QHBoxLayout()
        self.restore_btn = QPushButton(tr("undo"))
        self.restore_btn.clicked.connect(self._restore_selected)
        self.purge_btn = QPushButton(tr_text("Delete Forever"))
        self.purge_btn.setObjectName("dangerButton")
        self.purge_btn.clicked.connect(self._purge_selected)
        if read_only:
            self.restore_btn.setEnabled(False)
            self.purge_btn.setEnabled(False)
            self.restore_btn.setToolTip(tr_text("View only"))
            self.purge_btn.setToolTip(tr_text("View only"))
        elif not auth.is_manager(db):
            # Permanent deletion cannot be undone: managers only. Engineers
            # can still restore items in their own projects.
            self.purge_btn.setEnabled(False)
            self.purge_btn.setToolTip(tr_text("Managers only"))
        close_btn = QPushButton(tr_text("Close"))
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(self.restore_btn)
        btn_row.addWidget(self.purge_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self._reload()

    def _reload(self):
        self.list_widget.clear()
        with self.db._connect() as conn:
            rows = conn.execute(
                "SELECT id, item_name, deleted_at FROM items WHERE project_id = ? AND is_deleted = 1 ORDER BY deleted_at DESC",
                (self.project_id,),
            ).fetchall()
        for r in rows:
            item = QListWidgetItem(f"{tr_text('deleted')} ⁦{r['deleted_at']}⁩  —  {r['item_name']}")
            item.setToolTip(r["item_name"])
            item.setData(Qt.UserRole, r["id"])
            self.list_widget.addItem(item)

    def _selected_id(self):
        current = self.list_widget.currentItem()
        if not current:
            QMessageBox.information(self, "No selection", "Select an item first.")
            return None
        return current.data(Qt.UserRole)

    def _restore_selected(self):
        if self.read_only or not auth.can_edit_project(self.db, self.project_id):
            return
        iid = self._selected_id()
        if iid is None:
            return
        self.db.restore_item(iid)
        self._reload()
        if self.on_change:
            self.on_change()

    def _purge_selected(self):
        if (self.read_only or not auth.is_manager(self.db)
                or not auth.can_edit_project(self.db, self.project_id)):
            return
        iid = self._selected_id()
        if iid is None:
            return
        confirm = QMessageBox.question(self, "Delete forever", "This cannot be undone. Continue?")
        if confirm == QMessageBox.Yes and auth.is_manager(self.db):
            self.db.purge_item(iid)
            self._reload()
            if self.on_change:
                self.on_change()


class TrackerPage(QWidget):
    back_requested = Signal()
    project_requested = Signal(int)

    def __init__(self, db, undo_bar, parent=None):
        super().__init__(parent)
        self.db = db
        self.undo_bar = undo_bar
        self.project = None
        self._editable = False
        self._export_worker = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 10, 14, 10)

        # ---- Header: breadcrumb line, then title + subtitle + back ----
        self.breadcrumb_label = QLabel()
        self.breadcrumb_label.setObjectName("breadcrumb")
        context_row = QHBoxLayout()
        context_row.addWidget(self.breadcrumb_label, 1)
        self.project_picker = ProjectPicker(db)
        self.project_picker.project_requested.connect(self.project_requested)
        context_row.addWidget(self.project_picker)
        outer.addLayout(context_row)

        header_row = QHBoxLayout()
        heading = QVBoxLayout()
        heading.setSpacing(3)
        self.title_label = QLabel()
        self.title_label.setObjectName("pageTitle")
        self.title_label.setWordWrap(True)
        self.title_label.setTextFormat(Qt.PlainText)
        heading.addWidget(self.title_label)

        self.subtitle_label = QLabel()
        self.subtitle_label.setObjectName("breadcrumb")
        self.subtitle_label.setTextFormat(Qt.PlainText)
        self.subtitle_label.setWordWrap(True)
        heading.addWidget(self.subtitle_label)
        header_row.addLayout(heading, 1)

        back_btn = QPushButton(tr("back_to_projects"))
        back_btn.clicked.connect(self.back_requested.emit)
        header_row.addWidget(back_btn, 0, Qt.AlignTop)
        outer.addLayout(header_row)

        self.tabs = QTabWidget()
        outer.addWidget(self.tabs)
        self.tabs.addTab(self._build_items_tab(), tr("items_tracker"))
        self.tabs.addTab(self._build_reports_tab(), tr("reports"))
        self.activity_view = ActivityListWidget(self.db)
        self.tabs.addTab(self.activity_view, tr("activity"))
        self.tabs.currentChanged.connect(self._on_tab_changed)

        QShortcut(QKeySequence("Ctrl+N"), self, self._add_item)
        QShortcut(QKeySequence("Ctrl+E"), self, self._edit_item)
        QShortcut(QKeySequence("Delete"), self, self._delete_item)
        QShortcut(QKeySequence("Ctrl+D"), self, self._duplicate_item)
        QShortcut(QKeySequence("Alt+Up"), self, lambda: self._move_item(-1))
        QShortcut(QKeySequence("Alt+Down"), self, lambda: self._move_item(1))
        QShortcut(QKeySequence("Ctrl+Alt+Up"), self, lambda: self._move_to_edge(True))
        QShortcut(QKeySequence("Ctrl+Alt+Down"), self, lambda: self._move_to_edge(False))
        QShortcut(QKeySequence("Ctrl+G"), self, self._move_to_position)

    # ------------------------------------------------------------ #
    def open_project(self, project_id, select_item_id=None):
        changed_project = self.project is not None and self.project["id"] != project_id
        self.project = self.db.get_project(project_id)
        self.project_picker.set_project(project_id)
        if changed_project:
            self._clear_filters()
        self.title_label.setText(self.project["name"])
        self.title_label.setToolTip(self.project["name"])
        self.breadcrumb_label.setText(f"{tr('projects')}  \u203a  {self.project['name']}")
        bits = [b for b in [self.project["project_number"], self.project["location"], self.project["contractor"]] if b]
        self.subtitle_label.setText("  \u2022  ".join(bits))
        if select_item_id is not None:
            self.tabs.setCurrentIndex(0)  # make sure the Items tab is what's shown
            self._clear_filters()  # a stale filter from a previous project could hide the target item
        self.reload_items(select_item_id=select_item_id)
        self._apply_permissions()
        if self.tabs.currentIndex() == 2:
            self.activity_view.load(project_id=self.project["id"])

    # ------------------------------------------------------------------ #
    # External entry points (command palette / theme changes)
    # ------------------------------------------------------------------ #
    def add_item_from_palette(self):
        """Public entry point used by the Ctrl+K command palette."""
        self._add_item()

    def export_pdf_from_palette(self):
        """Public entry point used by the Ctrl+K command palette."""
        self._export_pdf()

    def on_theme_changed(self):
        """Re-applies the directly-painted cell colors (status chips and the
        amber warning highlights) after a theme switch. Those are cell
        brushes rather than stylesheet rules, so without this the table would
        keep the previous theme's chip colors until it happened to be
        rebuilt. Scroll position and selection are preserved."""
        if self.project is None:
            return
        selected = self._selected_item_ids()
        scroll = self.items_table.verticalScrollBar().value()
        self.reload_items(select_item_ids=selected or None)
        self.items_table.verticalScrollBar().setValue(scroll)

    def _on_tab_changed(self, index):
        if index == 2 and self.project is not None:
            self.activity_view.load(project_id=self.project["id"])

    # ---------------------------------------------------------------
    # Items tab
    # ---------------------------------------------------------------
    def _build_items_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        filter_row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(tr("search_items"))
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._apply_filters)

        self.status_filter = QComboBox()
        self.status_filter.addItem(tr("all_statuses"), None)
        for status in STATUS_OPTIONS:
            self.status_filter.addItem(tr_text(status), status)
        self.status_filter.currentIndexChanged.connect(self._apply_filters)

        self.supplier_filter = QComboBox()
        self.supplier_filter.addItem(tr("all_suppliers"))
        self.supplier_filter.currentIndexChanged.connect(self._apply_filters)

        self.area_filter = QComboBox()
        self.area_filter.addItem(tr("all_areas"))
        self.area_filter.currentIndexChanged.connect(self._apply_filters)

        self.missing_cost_check = QCheckBox(tr_text("\u26A0 Missing Unit Cost only"))
        self.missing_cost_check.setToolTip(
            tr_text("Show only items where Unit Cost is 0 (or blank) — useful when filling in pricing data.")
        )
        self.missing_cost_check.stateChanged.connect(self._apply_filters)

        self.missing_prpo_check = QCheckBox(tr_text("\u26A0 Missing PR/PO only"))
        self.missing_prpo_check.setToolTip(
            tr_text("Show only items missing a PR and/or PO attachment — useful when chasing down documentation.")
        )
        self.missing_prpo_check.stateChanged.connect(self._apply_filters)

        filter_row.addWidget(self.search_edit, 3)
        filter_row.addWidget(self.status_filter, 1)
        self.advanced_filters_btn = QPushButton(tr_text("More Filters"))
        self.advanced_filters_btn.setCheckable(True)
        filter_row.addWidget(self.advanced_filters_btn)
        self.view_combo = QComboBox()
        self.view_combo.setAccessibleName(tr_text("Table View"))
        for key, label in (("all", "All Columns"), ("delivery", "Delivery"),
                           ("costs", "Costs"), ("documents", "Documents")):
            self.view_combo.addItem(tr_text(label), key)
        filter_row.addWidget(self.view_combo)
        layout.addLayout(filter_row)
        self.advanced_filters_panel = QWidget()
        advanced_row = QHBoxLayout(self.advanced_filters_panel)
        advanced_row.setContentsMargins(0, 0, 0, 0)
        advanced_row.addWidget(self.supplier_filter, 1)
        advanced_row.addWidget(self.area_filter, 1)
        advanced_row.addWidget(self.missing_cost_check)
        advanced_row.addWidget(self.missing_prpo_check)
        self.advanced_filters_panel.setVisible(False)
        self.advanced_filters_btn.toggled.connect(self.advanced_filters_panel.setVisible)
        layout.addWidget(self.advanced_filters_panel)
        self.filter_chips = QWidget()
        self.filter_chips_layout = FlowLayout(self.filter_chips)
        self.filter_chips_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.filter_chips)

        btn_row = QHBoxLayout()

        # -- Group 1: edit --
        self.add_btn = QPushButton(tr("add_item"))
        self.add_btn.setObjectName("primaryButton")
        self.add_btn.setToolTip("Ctrl+N")
        self.add_btn.clicked.connect(self._add_item)

        self.edit_btn = QPushButton(tr("edit_item"))
        self.edit_btn.setToolTip("Ctrl+E")
        self.edit_btn.clicked.connect(self._edit_item)

        self.attach_btn = QPushButton(tr("attachments"))
        self.attach_btn.clicked.connect(self._open_attachments)

        for w in (self.add_btn, self.edit_btn, self.attach_btn):
            btn_row.addWidget(w)
        # -- Group 2: selection actions (shown only while rows are selected) --
        # Kept inside the same command row so the toolbar stays one tidy
        # line and the table does not jump down when a selection appears.
        self.selection_bar = QWidget()
        selection_actions = QHBoxLayout(self.selection_bar)
        selection_actions.setContentsMargins(0, 0, 0, 0)
        selection_actions.addWidget(make_separator())
        self.selection_label = QLabel()
        selection_actions.addWidget(self.selection_label)
        self._selection_buttons = []
        for label, callback in (("Duplicate", self._duplicate_item), ("Bulk Edit", None),
                                ("Move", None), ("Delete", self._delete_item)):
            button = QPushButton(tr_text(label))
            if callback:
                button.clicked.connect(callback)
            else:
                # Each popup belongs to its visible button. Sharing a menu with
                # a submenu or a discarded button can prevent it from opening.
                factory = self._create_bulk_edit_menu if label == "Bulk Edit" else self._create_move_menu
                button.setMenu(factory(button))
            if label == "Delete":
                button.setObjectName("dangerButton")
            self._selection_buttons.append(button)
            selection_actions.addWidget(button)
        self.selection_bar.hide()
        btn_row.addWidget(self.selection_bar)
        self.readonly_label = QLabel(tr_text("View only"))
        self.readonly_label.setObjectName("breadcrumb")
        self.readonly_label.setToolTip(tr_text("This project is view-only for you - you can view it and export reports, but not change its data."))
        self.readonly_label.hide()
        btn_row.addWidget(self.readonly_label)
        btn_row.addStretch()
        more_btn = QPushButton(tr_text("More Actions"))
        more_menu = QMenu(more_btn)
        self.history_action = more_menu.addAction(tr("history"), self._open_item_history)
        self.history_action.setEnabled(False)
        more_menu.addSeparator()
        more_menu.addAction(tr("trash"), self._open_deleted_items)
        more_btn.setMenu(more_menu)
        btn_row.addWidget(more_btn)
        layout.addLayout(btn_row)

        self.items_table = QTableWidget()
        self.items_table.setColumnCount(len(ITEM_COLUMNS))
        self.items_table.setHorizontalHeaderLabels([tr_text(label) for label in ITEM_COLUMNS])
        # Double-click or start typing to edit — but only Unit Cost /
        # Requested / Delivered Qty are actually editable (see
        # _populate_items_table, which strips the editable flag from
        # every other cell). Everything else stays read-only via
        # Edit Item, same as before.
        self.items_table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.items_table.itemChanged.connect(self._on_cell_edited)
        self._populating_table = False
        self.items_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.items_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.items_table.setAlternatingRowColors(True)
        configure_interactive_table(self.items_table, first_col_width=40, allow_row_drag=False,
                                     layout_key="items_table")
        # The '#' column already shows the item number - the row-header
        # column would just repeat the same values next to it.
        self.items_table.verticalHeader().setVisible(False)
        # # and Item Name are core identity columns of this screen and must
        # ALWAYS be visible. A saved layout from the short-lived (and since
        # withdrawn) frozen-columns build could hide them - so discard such
        # a poisoned layout outright and force both columns visible.
        if (self.items_table.isColumnHidden(COL_ITEM_NAME)
                or self.items_table.isColumnHidden(COL_SORT)):
            app_config.clear_table_layout("items_table")
            reset_table_layout(self.items_table, "items_table", default_column_width=240)
        self.items_table.setColumnHidden(COL_SORT, False)
        self.items_table.setColumnHidden(COL_ITEM_NAME, False)
        if not app_config.load_table_layout("items_table"):
            # First run (or the user never rearranged this table) — give
            # Item Name more breathing room than the generic default.
            self.items_table.setColumnWidth(COL_ITEM_NAME, 240)
        saved_view = app_config.load_items_view()
        self.view_combo.setCurrentIndex(max(0, self.view_combo.findData(saved_view)))
        self.view_combo.currentIndexChanged.connect(self._apply_table_view)
        self._apply_table_view()

        self.items_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.items_table.customContextMenuRequested.connect(self._show_items_context_menu)
        self.items_table.doubleClicked.connect(lambda _i: self._edit_item())
        for key in (Qt.Key_Return, Qt.Key_Enter):
            enter_sc = QShortcut(QKeySequence(key), self.items_table)
            enter_sc.setContext(Qt.WidgetShortcut)  # only fires while the table itself has focus
            enter_sc.activated.connect(self._edit_item)
        # Re-apply filters/hidden-row state and the area-repeat dimming
        # whenever the user re-sorts by clicking a column header — both
        # are computed from the table's current row order.
        self.items_table.horizontalHeader().sortIndicatorChanged.connect(lambda *_: self._apply_filters())
        layout.addWidget(self.items_table, 1)
        self.items_table.itemSelectionChanged.connect(self._update_selection_ui)

        status_row = QHBoxLayout()
        self.items_summary_label = QLabel()
        self.items_summary_label.setObjectName("breadcrumb")
        status_row.addWidget(self.items_summary_label, 1)
        self.clear_filters_btn = QPushButton(tr_text("\u2715 Clear Filters"))
        self.clear_filters_btn.setVisible(False)
        self.clear_filters_btn.clicked.connect(self._clear_filters)
        status_row.addWidget(self.clear_filters_btn)
        layout.addLayout(status_row)

        hint = QLabel(
            tr_text("Ctrl/Shift+Click to select multiple rows. Duplicate now inserts copies right next to the "
            "original. For long lists: Top/Bottom (Ctrl+Alt+\u2191/\u2193) or Move to\u2026 (Ctrl+G) jumps "
            "instantly instead of stepping through every row.")
        )
        hint.setObjectName("breadcrumb")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._apply_permissions()

        return widget

    def _can_edit(self):
        """True when the signed-in user may change data in the open project."""
        return (self.project is not None
                and auth.can_edit_project(self.db, self.project["id"]))

    def _apply_permissions(self):
        """Reflect the current user's rights on every edit entry point."""
        editable = self._can_edit()
        self._editable = editable
        readonly_tip = tr_text(
            "This project is view-only for you - you can view it and export reports, but not change its data.")
        for button in (getattr(self, "add_btn", None), getattr(self, "edit_btn", None)):
            if button is not None:
                button.setEnabled(editable)
                button.setToolTip("Ctrl+N" if editable and button is getattr(self, "add_btn", None)
                                  else "Ctrl+E" if editable else readonly_tip)
        if getattr(self, "attach_btn", None) is not None:
            # Attachments stay openable for reading, even in view-only mode.
            self.attach_btn.setEnabled(self.project is not None)
        for button in getattr(self, "_selection_buttons", []):
            button.setEnabled(editable)
        if getattr(self, "readonly_label", None) is not None:
            self.readonly_label.setVisible(self.project is not None and not editable)
        triggers = (QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
                    if editable else QAbstractItemView.NoEditTriggers)
        if hasattr(self, "items_table"):
            self.items_table.setEditTriggers(triggers)
        if not editable and getattr(self, "selection_bar", None) is not None:
            self.selection_bar.hide()

    def _update_selection_ui(self, *_):
        if self._populating_table:
            return
        ids = self._selected_item_ids()
        self.selection_label.setText(tr_text("{count} items selected").format(count=len(ids)))
        self.selection_bar.setVisible(bool(ids) and getattr(self, "_editable", False))
        self.history_action.setEnabled(len(ids) == 1)

    def _update_filter_chips(self):
        while self.filter_chips_layout.count():
            child = self.filter_chips_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        active = []
        if self.search_edit.text().strip():
            active.append((tr_text("Search") + ": " + self.search_edit.text().strip(), self.search_edit.clear))
        for combo, label in ((self.status_filter, "Status"), (self.supplier_filter, "Supplier"), (self.area_filter, "Area")):
            if combo.currentIndex() > 0:
                active.append((tr_text(label) + ": " + combo.currentText(), lambda _checked=False, c=combo: c.setCurrentIndex(0)))
        for check in (self.missing_cost_check, self.missing_prpo_check):
            if check.isChecked():
                active.append((check.text(), lambda _checked=False, c=check: c.setChecked(False)))
        for caption, callback in active:
            chip = QPushButton(self.fontMetrics().elidedText(caption, Qt.ElideRight, 240) + " ×")
            chip.setObjectName("filterChip")
            chip.setToolTip(caption + "\n" + tr_text("Remove this filter"))
            chip.clicked.connect(callback)
            self.filter_chips_layout.addWidget(chip)
        self.filter_chips.setVisible(bool(active))

    def _apply_table_view(self, *_):
        view = self.view_combo.currentData()
        columns = {
            "delivery": {"#", "Item Name", "Pump Station / Area", "Supplier", "Unit", "Total Qty",
                         "Requested Qty", "Delivered Qty", "Remaining to Deliver", "Status"},
            "costs": {"#", "Item Name", "Supplier", "Unit", "Currency", "Total Qty", "Unit Cost", "Total Cost"},
            "documents": {"#", "Item Name", "Supplier", "Requested Qty", "Delivered Qty", "PR/PO", "Status"},
        }.get(view, set(ITEM_COLUMNS))
        for col, name in enumerate(ITEM_COLUMNS):
            self.items_table.setColumnHidden(col, name not in columns)
        app_config.save_items_view(view)

    def _create_bulk_edit_menu(self, parent):
        menu = QMenu(parent)
        menu.addAction(tr_text("Edit Fields…"), self._bulk_edit)
        menu.addAction(tr_text("Find & Replace…"), self._find_replace)
        return menu

    def _create_move_menu(self, parent):
        menu = QMenu(parent)
        menu.addAction(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowUp),
                       tr("move_up") + "\tAlt+↑", lambda: self._move_item(-1))
        menu.addAction(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowDown),
                       tr("move_down") + "\tAlt+↓", lambda: self._move_item(1))
        menu.addSeparator()
        menu.addAction(tr_text("⇞ Move to Top\tCtrl+Alt+↑"), lambda: self._move_to_edge(True))
        menu.addAction(tr_text("⇠ Move to Bottom\tCtrl+Alt+↓"), lambda: self._move_to_edge(False))
        menu.addAction(tr_text("🎯 Move to Position…\tCtrl+G"), self._move_to_position)
        return menu

    def _show_items_context_menu(self, pos):
        menu = QMenu(self)
        add_action = menu.addAction(tr("add_item"))
        edit_action = menu.addAction(tr("edit_item"))
        dup_action = menu.addAction(tr("duplicate"))
        bulk_edit_action = menu.addAction(tr_text("\u270E Bulk Edit\u2026"))
        find_replace_action = menu.addAction(tr_text("\U0001F504 Find & Replace\u2026"))
        delete_action = menu.addAction(tr("delete_item"))
        menu.addSeparator()
        up_action = menu.addAction(tr("move_up"))
        down_action = menu.addAction(tr("move_down"))
        top_action = menu.addAction(tr_text("\u21DE Move to Top"))
        bottom_action = menu.addAction(tr_text("\u21E0 Move to Bottom"))
        goto_action = menu.addAction(tr_text("\U0001F3AF Move to Position\u2026"))
        menu.addSeparator()
        attach_action = menu.addAction(tr("attachments"))
        history_action = menu.addAction(tr("history"))
        menu.addSeparator()
        reset_cols_action = menu.addAction(tr_text("\u21BA Reset Columns to Default"))
        if not self._can_edit():
            for action_item in (add_action, edit_action, dup_action, bulk_edit_action,
                                find_replace_action, delete_action, up_action, down_action,
                                top_action, bottom_action, goto_action):
                action_item.setEnabled(False)

        action = menu.exec(self.items_table.mapToGlobal(pos))
        if action == add_action:
            self._add_item()
        elif action == edit_action:
            self._edit_item()
        elif action == dup_action:
            self._duplicate_item()
        elif action == bulk_edit_action:
            self._bulk_edit()
        elif action == find_replace_action:
            self._find_replace()
        elif action == delete_action:
            self._delete_item()
        elif action == up_action:
            self._move_item(-1)
        elif action == down_action:
            self._move_item(1)
        elif action == top_action:
            self._move_to_edge(True)
        elif action == bottom_action:
            self._move_to_edge(False)
        elif action == goto_action:
            self._move_to_position()
        elif action == attach_action:
            self._open_attachments()
        elif action == reset_cols_action:
            reset_table_layout(self.items_table, "items_table", default_column_width=240)
        elif action == history_action:
            self._open_item_history()

    def _refresh_supplier_filter(self):
        self.supplier_filter.blockSignals(True)
        current_text = self.supplier_filter.currentText()
        self.supplier_filter.clear()
        self.supplier_filter.addItem(tr("all_suppliers"))
        for s in self.db.get_suppliers():
            self.supplier_filter.addItem(s["name"])
        idx = self.supplier_filter.findText(current_text)
        self.supplier_filter.setCurrentIndex(max(idx, 0))
        self.supplier_filter.blockSignals(False)

    def _refresh_area_filter(self, items):
        """Populated from the distinct Pump Station / Area values actually
        present on this project's items (no separate areas table exists)."""
        self.area_filter.blockSignals(True)
        current_text = self.area_filter.currentText()
        areas = sorted({(it["pump_station"] or "").strip() for it in items if (it["pump_station"] or "").strip()})
        self.area_filter.clear()
        self.area_filter.addItem(tr("all_areas"))
        for area in areas:
            self.area_filter.addItem(area)
        idx = self.area_filter.findText(current_text)
        self.area_filter.setCurrentIndex(max(idx, 0))
        self.area_filter.blockSignals(False)

    def reload_items(self, select_item_id=None, select_item_ids=None):
        if self.project is None:
            return
        self._refresh_supplier_filter()
        items = self.db.get_items(self.project["id"])
        self._refresh_area_filter(items)
        attachment_categories = self.db.get_item_attachment_categories(self.project["id"])
        self._populate_items_table(items, attachment_categories)
        self._apply_filters()
        ids_to_select = select_item_ids or ([select_item_id] if select_item_id is not None else None)
        if ids_to_select:
            self._select_rows_by_item_ids(ids_to_select)
        self._apply_permissions()

    @staticmethod
    def _make_numeric_cell(val, col):
        """A numeric table cell that sorts by its real value and displays
        formatted with thousands separators (whole numbers for '#')."""
        cell = NumericTableWidgetItem(val, decimals=0 if col == COL_SORT else 2)
        cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        return cell

    @staticmethod
    def _style_status_cell(cell, it):
        """Applies the computed warning/color treatment to a Status cell.
        Single styling path shared by full table population and targeted
        in-place row refreshes, so the two can never drift apart. Colors are
        theme-aware: the light theme keeps the original pastel chips, the
        dark theme uses the deep-tinted equivalents."""
        total = it["total_quantity"] or 0
        requested = it["requested_quantity"] or 0
        delivered = it["delivered_quantity"] or 0
        over = is_over_supplied(total, delivered)
        delivered_no_request = is_delivered_without_request(requested, delivered)
        over_requested = is_over_requested(total, requested)
        tooltip_parts = []
        if over:
            bg, fg = special_chip_colors("over_supply")
            cell.setText(f"{tr_text(it['status'])} \u26A0")
            tooltip_parts.append("Delivered quantity exceeds Total quantity.")
        elif delivered_no_request:
            bg, fg = special_chip_colors("no_request")
            cell.setText(f"{tr_text(it['status'])} \u26A0")
            tooltip_parts.append(
                "Delivered quantity is recorded but nothing was ever requested for this item."
            )
        elif over_requested:
            bg, fg = special_chip_colors("over_request")
            cell.setText(f"{tr_text(it['status'])} \u26A0")
            tooltip_parts.append("Requested quantity exceeds Total quantity.")
        else:
            bg, fg = status_chip_colors(it["status"])
            cell.setText(tr_text(it["status"]))
        cell.setData(Qt.UserRole, it["status"])
        cell.setBackground(QColor(bg))
        cell.setForeground(QColor(fg))
        if it["variance_note"]:
            tooltip_parts.append(it["variance_note"])
        if tooltip_parts:
            cell.setToolTip("\n".join(tooltip_parts))



    def _row_for_item_id(self, item_id):
        """The on-screen row currently holding this item id (stable under
        sorting/filtering - identity lives in the row's Item Name cell)."""
        for row in range(self.items_table.rowCount()):
            name_item = self.items_table.item(row, COL_ITEM_NAME)
            if name_item and name_item.data(Qt.UserRole) == item_id:
                return row
        return None

    def _refresh_row_after_inline_edit(self, item_id):
        """After an in-table edit, updates only this item's affected cells
        (quantities, remaining, total cost, computed status colors) instead
        of rebuilding the entire table - keeps scroll position, the current
        sort order and keyboard focus intact on big projects. Falls back to
        a full reload whenever anything is not exactly as expected."""
        it = self.db.get_item(item_id)
        row = self._row_for_item_id(item_id) if it is not None else None
        if it is None or row is None:
            self.reload_items(select_item_id=item_id)
            return

        total = it["total_quantity"] or 0
        requested = it["requested_quantity"] or 0
        delivered = it["delivered_quantity"] or 0

        self._populating_table = True
        sorting = self.items_table.isSortingEnabled()
        self.items_table.setSortingEnabled(False)
        try:
            updates = {
                COL_REQUESTED_QTY: requested,
                COL_DELIVERED_QTY: delivered,
                COL_UNIT_COST: it["unit_cost"] or 0,
                ITEM_COLUMNS.index("Remaining to Request"): remaining_to_request(total, requested),
                ITEM_COLUMNS.index("Remaining to Deliver"): remaining_to_deliver(total, delivered),
                COL_TOTAL_COST: total * (it["unit_cost"] or 0),
            }
            for col, val in updates.items():
                cell = self._make_numeric_cell(val, col)
                if col in INLINE_EDITABLE_COLS:
                    cell.setFlags(cell.flags() | Qt.ItemIsEditable)
                    cell.setToolTip(tr_text("Double-click or press F2 to edit directly"))
                else:
                    cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
                self.items_table.setItem(row, col, cell)

            status_cell = QTableWidgetItem(it["status"])
            self._style_status_cell(status_cell, it)
            self.items_table.setItem(row, COL_STATUS, status_cell)

            unit_cost_cell = self.items_table.item(row, COL_UNIT_COST)
            if not (it["unit_cost"] or 0):
                _warn_bg, _warn_fg = warning_chip_colors("missing_cost")
                unit_cost_cell.setBackground(QColor(_warn_bg))
                unit_cost_cell.setForeground(QColor(_warn_fg))
                unit_cost_cell.setToolTip(
                    tr_text("No unit cost entered yet \u2014 double-click or press F2 to fill it in")
                )
        finally:
            self.items_table.setSortingEnabled(sorting)
            self._populating_table = False

        self._update_items_summary()

    def _populate_items_table(self, items, attachment_categories=None):
        attachment_categories = attachment_categories or {}
        self._populating_table = True
        self.items_table.setSortingEnabled(False)
        self.items_table.setRowCount(len(items))

        for row, it in enumerate(items):
            total = it["total_quantity"] or 0
            requested = it["requested_quantity"] or 0
            delivered = it["delivered_quantity"] or 0
            total_cost = total * (it["unit_cost"] or 0)
            over = is_over_supplied(total, delivered)
            delivered_no_request = is_delivered_without_request(requested, delivered)
            over_requested = is_over_requested(total, requested)

            categories = attachment_categories.get(it["id"], set())
            has_pr = "PR" in categories
            has_po = "PO" in categories
            if has_pr and has_po:
                prpo_text = "\u2713 PR, PO"
            elif has_pr:
                prpo_text = "\u26A0 PR only"
            elif has_po:
                prpo_text = "\u26A0 PO only"
            else:
                prpo_text = "\u26A0 Missing"

            field_values = {
                "#": it["sort_order"] or (row + 1),
                "Status": it["status"],
                "Item Name": it["item_name"],
                "Pump Station / Area": it["pump_station"],
                "Supplier": it["supplier_name"] or "-",
                "Unit": it["unit"],
                "Currency": it["currency"] or (self.project["currency"] if self.project else "-") or "-",
                "Total Qty": total,
                "Requested Qty": requested,
                "Delivered Qty": delivered,
                "Remaining to Request": remaining_to_request(total, requested),
                "Remaining to Deliver": remaining_to_deliver(total, delivered),
                "Unit Cost": it["unit_cost"] or 0,
                "Total Cost": total_cost,
                "PR/PO": prpo_text,
            }

            for col, col_name in enumerate(ITEM_COLUMNS):
                val = field_values[col_name]
                if col in NUMERIC_COLS:
                    cell = self._make_numeric_cell(val, col)
                else:
                    cell = QTableWidgetItem(str(val))
                    cell.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)

                if col in INLINE_EDITABLE_COLS:
                    cell.setFlags(cell.flags() | Qt.ItemIsEditable)
                    cell.setToolTip(tr_text("Double-click or press F2 to edit directly"))
                else:
                    cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)

                if col == COL_ITEM_NAME:
                    cell.setData(Qt.UserRole, it["id"])

                if col == COL_STATUS:
                    self._style_status_cell(cell, it)

                if col == COL_UNIT_COST and not (it["unit_cost"] or 0):
                    _warn_bg, _warn_fg = warning_chip_colors("missing_cost")
                    cell.setBackground(QColor(_warn_bg))
                    cell.setForeground(QColor(_warn_fg))
                    cell.setToolTip(tr_text("No unit cost entered yet \u2014 double-click or press F2 to fill it in"))

                if col == COL_PRPO and not (has_pr and has_po):
                    _warn_bg, _warn_fg = warning_chip_colors("missing_prpo")
                    cell.setBackground(QColor(_warn_bg))
                    cell.setForeground(QColor(_warn_fg))
                    cell.setToolTip(tr_text("Open Attachments to add the missing PR/PO document"))

                self.items_table.setItem(row, col, cell)

        self.items_table.setSortingEnabled(True)
        self.items_table.sortItems(COL_SORT, Qt.AscendingOrder)
        self._populating_table = False
        # Auto-fit every row's height to its (possibly wrapped) content —
        # so long item names/remarks are fully readable without having to
        # double-click each row's border one at a time.
        self.items_table.resizeRowsToContents()
        self._update_items_summary()

    def _selected_item_ids(self):
        """All item ids currently selected (multi-row selection aware),
        in their current on-screen top-to-bottom order."""
        rows = sorted({idx.row() for idx in self.items_table.selectedIndexes()})
        ids = []
        for row in rows:
            if self.items_table.isRowHidden(row):
                continue
            name_item = self.items_table.item(row, COL_ITEM_NAME)
            if name_item:
                ids.append(name_item.data(Qt.UserRole))
        return ids

    def _select_rows_by_item_ids(self, item_ids):
        """Re-selects every row whose item id is in *item_ids* (used after
        an operation like Add/Duplicate/Move so the result stays
        selected, even though row positions may have changed after a
        reload) and gives the table keyboard focus, so Enter opens it
        immediately without first having to click it with the mouse."""
        if not item_ids:
            return
        id_set = set(item_ids)
        selection_model = self.items_table.selectionModel()
        selection_model.clearSelection()
        first_item = None
        for row in range(self.items_table.rowCount()):
            name_item = self.items_table.item(row, COL_ITEM_NAME)
            if name_item and name_item.data(Qt.UserRole) in id_set and not self.items_table.isRowHidden(row):
                if first_item is None:
                    first_item = name_item
                selection_model.select(
                    self.items_table.model().index(row, 0),
                    QItemSelectionModel.Select | QItemSelectionModel.Rows,
                )
        if first_item is not None:
            self.items_table.scrollToItem(first_item)
            self.items_table.setCurrentItem(first_item, QItemSelectionModel.NoUpdate)
            self.items_table.setFocus()

    def _apply_filters(self):
        search_text = self.search_edit.text().strip().lower()
        status_filter = self.status_filter.currentData()
        supplier_filter = self.supplier_filter.currentText()
        area_filter = self.area_filter.currentText()
        missing_cost_only = self.missing_cost_check.isChecked()
        missing_prpo_only = self.missing_prpo_check.isChecked()

        visible_count = 0
        total_cost_visible = 0.0
        value_by_currency = defaultdict(float)
        last_visible_area = None

        for row in range(self.items_table.rowCount()):
            name_item = self.items_table.item(row, COL_ITEM_NAME)
            area_item = self.items_table.item(row, COL_AREA)
            status_item = self.items_table.item(row, COL_STATUS)
            supplier_item = self.items_table.item(row, COL_SUPPLIER)
            cost_item = self.items_table.item(row, COL_UNIT_COST)
            prpo_item = self.items_table.item(row, COL_PRPO)

            if not name_item:
                continue

            show = True
            if search_text and search_text not in (name_item.text() or "").lower():
                show = False
            if show and status_filter is not None:
                status_text = status_item.data(Qt.UserRole) if status_item else ""
                if status_text != status_filter:
                    show = False
            if show and supplier_filter != tr("all_suppliers"):
                if (supplier_item.text() if supplier_item else "") != supplier_filter:
                    show = False
            if show and area_filter != tr("all_areas"):
                if (area_item.text() if area_item else "") != area_filter:
                    show = False
            if show and missing_cost_only:
                cost_val = cost_item._value if isinstance(cost_item, NumericTableWidgetItem) else 0
                if cost_val:
                    show = False
            if show and missing_prpo_only:
                complete = bool(prpo_item and prpo_item.text().startswith("\u2713"))
                if complete:
                    show = False

            self.items_table.setRowHidden(row, not show)
            if not show:
                self.items_table.selectionModel().select(self.items_table.model().index(row, 0),
                                                        QItemSelectionModel.Deselect | QItemSelectionModel.Rows)

            if show:
                visible_count += 1
                cost_item = self.items_table.item(row, COL_TOTAL_COST)
                if cost_item and isinstance(cost_item, NumericTableWidgetItem):
                    total_cost_visible += cost_item._value
                    currency_cell = self.items_table.item(row, ITEM_COLUMNS.index("Currency"))
                    value_by_currency[currency_cell.text() if currency_cell else "—"] += cost_item._value

                # Dim an Area cell that just repeats the row above it — the
                # same text row after row after row is noise, not signal,
                # especially with hundreds of items grouped by area.
                if area_item:
                    area_text = area_item.text()
                    if area_text and area_text == last_visible_area:
                        area_item.setForeground(QColor(AREA_REPEAT_MUTED_COLOR))
                    else:
                        area_item.setData(Qt.ForegroundRole, None)
                    last_visible_area = area_text

        total_rows = self.items_table.rowCount()
        filter_active = (
            bool(search_text) or status_filter is not None
            or supplier_filter != tr("all_suppliers") or area_filter != tr("all_areas")
            or missing_cost_only or missing_prpo_only
        )
        self.clear_filters_btn.setVisible(filter_active)
        extra_active = (supplier_filter != tr("all_suppliers") or area_filter != tr("all_areas")
                        or missing_cost_only or missing_prpo_only)
        self.advanced_filters_btn.setText(tr_text("More Filters") + (" •" if extra_active else ""))
        totals = " · ".join(f"{amount:,.2f} {currency}" for currency, amount in sorted(value_by_currency.items())) or "—"

        if total_rows == 0:
            self.items_summary_label.setText(tr_text("No items"))
        elif visible_count == total_rows:
            self.items_summary_label.setText(tr_text("Showing all {count} items | Total cost: {cost}").format(count=total_rows, cost=totals))
        else:
            self.items_summary_label.setText(
                tr_text("Showing {visible} of {count} items | Filtered cost: {cost}").format(visible=visible_count, count=total_rows, cost=totals)
            )
        self.items_summary_label.setWordWrap(True)
        self._update_filter_chips()
        self._update_selection_ui()

    def _clear_filters(self):
        self.search_edit.clear()
        self.status_filter.setCurrentIndex(0)
        self.supplier_filter.setCurrentIndex(0)
        self.area_filter.setCurrentIndex(0)
        self.missing_cost_check.setChecked(False)
        self.missing_prpo_check.setChecked(False)

    def _update_items_summary(self):
        self._apply_filters()

    def _current_item_id(self):
        row = self.items_table.currentRow()
        if (row < 0 or self.items_table.isRowHidden(row)
                or not self.items_table.selectionModel().isRowSelected(row)):
            QMessageBox.information(self, "No item selected", "Select an item first.")
            return None
        name_item = self.items_table.item(row, COL_ITEM_NAME)
        return name_item.data(Qt.UserRole) if name_item else None

    def _on_cell_edited(self, cell):
        if not self._can_edit():
            return
        """Handles a direct in-table edit of Unit Cost / Requested Qty /
        Delivered Qty (double-click or F2 to edit, matching an Excel-like
        workflow) — everything else stays read-only via Edit Item."""
        if self._populating_table:
            return  # our own repopulation triggers itemChanged too; ignore those

        col = cell.column()
        if col not in INLINE_EDITABLE_COLS:
            return

        row = cell.row()
        name_item = self.items_table.item(row, COL_ITEM_NAME)
        item_id = name_item.data(Qt.UserRole) if name_item else None
        if item_id is None:
            return

        text = (cell.text() or "").strip().replace(",", "")
        try:
            value = float(text)
        except ValueError:
            QMessageBox.warning(self, "Invalid value", "Enter a number (e.g. 12.5).")
            self.reload_items(select_item_id=item_id)  # revert the cell back to its real value
            return
        if not math.isfinite(value) or value < 0:
            QMessageBox.warning(self, "Invalid value", "Enter a finite, non-negative number.")
            self.reload_items(select_item_id=item_id)
            return

        field = INLINE_EDIT_FIELD_BY_COL[col]
        current = self.db.get_item(item_id)

        # Same business rule as the Edit Item dialog: a delivered quantity
        # above the total requires a short variance note (the dialog
        # refuses to save without one; inline editing must not become a
        # loophole around it).
        if (
            field == "delivered_quantity"
            and value > (current["total_quantity"] or 0) + 1e-9
            and not (current["variance_note"] or "").strip()
        ):
            note, ok = QInputDialog.getText(
                self, "Over-supply note required",
                f"Delivered ({value:g}) exceeds Total ({current['total_quantity'] or 0:g}).\n"
                f"Add a short note explaining the over-supply:",
            )
            if not ok or not note.strip():
                self.reload_items(select_item_id=item_id)  # revert the cell
                return
            self.db.update_item(item_id, delivered_quantity=value, variance_note=note.strip())
            self._refresh_row_after_inline_edit(item_id)
            return

        self.db.update_item(item_id, **{field: value})
        self._refresh_row_after_inline_edit(item_id)

    def _add_item(self):
        if not self._can_edit():
            return
        if self.project is None:
            return
        suppliers = self.db.get_suppliers()
        dlg = ItemDialog(self, suppliers=suppliers, db=self.db, default_currency=self.project["currency"])
        if dlg.exec() and self._can_edit():
            new_id = self.db.add_item(self.project["id"], **dlg.get_data())
            self._clear_filters()  # a stale filter (status/missing-cost/etc.) could hide the new item
            self.reload_items(select_item_id=new_id)

    def _edit_item(self):
        if not self._can_edit():
            return
        item_id = self._current_item_id()
        if item_id is None:
            return
        item = self.db.get_item(item_id)
        suppliers = self.db.get_suppliers()
        dlg = ItemDialog(self, item=item, suppliers=suppliers, db=self.db, default_currency=self.project["currency"])
        if dlg.exec() and self._can_edit():
            self.db.update_item(item_id, **dlg.get_data())
            self.reload_items(select_item_id=item_id)

    def _duplicate_item(self):
        if not self._can_edit():
            return
        item_ids = self._selected_item_ids()
        if not item_ids:
            QMessageBox.information(self, "No item selected", "Select at least one item first.")
            return
        new_ids = self.db.duplicate_items(self.project["id"], item_ids)
        self._clear_filters()  # a stale filter could hide the newly duplicated item(s)
        self.reload_items(select_item_ids=new_ids)

    def _bulk_edit(self):
        if not self._can_edit():
            return
        item_ids = self._selected_item_ids()
        if not item_ids:
            QMessageBox.information(self, "No items selected",
                                     "Select two or more items to bulk-edit (Ctrl/Shift+Click).")
            return
        dlg = BulkEditDialog(self, self.db, item_ids,
                              default_currency=self.project["currency"] if self.project else "SAR")
        if dlg.exec():
            self.reload_items(select_item_ids=item_ids)

    def _find_replace(self):
        if not self._can_edit():
            return
        item_ids = self._selected_item_ids()
        if not item_ids:
            QMessageBox.information(self, "No items selected",
                                     "Select one or more items to find & replace within "
                                     "(Ctrl/Shift+Click for several).")
            return
        dlg = FindReplaceDialog(self, self.db, item_ids)
        if dlg.exec():
            self.reload_items(select_item_ids=item_ids)

    def _delete_item(self):
        if not self._can_edit():
            return
        # Delete EVERY selected row (the shortcut reference promises
        # "Delete selected item(s)"), not just the row under the cursor.
        item_ids = self._selected_item_ids()
        if not item_ids:
            cur = self._current_item_id()
            item_ids = [cur] if cur is not None else []
        if not item_ids:
            return
        items = []
        for iid in item_ids:
            it = self.db.get_item(iid)
            if it is not None:
                items.append(it)
        if not items:
            return
        for it in items:
            self.db.delete_item(it["id"])
        self.reload_items()

        def _undo():
            project = self.db.get_project(items[0]["project_id"])
            if project is not None and project["is_deleted"]:
                # The project went to the trash after these items were
                # deleted: tie them to it so they return with the project.
                if auth.is_manager(self.db):
                    for it in items:
                        self.db.restore_item(it["id"])
                    QMessageBox.information(self, tr("undo"), tr_text(
                        "The item will come back when its project is restored from the trash."))
                return
            if not auth.can_edit_items(self.db, [it["id"] for it in items]):
                return
            for it in items:
                self.db.restore_item(it["id"])
            self.reload_items()

        names = ", ".join(it["item_name"] for it in items[:3])
        if len(items) > 3:
            names += f" (+{len(items) - 3} more)"
        self.undo_bar.show_message(f"{len(items)} item(s) deleted: {names}.", _undo)

    def _move_item(self, direction):
        if not self._can_edit():
            return
        item_ids = self._selected_item_ids()
        if not item_ids or self.project is None:
            return
        if len(item_ids) == 1:
            self.db.move_item(self.project["id"], item_ids[0], direction)
        else:
            self.db.move_items_group(self.project["id"], item_ids, direction)
        self.reload_items(select_item_ids=item_ids)

    def _move_to_edge(self, to_top):
        if not self._can_edit():
            return
        item_ids = self._selected_item_ids()
        if not item_ids or self.project is None:
            QMessageBox.information(self, "No item selected", "Select at least one item first.")
            return
        self.db.move_items_to_edge(self.project["id"], item_ids, to_top)
        self.reload_items(select_item_ids=item_ids)

    def _move_to_position(self):
        if not self._can_edit():
            return
        item_ids = self._selected_item_ids()
        if not item_ids or self.project is None:
            QMessageBox.information(self, "No item selected", "Select at least one item first.")
            return
        total = self.items_table.rowCount()
        current_item = self.db.get_item(item_ids[0])
        current_pos = current_item["sort_order"] if current_item else 1
        target, ok = QInputDialog.getInt(
            self, "Move to Position",
            f"Move {'these ' + str(len(item_ids)) + ' items' if len(item_ids) > 1 else 'this item'} "
            f"to row #  (1\u2013{total}):",
            value=current_pos, minValue=1, maxValue=max(total, 1),
        )
        if not ok or not self._can_edit():
            return
        self.db.move_items_to_position(self.project["id"], item_ids, target)
        self.reload_items(select_item_ids=item_ids)

    def _open_attachments(self):
        item_id = self._current_item_id()
        if item_id is None:
            return
        item = self.db.get_item(item_id)
        dlg = AttachmentsDialog(self, self.db, item_id, item["item_name"], read_only=not self._can_edit())
        dlg.exec()
        self.reload_items(select_item_id=item_id)  # PR/PO column may have changed

    def _open_item_history(self):
        item_id = self._current_item_id()
        if item_id is None:
            return
        item = self.db.get_item(item_id)
        dlg = ActivityDialog(self, self.db, f"{tr('history')} \u2014 {item['item_name']}",
                              entity_type="item", entity_id=item_id)
        dlg.exec()

    def _open_deleted_items(self):
        if self.project is None:
            return
        dlg = DeletedItemsDialog(self, self.db, self.project["id"], on_change=self.reload_items, read_only=not self._can_edit())
        dlg.exec()

    # ---------------------------------------------------------------
    # Reports tab
    # ---------------------------------------------------------------
    def _build_reports_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(QLabel(tr_text("<b>Export the currently selected project as a professional report.</b>")))

        self.excel_btn = QPushButton(tr("export_excel"))
        self.excel_btn.clicked.connect(self._export_excel)
        self.pdf_btn = QPushButton(tr("export_pdf"))
        self.pdf_btn.clicked.connect(self._export_pdf)

        layout.addWidget(self.excel_btn)
        layout.addWidget(self.pdf_btn)

        layout.addSpacing(10)
        layout.addWidget(QLabel(
            tr_text("<b>Export filtered view</b> \u2014 use the search box / status / supplier filters on the "
            "Items tab to narrow the list down to what you want, then export exactly that.")
        ))
        self.filtered_btn = QPushButton(tr_text("\U0001F4E5 Export Filtered View to Excel"))
        self.filtered_btn.clicked.connect(self._export_filtered_excel)
        layout.addWidget(self.filtered_btn)

        layout.addStretch()
        return widget

    def _run_export(self, button, original_text, export_fn, success_text):
        """Runs export_fn() (a zero-arg callable) on a background thread so
        the UI stays responsive, disabling *button* and showing a busy
        label on it in the meantime instead of freezing with no feedback."""
        if self._export_worker is not None and self._export_worker.isRunning():
            return
        for export_button in (self.excel_btn, self.pdf_btn, self.filtered_btn):
            export_button.setEnabled(False)
        button.setText("\u23F3 Exporting\u2026")

        worker = _ExportWorker(export_fn)

        def _on_ok():
            QMessageBox.information(self, "Done", success_text)

        def _on_err(err):
            QMessageBox.critical(self, "Export failed", err)

        def _on_finished():
            for export_button in (self.excel_btn, self.pdf_btn, self.filtered_btn):
                export_button.setEnabled(True)
            button.setText(original_text)
            self._export_worker = None

        worker.finished_ok.connect(_on_ok)
        worker.finished_err.connect(_on_err)
        worker.finished.connect(_on_finished)
        self._export_worker = worker  # keep a reference so it isn't garbage-collected mid-run
        worker.start()

    def _export_excel(self):
        if self.project is None:
            return
        default_name = f"{self.project['name']}.xlsx"
        path, _ = QFileDialog.getSaveFileName(self, "Save Excel report", default_name, "Excel Files (*.xlsx)")
        if not path:
            return
        from export.excel_export import export_project_to_excel
        db, project_id = self.db, self.project["id"]
        self._run_export(
            self.excel_btn, tr("export_excel"),
            lambda: export_project_to_excel(db, project_id, path),
            f"Excel report saved:\n{path}",
        )

    def _export_pdf(self):
        if self.project is None:
            return
        default_name = f"{self.project['name']}.pdf"
        path, _ = QFileDialog.getSaveFileName(self, "Save PDF report", default_name, "PDF Files (*.pdf)")
        if not path:
            return
        from export.pdf_export import export_project_to_pdf
        db, project_id = self.db, self.project["id"]
        self._run_export(
            self.pdf_btn, tr("export_pdf"),
            lambda: export_project_to_pdf(db, project_id, path),
            f"PDF report saved:\n{path}",
        )

    def _export_filtered_excel(self):
        """Exports exactly the items currently visible in the Items tab
        (after the search box / status filter / supplier filter are
        applied) — a plain, deterministic alternative to AI grouping:
        filter with the existing controls, then export what you see."""
        if self.project is None:
            return
        visible_item_ids = []
        for row in range(self.items_table.rowCount()):
            if not self.items_table.isRowHidden(row):
                visible_item_ids.append(self.items_table.item(row, COL_ITEM_NAME).data(Qt.UserRole))
        if not visible_item_ids:
            QMessageBox.information(
                self, "No items",
                "No items match the current filter (search/status/supplier) on the Items tab. "
                "Adjust the filters there first."
            )
            return

        default_name = f"{self.project['name']} - Filtered.xlsx"
        path, _ = QFileDialog.getSaveFileName(self, "Save filtered Excel report", default_name, "Excel Files (*.xlsx)")
        if not path:
            return
        from export.excel_export import export_project_to_excel
        db, project_id = self.db, self.project["id"]
        original_text = "\U0001F4E5 Export Filtered View to Excel"
        self._run_export(
            self.filtered_btn, original_text,
            lambda: export_project_to_excel(db, project_id, path, item_ids=visible_item_ids),
            f"Filtered Excel report saved ({len(visible_item_ids)} item(s)):\n{path}",
        )
