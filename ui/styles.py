"""
ui/styles.py
Theme for Project Tracker.

Palette follows the company logo: layered navy surfaces with a brighter
blue accent in dark mode and a deeper blue on white surfaces in light
mode. Both the dark and the light theme are built from the same
token set, so the two modes stay visually consistent.

The stylesheet is a %(token)s template because two details genuinely
depend on the interface language and cannot be expressed with Qt's
stylesheet language alone:
  * nav_align      - QSS `text-align` is physical, so the sidebar labels
                     must be right-aligned for Arabic and left-aligned for
                     English.
  * sidebar_edge   - the sidebar's separator must face the content area,
                     which is its LEFT edge under Arabic (RTL) and its
                     RIGHT edge under English (LTR).
Both are substituted at runtime by get_stylesheet().
"""

# --------------------------------------------------------------------------- #
# Design tokens
# --------------------------------------------------------------------------- #
DARK_TOKENS = {
    "bg": "#0F172A",
    "panel": "#162236",
    "panel2": "#1B293E",
    "panel3": "#23344C",
    "sidebar_bg": "#111C2F",
    "table_bg": "#152135",
    "table_alt": "#1A2A40",
    "header_bg": "#23344C",
    "hover": "#253A55",
    "border": "#3A4E69",
    "border_soft": "#2A3B53",
    "grid": "#2A3B53",
    "text": "#EFF5FF",
    "text2": "#CED9EA",
    "muted": "#A1B2C9",
    "faint": "#91A4BF",
    "accent": "#62B5F8",
    "accent_hover": "#8CCCFF",
    "accent_deep": "#268BD2",
    "accent_tint": "#1C3E5B",
    "accent_tint2": "#2B5B7A",
    "on_accent": "#081B2C",
    "ok": "#2FCC8F",
    "warn": "#F0B33E",
    "danger": "#F26D6D",
    "danger_bg": "#3A1B22",
    "danger_border": "#5C2632",
    "purple": "#A78BFA",
    "warn_bg": "#33280F",
    "warn_border": "#6B5216",
    "bad_bg": "#331A1E",
    "bad_border": "#6B2733",
    "field_bg": "#111F33",
    "field_focus_bg": "#1B304B",
    "sel_bg": "#254C70",
    "sel_text": "#F3F8FF",
    "logo_plate": "#FFFFFF",
    "logo_plate_border": "#E2E9F4",
    "scroll": "#405877",
    "scroll_hover": "#577498",
    "tooltip_bg": "#23344C",
    "overlay": "rgba(4,8,15,0.55)",
}

LIGHT_TOKENS = {
    "bg": "#F1F4F8",
    "panel": "#FFFFFF",
    "panel2": "#F8FAFD",
    "panel3": "#EAF0F7",
    "sidebar_bg": "#E7EEF7",
    "table_bg": "#FFFFFF",
    "table_alt": "#F4F7FB",
    "header_bg": "#E7EEF7",
    "hover": "#EAF2FC",
    "border": "#C7D4E4",
    "border_soft": "#D7E1ED",
    "grid": "#E0E7F0",
    "text": "#16263B",
    "text2": "#354A63",
    "muted": "#526782",
    "faint": "#637793",
    "accent": "#1268AD",
    "accent_hover": "#0D568F",
    "accent_deep": "#0B4C83",
    "accent_tint": "#DBEBFB",
    "accent_tint2": "#ADCDEC",
    "on_accent": "#FFFFFF",
    "ok": "#0E9F6E",
    "warn": "#B26E05",
    "danger": "#D64545",
    "danger_bg": "#FDECEC",
    "danger_border": "#F3C4C4",
    "purple": "#7C5CD6",
    "warn_bg": "#FFF7E8",
    "warn_border": "#F2D9A8",
    "bad_bg": "#FDECEC",
    "bad_border": "#F3C4C4",
    "field_bg": "#FFFFFF",
    "field_focus_bg": "#FFFFFF",
    "sel_bg": "#D7EAFE",
    "sel_text": "#133B63",
    "logo_plate": "#FFFFFF",
    "logo_plate_border": "#E2E9F4",
    "scroll": "#A9BCD4",
    "scroll_hover": "#849DBD",
    "tooltip_bg": "#FFFFFF",
    "overlay": "rgba(16,28,48,0.35)",
}


_TEMPLATE = """
/* ---------- base ---------- */
QMainWindow, QDialog {
    background-color: %(bg)s;
    color: %(text)s;
}
QWidget {
    font-family: 'Cairo', 'Segoe UI', Tahoma, sans-serif;
    font-size: 14px;
    color: %(text)s;
}

/* ---------- sidebar shell ---------- */
QWidget#sidebar {
    background-color: %(sidebar_bg)s;
    border-%(sidebar_edge)s: 1px solid %(border_soft)s;
}
QLabel#logoLabel {
    /* Light plate: the logo art is dark navy, so it stays readable on a
       light chip in BOTH themes. */
    background-color: %(logo_plate)s;
    border: 1px solid %(logo_plate_border)s;
    border-radius: 10px;
    padding: 6px 12px;
}
QLabel#sideSection {
    color: %(faint)s;
    font-size: 12px;
    font-weight: 700;
    padding: 12px 12px 4px 12px;
    letter-spacing: 1px;
}

QPushButton#navButton {
    /* Bold in EVERY state: switching 500->700 on the active state made
       bold text render wider than a button sized from the regular hint,
       clipping the last letter. */
    text-align: %(nav_align)s;
    padding: 8px 12px;
    border-radius: 9px;
    background-color: transparent;
    border: 1px solid transparent;
    font-weight: 600;
    color: %(muted)s;
}
QPushButton#hamburgerButton {
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 5px;
}
QPushButton#hamburgerButton:hover {
    background-color: %(hover)s;
    border-color: %(border)s;
}
QPushButton#navButton:hover {
    background-color: %(hover)s;
    color: %(text2)s;
}
QPushButton#navButton:checked {
    background-color: %(accent_tint)s;
    color: %(accent)s;
    border: 1px solid %(accent_tint2)s;
}

QSplitter::handle {
    background-color: %(border_soft)s;
}

/* ---------- typography ---------- */
QLabel { color: %(text2)s; }
QLabel#pageTitle {
    font-size: 18px;
    font-weight: 700;
    color: %(text)s;
    letter-spacing: -0.2px;
}
QLabel#breadcrumb {
    color: %(muted)s;
    font-size: 12.5px;
}

/* ---------- buttons ---------- */
QPushButton {
    background-color: %(panel2)s;
    color: %(text2)s;
    border: 1px solid %(border)s;
    border-radius: 9px;
    padding: 6px 12px;
    font-weight: 600;
}
QPushButton:hover {
    background-color: %(hover)s;
    color: %(text)s;
    border-color: %(border)s;
}
QPushButton:pressed { background-color: %(panel3)s; }
QPushButton:disabled {
    background-color: %(panel2)s;
    color: %(faint)s;
    border-color: %(border_soft)s;
}

QPushButton#primaryButton {
    background-color: %(accent)s;
    color: %(on_accent)s;
    border: 1px solid %(accent)s;
    font-weight: 700;
}
QPushButton#primaryButton:hover {
    color: %(on_accent)s;
    background-color: %(accent_hover)s;
    border-color: %(accent_hover)s;
}
QPushButton#primaryButton:disabled {
    background-color: %(panel3)s;
    color: %(faint)s;
    border-color: %(border_soft)s;
}

QPushButton#dangerButton {
    background-color: %(danger_bg)s;
    color: %(danger)s;
    border: 1px solid %(danger_border)s;
}
QPushButton#dangerButton:hover {
    background-color: %(danger)s;
    color: %(on_accent)s;
}

QPushButton#linkButton {
    background-color: transparent;
    border: none;
    color: %(accent)s;
    text-decoration: underline;
    padding: 2px 4px;
    font-weight: 600;
}
QPushButton#linkButton:hover { color: %(accent_hover)s; }

/* ---------- inputs ---------- */
QLineEdit, QComboBox, QTextEdit, QDoubleSpinBox, QSpinBox {
    background-color: %(field_bg)s;
    border: 1px solid %(border)s;
    border-radius: 8px;
    padding: 7px 10px;
    color: %(text)s;
    selection-background-color: %(accent)s;
    selection-color: %(on_accent)s;
}
QLineEdit:focus, QComboBox:focus, QTextEdit:focus,
QDoubleSpinBox:focus, QSpinBox:focus {
    border: 1px solid %(accent)s;
    background-color: %(field_focus_bg)s;
}
QDoubleSpinBox, QSpinBox { padding-%(spin_side)s: 30px; }
QDoubleSpinBox::up-button, QSpinBox::up-button {
    subcontrol-origin: border;
    subcontrol-position: top %(spin_side)s;
    width: 24px;
    border: 0px;
    margin: 3px 3px 0px 3px;
}
QDoubleSpinBox::down-button, QSpinBox::down-button {
    subcontrol-origin: border;
    subcontrol-position: bottom %(spin_side)s;
    width: 24px;
    border: 0px;
    margin: 0px 3px 3px 3px;
}
QDoubleSpinBox::up-arrow, QSpinBox::up-arrow {
    image: url(%(spin_up_icon)s); width: 10px; height: 6px;
}
QDoubleSpinBox::down-arrow, QSpinBox::down-arrow {
    image: url(%(spin_down_icon)s); width: 10px; height: 6px;
}
QDoubleSpinBox::up-button:hover, QSpinBox::up-button:hover,
QDoubleSpinBox::down-button:hover, QSpinBox::down-button:hover {
    background-color: %(accent_tint)s;
    border-radius: 4px;
}
QComboBox::drop-down { border: 0px; width: 22px; }
QComboBox QAbstractItemView {
    background-color: %(panel2)s;
    color: %(text)s;
    selection-background-color: %(accent_tint)s;
    selection-color: %(accent)s;
    border: 1px solid %(border)s;
    outline: none;
}

QCheckBox { spacing: 8px; }

/* ---------- lists & trees ---------- */
QListWidget, QTreeWidget {
    background-color: %(panel2)s;
    border: 1px solid %(border_soft)s;
    border-radius: 10px;
    padding: 4px;
}
QListWidget::item, QTreeWidget::item {
    padding: 7px 10px;
    border-radius: 8px;
    margin-bottom: 1px;
}
QListWidget::item:hover, QTreeWidget::item:hover { background-color: %(hover)s; }
QListWidget::item:selected, QTreeWidget::item:selected {
    background-color: %(accent_tint)s;
    color: %(accent)s;
    font-weight: 700;
    border: 1px solid %(accent_tint2)s;
}

/* ---------- tables ---------- */
QWidget#projectOverview, QScrollArea#projectOverviewScroll {
    background-color: %(bg)s;
    border: none;
}
QTreeWidget#projectBrowser::item {
    border: none;
    border-radius: 0;
}
QFrame#detailPanel, QWidget#detailPanel {
    background-color: %(panel)s;
    border: 1px solid %(border_soft)s;
    border-radius: 10px;
}
QLabel#detailTitle { font-size: 15px; font-weight: 700; color: %(text)s; }
QTextBrowser#detailBody { background-color: transparent; border: none; padding: 0; }
QPushButton#filterChip {
    background-color: %(accent_tint)s;
    color: %(accent)s;
    border: 1px solid %(accent_tint2)s;
    padding: 4px 8px;
}
QFrame#statCard[clickable="true"]:hover, QFrame#statCard[clickable="true"]:focus {
    border: 1px solid %(accent)s;
}
QTableWidget, QTableView {
    background-color: %(table_bg)s;
    border: 1px solid %(border_soft)s;
    gridline-color: %(grid)s;
    border-radius: 10px;
    selection-background-color: %(sel_bg)s;
    selection-color: %(sel_text)s;
    alternate-background-color: %(table_alt)s;
}
QTableWidget::item, QTableView::item { padding: 3px; }
QTableWidget::item:hover { background-color: %(hover)s; }
QTableWidget::item:selected {
    background-color: %(sel_bg)s;
    color: %(sel_text)s;
    /* Outline keeps multi-row selection readable even where a cell paints
       its own background brush (Status / warning chips). */
    border-top: 1px solid %(accent_tint2)s;
    border-bottom: 1px solid %(accent_tint2)s;
}
QHeaderView { background-color: %(header_bg)s; }
QHeaderView::section {
    background-color: %(header_bg)s;
    color: %(text2)s;
    padding: 8px 10px;
    border: none;
    border-%(sidebar_edge)s: 1px solid %(border_soft)s;
    border-bottom: 1px solid %(border)s;
    font-weight: 700;
}
QHeaderView::section:hover { background-color: %(hover)s; color: %(text)s; }
QHeaderView::section:checked { color: %(text)s; background-color: %(panel3)s; }

/* ---------- tabs ---------- */
QTabWidget::pane {
    border: 1px solid %(border_soft)s;
    border-radius: 10px;
    background-color: %(panel2)s;
    top: -1px;
}
QTabBar::tab {
    background-color: transparent;
    color: %(muted)s;
    padding: 7px 14px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background-color: %(panel2)s;
    color: %(accent)s;
    font-weight: 700;
    border-bottom: 2px solid %(accent)s;
}
QTabBar::tab:hover:!selected { background-color: %(hover)s; color: %(text)s; }

/* ---------- menus / status / tooltip ---------- */
QStatusBar {
    background-color: %(bg)s;
    color: %(muted)s;
    border-top: 1px solid %(border_soft)s;
}
QMenuBar { background-color: %(bg)s; color: %(text2)s; }
QMenuBar::item:selected { background-color: %(panel2)s; border-radius: 4px; }
QMenu {
    background-color: %(panel2)s;
    border: 1px solid %(border)s;
    border-radius: 8px;
    padding: 4px;
}
QMenu::item { padding: 7px 22px; border-radius: 6px; }
QMenu::item:selected { background-color: %(accent_tint)s; color: %(accent)s; }

QToolTip {
    background-color: %(tooltip_bg)s;
    color: %(text)s;
    border: 1px solid %(border)s;
    border-radius: 6px;
    padding: 6px 9px;
}

/* ---------- scrollbars ---------- */
QScrollBar:vertical { background: transparent; width: 11px; margin: 2px; }
QScrollBar::handle:vertical {
    background: %(scroll)s; border-radius: 4px; min-height: 32px;
}
QScrollBar::handle:vertical:hover { background: %(scroll_hover)s; }
QScrollBar::handle:vertical:pressed { background: %(accent)s; }
QScrollBar:horizontal { background: transparent; height: 11px; margin: 2px; }
QScrollBar::handle:horizontal {
    background: %(scroll)s; border-radius: 4px; min-width: 32px;
}
QScrollBar::handle:horizontal:hover { background: %(scroll_hover)s; }
QScrollBar::handle:horizontal:pressed { background: %(accent)s; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0px; width: 0px; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

/* ---------- group box / progress ---------- */
QGroupBox {
    border: 1px solid %(border)s;
    border-radius: 10px;
    margin-top: 12px;
    padding: 10px 8px 8px 8px;
    background-color: %(panel2)s;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top %(groupbox_title_side)s;
    padding: 0 6px;
    color: %(muted)s;
    font-weight: 600;
}
QProgressBar {
    background-color: %(panel3)s;
    border: 1px solid %(border_soft)s;
    border-radius: 7px;
    text-align: center;
    color: %(text)s;
    height: 16px;
}
QProgressBar::chunk { background-color: %(accent)s; border-radius: 6px; }

/* ---------- app-specific frames ---------- */
QFrame#undoBar {
    background-color: %(panel3)s;
    border: 1px solid %(border)s;
    border-radius: 10px;
}
QFrame#undoBar QLabel { color: %(text)s; }

QFrame#toolbarFrame {
    background-color: %(bg)s;
    border-bottom: 1px solid %(border_soft)s;
}

QFrame#statCard {
    background-color: %(panel2)s;
    border: 1px solid %(border_soft)s;
    border-radius: 12px;
    padding: 12px;
}
QFrame#statCard QLabel#statValue {
    font-size: 24px;
    font-weight: 700;
    color: %(text)s;
}
QFrame#statCard[severity="warn"] {
    border: 1px solid %(warn_border)s;
    background-color: %(warn_bg)s;
}
QFrame#statCard[severity="warn"] QLabel#statValue { color: %(warn)s; }
QFrame#statCard[severity="bad"] {
    border: 1px solid %(bad_border)s;
    background-color: %(bad_bg)s;
}
QFrame#statCard[severity="bad"] QLabel#statValue { color: %(danger)s; }

/* ---------- command palette (Ctrl+K) ---------- */
QFrame#commandPalette {
    background-color: %(panel)s;
    border: 1px solid %(border)s;
    border-radius: 14px;
}
QLineEdit#paletteSearch {
    background-color: transparent;
    border: none;
    border-radius: 0px;
    padding: 12px 6px;
    font-size: 13.5px;
    font-weight: 500;
}
QLineEdit#paletteSearch:focus { border: none; background-color: transparent; }
QLabel#paletteGroupLabel {
    color: %(faint)s;
    font-size: 10.5px;
    font-weight: 700;
    padding: 8px 10px 4px 10px;
    letter-spacing: 1px;
}
QListWidget#paletteList {
    background-color: transparent;
    border: none;
    border-radius: 0px;
    padding: 4px;
}
QListWidget#paletteList::item {
    padding: 9px 10px;
    border-radius: 9px;
    color: %(text2)s;
}
QListWidget#paletteList::item:hover { background-color: %(hover)s; }
QListWidget#paletteList::item:selected {
    background-color: %(accent_tint)s;
    color: %(text)s;
    border: 1px solid %(accent_tint2)s;
}
"""


def _render(tokens, rtl):
    values = dict(tokens)
    # `text-align` is a Qt::Alignment value: Qt mirrors it automatically for
    # a RightToLeft layout, so it must always be given the LOGICAL start
    # ("left" = start). Passing "right" here flips the nav labels to the
    # wrong edge in Arabic - measured, not assumed.
    values["nav_align"] = "left"
    # Box-model sides in QSS are physical (Qt does not mirror them), so these
    # two really do depend on the interface direction.
    values["sidebar_edge"] = "left" if rtl else "right"
    values["groupbox_title_side"] = "right" if rtl else "left"
    # Spin-box arrows sit on the trailing edge (left in Arabic). The field
    # padding on that side must leave room for them, or the arrows cover
    # the number itself.
    values["spin_side"] = "left" if rtl else "right"
    # Once the spin-box buttons are styled, Qt stops drawing its own arrows.
    import os
    from app_paths import get_resource_dir
    assets =os.path.join(get_resource_dir(), "assets").replace("\\", "/")
    values["spin_up_icon"] = f"{assets}/spin_up.svg"
    values["spin_down_icon"] = f"{assets}/spin_down.svg"
    return _TEMPLATE % values


def get_stylesheet(theme, rtl=False, scale=1.0):
    """Returns the full QSS for *theme* ("dark" | "light").

    *rtl* must match the application layout direction (Arabic = True),
    because a few rules are physically left/right rather than direction
    aware. Callers re-fetch this after a language or theme change.
    """
    tokens = DARK_TOKENS if theme == "dark" else LIGHT_TOKENS
    import re
    scale = max(1.0, min(float(scale), 1.3))
    return re.sub(r"font-size:\s*([\d.]+)px", lambda match:
                  f"font-size: {float(match.group(1)) * scale:g}px", _render(tokens, rtl))


# Backwards-compatible module-level constants: some callers/tests may still
# import DARK_THEME / LIGHT_THEME. They are the LTR rendering.
DARK_THEME = get_stylesheet("dark", rtl=False)
LIGHT_THEME = get_stylesheet("light", rtl=False)
