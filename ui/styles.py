"""

ui/styles.py
Refined Dark & Light QSS themes for Project Tracker.
Palette: deep indigo/slate accents with a warm teal highlight — chosen to
be calm on the eyes for long working sessions while staying professional.
"""

DARK_THEME = """
QMainWindow, QDialog {
    background-color: #0F1115;
    color: #E7EBF3;
}

QWidget {
    font-family: 'Inter', 'Segoe UI', 'Cairo', Tahoma, Geneva, Verdana, sans-serif;
    font-size: 13px;
    color: #E7EBF3;
}

QWidget#sidebar {
    background-color: #14161C;
    border-right: 1px solid #23262F;
}

QPushButton#navButton {
    /* Bold in EVERY state: switching 500->700 on the active state made
       bold text render wider than a button sized from the regular hint,
       clipping the last letter at the pill's right edge. */
    padding: 6px 16px;
    border-radius: 7px;
    background-color: transparent;
    border: 1px solid transparent;
    font-weight: 700;
}
QPushButton#navButton:hover {
    background-color: #1D2028;
}
QPushButton#navButton:checked {
    /* Active tab = tinted pill. Geometry (border/padding) stays identical
       to the unchecked state so the label can never shift or clip when
       the user clicks a tab - at any display scaling factor. */
    background-color: #17352F;
    color: #4FD1C5;
    border: 1px solid #1F4A42;
    border-radius: 7px;
}

QLabel#logoLabel {
    /* White plate: a dark-ink company logo would vanish against the dark
       toolbar - on a white chip it is always readable, in both themes. */
    background-color: #FFFFFF;
    border: 1px solid #E4E9F2;
    border-radius: 8px;
    padding: 4px 10px;
}

QSplitter::handle {
    background-color: #23262F;
}

QLabel {
    color: #C7CEDB;
}

QLabel#pageTitle {
    font-size: 19px;
    font-weight: 700;
    color: #F4F6FB;
}

QLabel#breadcrumb {
    color: #99A3B8;
    font-size: 12px;
}

QPushButton {
    background-color: #1C1F27;
    color: #E7EBF3;
    border: 1px solid #2C303B;
    border-radius: 8px;
    padding: 6px 12px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #262A34;
    border-color: #3A3F4C;
}
QPushButton:pressed {
    background-color: #16181E;
}
QPushButton:disabled {
    background-color: #15171C;
    color: #4B5262;
    border-color: #1E212A;
}

QPushButton#primaryButton {
    background-color: #2DAE93;
    color: #08130F;
    border: 1px solid #37C7A8;
    font-weight: 700;
}
QPushButton#primaryButton:hover {
    background-color: #33C2A3;
}

QPushButton#dangerButton {
    background-color: #3A1620;
    color: #FCA5A5;
    border: 1px solid #5C1F2C;
}
QPushButton#dangerButton:hover {
    background-color: #5C1F2C;
    color: #FFFFFF;
}

QPushButton#linkButton {
    background-color: transparent;
    border: none;
    color: #4FD1C5;
    text-decoration: underline;
    padding: 2px 4px;
    font-weight: 600;
}
QPushButton#linkButton:hover {
    color: #7EE8D8;
}

QLineEdit, QComboBox, QTextEdit, QDoubleSpinBox {
    background-color: #171A21;
    border: 1px solid #2A2E38;
    border-radius: 8px;
    padding: 7px 10px;
    color: #F4F6FB;
    selection-background-color: #2DAE93;
}
QLineEdit:focus, QComboBox:focus, QTextEdit:focus, QDoubleSpinBox:focus {
    border: 1px solid #2DAE93;
    background-color: #1B1E26;
}
QComboBox::drop-down {
    border: 0px;
    width: 22px;
}
QComboBox QAbstractItemView {
    background-color: #1B1E26;
    color: #E7EBF3;
    selection-background-color: #2DAE93;
    selection-color: #08130F;
    border: 1px solid #2C303B;
    outline: none;
}

QCheckBox {
    spacing: 8px;
}

QListWidget {
    background-color: #14161C;
    border: 1px solid #23262F;
    border-radius: 10px;
    padding: 4px;
}
QListWidget::item {
    padding: 7px 10px;
    border-radius: 8px;
    margin-bottom: 1px;
}
QListWidget::item:hover {
    background-color: #1B1E26;
}
QListWidget::item:selected {
    background-color: #17352F;
    color: #4FD1C5;
    font-weight: 700;
    border: 1px solid #1F4A42;
}

QTableWidget {
    background-color: #14161C;
    border: 1px solid #23262F;
    gridline-color: #1E212A;
    border-radius: 10px;
    selection-background-color: #17352F;
    selection-color: #EAFBF6;
    alternate-background-color: #171A21;
}
QTableWidget::item {
    padding: 3px;
}
QTableWidget::item:hover {
    background-color: rgba(45, 174, 147, 0.14);
}
QTableWidget::item:selected {
    background-color: #17352F;
    color: #EAFBF6;
    /* Outline keeps multi-row selection readable even where a cell paints
       its own background brush (Status/Unit-Cost warning chips). */
    border: 1px solid #2DAE93;
}
QHeaderView::section {
    background-color: #1A1D24;
    color: #9AA3B8;
    padding: 8px 10px;
    border: none;
    border-right: 1px solid #23262F;
    border-bottom: 2px solid #2DAE93;
    font-weight: 700;
}
QHeaderView::section:hover {
    background-color: #21242D;
    color: #F4F6FB;
}

QTabWidget::pane {
    border: 1px solid #23262F;
    border-radius: 10px;
    background-color: #14161C;
    top: -1px;
}
QTabBar::tab {
    background-color: #0F1115;
    color: #8892A6;
    padding: 7px 14px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background-color: #14161C;
    color: #4FD1C5;
    font-weight: 700;
    border-bottom: 2px solid #4FD1C5;
}
QTabBar::tab:hover:!selected {
    background-color: #191C23;
    color: #E7EBF3;
}

QStatusBar {
    background-color: #0F1115;
    color: #8892A6;
    border-top: 1px solid #23262F;
}
QMenuBar {
    background-color: #0F1115;
    color: #C7CEDB;
}
QMenuBar::item:selected {
    background-color: #1C1F27;
    border-radius: 4px;
}
QMenu {
    background-color: #171A21;
    border: 1px solid #23262F;
    border-radius: 8px;
    padding: 4px;
}
QMenu::item {
    padding: 7px 22px;
    border-radius: 6px;
}
QMenu::item:selected {
    background-color: #17352F;
    color: #4FD1C5;
}

QFrame#undoBar {
    background-color: #171A21;
    border: 1px solid #2C303B;
    border-radius: 10px;
}
QFrame#undoBar QLabel {
    color: #E7EBF3;
}

QFrame#toolbarFrame {
    background-color: #0F1115;
    border-bottom: 1px solid #23262F;
}
QFrame#statCard {
    background-color: #171A21;
    border: 1px solid #23262F;
    border-radius: 10px;
    padding: 10px;
}
QFrame#statCard QLabel#statValue {
    font-size: 26px;
    font-weight: 700;
    color: #E7EBF3;
}
QFrame#statCard[severity="warn"] {
    border: 1px solid #B45309;
    background-color: #2A1F0F;
}
QFrame#statCard[severity="warn"] QLabel#statValue {
    color: #FBBF24;
}
QFrame#statCard[severity="bad"] {
    border: 1px solid #B91C1C;
    background-color: #2A1414;
}
QFrame#statCard[severity="bad"] QLabel#statValue {
    color: #F87171;
}

QToolTip {
    background-color: #22262F;
    color: #E7EBF3;
    border: 1px solid #3A3F4C;
    border-radius: 6px;
    padding: 6px 9px;
}

QScrollBar:vertical {
    background: transparent;
    width: 11px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #2C303B;
    border-radius: 4px;
    min-height: 32px;
}
QScrollBar::handle:vertical:hover {
    background: #3A3F4C;
}
QScrollBar::handle:vertical:pressed {
    background: #2DAE93;
}
QScrollBar:horizontal {
    background: transparent;
    height: 11px;
    margin: 2px;
}
QScrollBar::handle:horizontal {
    background: #2C303B;
    border-radius: 4px;
    min-width: 32px;
}
QScrollBar::handle:horizontal:hover {
    background: #3A3F4C;
}
QScrollBar::handle:horizontal:pressed {
    background: #2DAE93;
}
QScrollBar::add-line, QScrollBar::sub-line {
    height: 0px;
    width: 0px;
}
QScrollBar::add-page, QScrollBar::sub-page {
    background: transparent;
}

QGroupBox {
    border: 1px solid #2C303B;
    border-radius: 10px;
    margin-top: 12px;
    padding: 10px 8px 8px 8px;
    background-color: #14161C;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top right;
    padding: 0 6px;
    color: #8892A6;
    font-weight: 600;
}

QProgressBar {
    background-color: #171A21;
    border: 1px solid #2C303B;
    border-radius: 7px;
    text-align: center;
    color: #E7EBF3;
    height: 16px;
}
QProgressBar::chunk {
    background-color: #2DAE93;
    border-radius: 6px;
}

QHeaderView::section:checked {
    color: #F4F6FB;
    background-color: #21242D;
}
"""

LIGHT_THEME = """
QMainWindow, QDialog {
    background-color: #F6F8FB;
    color: #1D2433;
}

QWidget {
    font-family: 'Inter', 'Segoe UI', 'Cairo', Tahoma, Geneva, Verdana, sans-serif;
    font-size: 13px;
    color: #1D2433;
}

QWidget#sidebar {
    background-color: #FFFFFF;
    border-right: 1px solid #E4E9F2;
}

QPushButton#navButton {
    /* Bold in EVERY state: switching 500->700 on the active state made
       bold text render wider than a button sized from the regular hint,
       clipping the last letter at the pill's right edge. */
    padding: 6px 16px;
    border-radius: 7px;
    background-color: transparent;
    border: 1px solid transparent;
    font-weight: 700;
}
QPushButton#navButton:hover {
    background-color: #F0F4F9;
}
QPushButton#navButton:checked {
    background-color: #E4F7F1;
    color: #0E8F76;
    border: 1px solid #BDEBDD;
    border-radius: 7px;
}

QLabel#logoLabel {
    background-color: #FFFFFF;
    border: 1px solid #E4E9F2;
    border-radius: 8px;
    padding: 4px 10px;
}

QSplitter::handle {
    background-color: #E4E9F2;
}

QLabel {
    color: #3D465A;
}
QLabel#pageTitle {
    font-size: 19px;
    font-weight: 700;
    color: #101828;
}
QLabel#breadcrumb {
    color: #566079;
    font-size: 12px;
}

QPushButton {
    background-color: #FFFFFF;
    color: #334155;
    border: 1px solid #D8DEEA;
    border-radius: 8px;
    padding: 6px 12px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #F0F4F9;
    border-color: #B7C0D6;
}
QPushButton:pressed {
    background-color: #E4E9F2;
}
QPushButton:disabled {
    background-color: #F6F8FB;
    color: #A6AFC2;
    border-color: #E4E9F2;
}

QPushButton#primaryButton {
    background-color: #0E9F82;
    color: #FFFFFF;
    border: 1px solid #0C8A70;
    font-weight: 700;
}
QPushButton#primaryButton:hover {
    background-color: #0C8A70;
}

QPushButton#dangerButton {
    background-color: #FEF2F2;
    color: #DC2626;
    border: 1px solid #FCA5A5;
}
QPushButton#dangerButton:hover {
    background-color: #DC2626;
    color: #FFFFFF;
}

QPushButton#linkButton {
    background-color: transparent;
    border: none;
    color: #0C8A70;
    text-decoration: underline;
    padding: 2px 4px;
    font-weight: 600;
}
QPushButton#linkButton:hover {
    color: #0E9F82;
}

QLineEdit, QComboBox, QTextEdit, QDoubleSpinBox {
    background-color: #FFFFFF;
    border: 1px solid #D8DEEA;
    border-radius: 8px;
    padding: 7px 10px;
    color: #101828;
    selection-background-color: #0E9F82;
    selection-color: #FFFFFF;
}
QLineEdit:focus, QComboBox:focus, QTextEdit:focus, QDoubleSpinBox:focus {
    border: 1px solid #0E9F82;
    background-color: #FFFFFF;
}
QComboBox QAbstractItemView {
    background-color: #FFFFFF;
    color: #1D2433;
    selection-background-color: #0E9F82;
    selection-color: #FFFFFF;
    border: 1px solid #D8DEEA;
    outline: none;
}

QListWidget {
    background-color: #FFFFFF;
    border: 1px solid #E4E9F2;
    border-radius: 10px;
    padding: 4px;
}
QListWidget::item {
    padding: 7px 10px;
    border-radius: 8px;
    margin-bottom: 1px;
}
QListWidget::item:hover {
    background-color: #F0F4F9;
}
QListWidget::item:selected {
    background-color: #E4F7F1;
    color: #0E8F76;
    font-weight: 700;
    border: 1px solid #BDEBDD;
}

QTableWidget {
    background-color: #FFFFFF;
    border: 1px solid #E4E9F2;
    gridline-color: #EEF2F8;
    border-radius: 10px;
    selection-background-color: #E4F7F1;
    selection-color: #0E8F76;
    alternate-background-color: #F8FAFD;
}
QTableWidget::item {
    padding: 3px;
}
QTableWidget::item:hover {
    background-color: rgba(14, 159, 130, 0.10);
}
QTableWidget::item:selected {
    background-color: #E4F7F1;
    color: #0E8F76;
    border: 1px solid #0E9F82;
}
QHeaderView::section {
    background-color: #F6F8FB;
    color: #566079;
    padding: 8px 10px;
    border: none;
    border-right: 1px solid #E4E9F2;
    border-bottom: 2px solid #0E9F82;
    font-weight: 700;
}
QHeaderView::section:hover {
    background-color: #EEF2F8;
    color: #101828;
}

QTabWidget::pane {
    border: 1px solid #E4E9F2;
    border-radius: 10px;
    background-color: #FFFFFF;
    top: -1px;
}
QTabBar::tab {
    background-color: #F6F8FB;
    color: #6B7280;
    padding: 7px 14px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background-color: #FFFFFF;
    color: #0E8F76;
    font-weight: 700;
    border-bottom: 2px solid #0E9F82;
}
QTabBar::tab:hover:!selected {
    background-color: #EEF2F8;
    color: #1D2433;
}

QStatusBar {
    background-color: #F6F8FB;
    color: #4B5563;
    border-top: 1px solid #E4E9F2;
}
QMenuBar {
    background-color: #F6F8FB;
    color: #334155;
}
QMenuBar::item:selected {
    background-color: #E4E9F2;
    border-radius: 4px;
}
QMenu {
    background-color: #FFFFFF;
    border: 1px solid #D8DEEA;
    border-radius: 8px;
    padding: 4px;
}
QMenu::item {
    padding: 7px 22px;
    border-radius: 6px;
}
QMenu::item:selected {
    background-color: #E4F7F1;
    color: #0E8F76;
}

QFrame#undoBar {
    background-color: #101828;
    border: 1px solid #1D2433;
    border-radius: 10px;
}
QFrame#undoBar QLabel {
    color: #F6F8FB;
}

QFrame#toolbarFrame {
    background-color: #FFFFFF;
    border-bottom: 1px solid #E4E9F2;
}
QFrame#statCard {
    background-color: #FFFFFF;
    border: 1px solid #D8DEEA;
    border-radius: 10px;
    padding: 10px;
}
QFrame#statCard QLabel#statValue {
    font-size: 26px;
    font-weight: 700;
    color: #101828;
}
QFrame#statCard[severity="warn"] {
    border: 1px solid #D97706;
    background-color: #FFFBEB;
}
QFrame#statCard[severity="warn"] QLabel#statValue {
    color: #B45309;
}
QFrame#statCard[severity="bad"] {
    border: 1px solid #DC2626;
    background-color: #FEF2F2;
}
QFrame#statCard[severity="bad"] QLabel#statValue {
    color: #B91C1C;
}

QToolTip {
    background-color: #FFFFFF;
    color: #1D2433;
    border: 1px solid #C9D2E3;
    border-radius: 6px;
    padding: 6px 9px;
}

QScrollBar:vertical {
    background: transparent;
    width: 11px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #C9D2E3;
    border-radius: 4px;
    min-height: 32px;
}
QScrollBar::handle:vertical:hover {
    background: #AEB9CF;
}
QScrollBar::handle:vertical:pressed {
    background: #0E9F82;
}
QScrollBar:horizontal {
    background: transparent;
    height: 11px;
    margin: 2px;
}
QScrollBar::handle:horizontal {
    background: #C9D2E3;
    border-radius: 4px;
    min-width: 32px;
}
QScrollBar::handle:horizontal:hover {
    background: #AEB9CF;
}
QScrollBar::handle:horizontal:pressed {
    background: #0E9F82;
}
QScrollBar::add-line, QScrollBar::sub-line {
    height: 0px;
    width: 0px;
}
QScrollBar::add-page, QScrollBar::sub-page {
    background: transparent;
}

QGroupBox {
    border: 1px solid #E4E9F2;
    border-radius: 10px;
    margin-top: 12px;
    padding: 10px 8px 8px 8px;
    background-color: #FFFFFF;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top right;
    padding: 0 6px;
    color: #6B7280;
    font-weight: 600;
}

QProgressBar {
    background-color: #EEF2F8;
    border: 1px solid #E4E9F2;
    border-radius: 7px;
    text-align: center;
    color: #1D2433;
    height: 16px;
}
QProgressBar::chunk {
    background-color: #0E9F82;
    border-radius: 6px;
}

QHeaderView::section:checked {
    color: #101828;
    background-color: #EEF2F8;
}
"""
