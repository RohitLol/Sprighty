"""
Sprightly dark theme — violet accent (#7C3AED).
Apply once at startup via:  app.setStyleSheet(DARK_THEME)
"""

DARK_THEME = """
/* ═══════════════════════════════════════════════════════
   Base
═══════════════════════════════════════════════════════ */
QMainWindow, QWidget {
    background-color: #0A0A0F;
    color: #E2E8F0;
    font-family: 'Segoe UI', 'Arial', sans-serif;
    font-size: 13px;
}

/* ═══════════════════════════════════════════════════════
   Toolbar
═══════════════════════════════════════════════════════ */
QToolBar {
    background: #111118;
    border-bottom: 1px solid #1C1C28;
    padding: 5px 12px;
    spacing: 4px;
}
QToolBar::separator {
    background: #252535;
    width: 1px;
    margin: 4px 6px;
}
QToolBar QLabel {
    color: #4A5568;
    font-size: 11px;
    padding: 0 4px;
    letter-spacing: 0.3px;
}
QToolButton {
    background: transparent;
    color: #7A8A9E;
    border: 1px solid transparent;
    border-radius: 7px;
    padding: 5px 12px;
    font-size: 12px;
    min-width: 34px;
    font-weight: 500;
}
QToolButton:hover {
    background: #16162A;
    border-color: #312060;
    color: #C4B5FD;
}
QToolButton:pressed {
    background: #1E1E35;
    border-color: #5B21B6;
}
QToolButton:checked {
    background: #1A1A30;
    border-color: #7C3AED;
    color: #A78BFA;
}

/* ═══════════════════════════════════════════════════════
   ComboBox
═══════════════════════════════════════════════════════ */
QComboBox {
    background: #0F0F1A;
    border: 1px solid #22223A;
    border-radius: 8px;
    padding: 5px 12px;
    color: #C4B5FD;
    min-width: 230px;
    font-weight: 500;
    selection-background-color: #3B1FA0;
}
QComboBox:hover {
    border-color: #5B21B6;
    background: #131326;
}
QComboBox:focus {
    border-color: #7C3AED;
    background: #131326;
}
QComboBox::drop-down {
    border: none;
    width: 24px;
    subcontrol-origin: padding;
    subcontrol-position: center right;
}
QComboBox::down-arrow {
    width: 0;
    height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #5B21B6;
    margin-right: 8px;
}
QComboBox QAbstractItemView {
    background: #13131F;
    border: 1px solid #25253A;
    border-radius: 8px;
    selection-background-color: #3B1FA0;
    selection-color: #DDD6FE;
    outline: none;
    padding: 4px;
}

/* ═══════════════════════════════════════════════════════
   Tab Widget
═══════════════════════════════════════════════════════ */
QTabWidget::pane {
    border: none;
    background: #0A0A0F;
}
QTabWidget::tab-bar {
    alignment: left;
}
QTabBar {
    background: #111118;
    border-bottom: 1px solid #1C1C28;
}
QTabBar::tab {
    background: transparent;
    color: #3A4558;
    padding: 9px 22px;
    font-size: 12px;
    font-weight: 500;
    border: none;
    border-bottom: 2px solid transparent;
    margin-bottom: -1px;
    letter-spacing: 0.3px;
}
QTabBar::tab:selected {
    color: #A78BFA;
    border-bottom: 2px solid #7C3AED;
}
QTabBar::tab:hover:!selected {
    color: #94A3B8;
    background: #0F0F1C;
}

/* ═══════════════════════════════════════════════════════
   List Widget
═══════════════════════════════════════════════════════ */
QListWidget {
    background: #08080E;
    border: 1px solid #14141F;
    border-radius: 8px;
    outline: none;
    padding: 3px;
}
QListWidget::item {
    padding: 6px 10px;
    border-radius: 6px;
    color: #B4C0D0;
    margin: 1px 2px;
}
QListWidget::item:selected {
    background: #24145A;
    color: #DDD6FE;
}
QListWidget::item:hover:!selected {
    background: #12121E;
    color: #C8D0DC;
}

/* ═══════════════════════════════════════════════════════
   Push Buttons
═══════════════════════════════════════════════════════ */
QPushButton {
    background: #111120;
    color: #7A8A9E;
    border: 1px solid #20203A;
    border-radius: 8px;
    padding: 6px 14px;
    font-size: 12px;
    font-weight: 500;
}
QPushButton:hover {
    background: #18182E;
    border-color: #5B21B6;
    color: #C4B5FD;
}
QPushButton:pressed {
    background: #1E1E38;
    border-color: #7C3AED;
}
QPushButton:disabled {
    color: #1E1E30;
    border-color: #14141E;
    background: #0C0C14;
}
/* Accent button */
QPushButton[accent="true"] {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #5B21B6, stop:1 #7C3AED);
    color: #EDE9FE;
    border: none;
    font-weight: 600;
    letter-spacing: 0.3px;
}
QPushButton[accent="true"]:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #6D28D9, stop:1 #8B5CF6);
}
QPushButton[accent="true"]:pressed {
    background: #4C1D95;
}
QPushButton[accent="true"]:disabled {
    background: #2D1B69;
    color: #6C5FAF;
}

/* ═══════════════════════════════════════════════════════
   Line Edit / Spin Box
═══════════════════════════════════════════════════════ */
QLineEdit, QSpinBox {
    background: #0F0F1A;
    border: 1px solid #22223A;
    border-radius: 8px;
    padding: 5px 10px;
    color: #E2E8F0;
    selection-background-color: #3B1FA0;
    selection-color: #DDD6FE;
}
QLineEdit:focus, QSpinBox:focus {
    border-color: #7C3AED;
    background: #12122A;
}
QSpinBox::up-button, QSpinBox::down-button {
    background: #1E1E32;
    border: none;
    width: 16px;
    border-radius: 3px;
}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {
    background: #2E2E4A;
}

/* ═══════════════════════════════════════════════════════
   Splitter
═══════════════════════════════════════════════════════ */
QSplitter::handle {
    background: #14141F;
}
QSplitter::handle:horizontal {
    width: 3px;
}
QSplitter::handle:hover {
    background: #5B21B6;
}

/* ═══════════════════════════════════════════════════════
   Status Bar
═══════════════════════════════════════════════════════ */
QStatusBar {
    background: #0C0C14;
    color: #2E3A4C;
    border-top: 1px solid #14141F;
    font-size: 11px;
    padding: 2px 8px;
    letter-spacing: 0.2px;
}
QStatusBar::item {
    border: none;
}

/* ═══════════════════════════════════════════════════════
   Scrollbars
═══════════════════════════════════════════════════════ */
QScrollBar:vertical {
    background: transparent;
    width: 5px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #1E1E30;
    border-radius: 2px;
    min-height: 28px;
}
QScrollBar::handle:vertical:hover {
    background: #5B21B6;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }

QScrollBar:horizontal {
    background: transparent;
    height: 5px;
}
QScrollBar::handle:horizontal {
    background: #1E1E30;
    border-radius: 2px;
    min-width: 28px;
}
QScrollBar::handle:horizontal:hover {
    background: #5B21B6;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: none; }

/* ═══════════════════════════════════════════════════════
   Labels
═══════════════════════════════════════════════════════ */
QLabel {
    color: #4A5568;
    background: transparent;
}

/* ═══════════════════════════════════════════════════════
   Dialogs
═══════════════════════════════════════════════════════ */
QDialog {
    background: #0F0F18;
}
QDialogButtonBox > QPushButton {
    min-width: 84px;
}

/* ═══════════════════════════════════════════════════════
   Tooltips
═══════════════════════════════════════════════════════ */
QToolTip {
    background: #16162A;
    color: #E2E8F0;
    border: 1px solid #312060;
    padding: 5px 10px;
    border-radius: 7px;
    font-size: 11px;
}

/* ═══════════════════════════════════════════════════════
   Progress bar
═══════════════════════════════════════════════════════ */
QProgressBar {
    background: #111120;
    border: none;
    border-radius: 3px;
    color: transparent;
    max-height: 4px;
}
QProgressBar::chunk {
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 #5B21B6,
        stop:1 #A78BFA
    );
    border-radius: 3px;
}

/* ═══════════════════════════════════════════════════════
   Frame / separator lines
═══════════════════════════════════════════════════════ */
QFrame[frameShape="4"],
QFrame[frameShape="5"] {
    color: #18182A;
}

/* ═══════════════════════════════════════════════════════
   Form row labels inside dialogs
═══════════════════════════════════════════════════════ */
QFormLayout QLabel {
    color: #4A5568;
    font-size: 12px;
}
"""
