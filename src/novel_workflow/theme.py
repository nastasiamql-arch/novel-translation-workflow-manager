"""Shared neutral design tokens and Qt styles for NovelWorkflow."""
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication

TOKENS = {
    "spacing": (4, 8, 12, 16, 20, 24, 32),
    "radius": 8,
    "control_height": 34,
    "motion_ms": 160,
}

_DARK = {
    "app": "#0F1115", "surface": "#15181E", "surface2": "#1A1E26",
    "hover": "#20252E", "elevated": "#232832", "border": "#2A303A",
    "border_strong": "#343B47", "text": "#F1F3F5", "secondary": "#A1A8B3",
    "muted": "#858D99", "accent": "#6C7CFF", "accent_hover": "#7C8AFF",
    "success": "#3FA67A", "warning": "#D5A94E", "danger": "#E25D68",
    "selection": "#252B38", "input": "#11141A", "on_accent": "#FFFFFF", "progress": "#7585BB",
}
_LIGHT = {
    "app": "#F4F5F7", "surface": "#FFFFFF", "surface2": "#F7F8FA",
    "hover": "#EEF0F4", "elevated": "#FFFFFF", "border": "#E0E3E8",
    "border_strong": "#C9CED7", "text": "#20242B", "secondary": "#59616D",
    "muted": "#737C88", "accent": "#5265E8", "accent_hover": "#4255D8",
    "success": "#27845D", "warning": "#9B6C12", "danger": "#C9414C",
    "selection": "#E8EBF8", "input": "#FFFFFF", "on_accent": "#FFFFFF", "progress": "#7182B2",
}


def _use_dark(appearance: str) -> bool:
    if appearance.lower() == "dark":
        return True
    if appearance.lower() == "light":
        return False
    app = QApplication.instance()
    if app is None:
        return True
    return app.palette().color(QPalette.Window).lightness() < 128


def application_stylesheet(appearance: str = "Dark") -> str:
    """Return the shared compact stylesheet for dark, light, or system mode."""
    c = _DARK if _use_dark(appearance) else _LIGHT
    return f"""
    QWidget {{
        color: {c["text"]};
        font-family: "Segoe UI", "Noto Sans Thai UI", sans-serif;
        font-size: 10pt;
    }}
    QMainWindow, QDialog {{ background: {c["app"]}; }}
    QToolBar#mainToolbar {{
        background: {c["surface"]};
        border: 0;
        border-bottom: 1px solid {c["border"]};
        spacing: 4px;
        padding: 4px 8px;
    }}
    QToolBar#mainToolbar::separator {{
        width: 1px; background: {c["border"]}; margin: 5px 8px;
    }}
    QLabel#brandTitle {{ color: {c["text"]}; font-size: 13pt; font-weight: 600; }}
    QLabel#currentNovel {{
        color: {c["text"]}; background: {c["surface"]};
        border: 1px solid {c["border"]}; border-radius: 8px;
        font-size: 16pt; font-weight: 600; padding: 10px 14px;
    }}
    QLabel#sectionHeading {{
        color: {c["secondary"]}; font-size: 9pt; font-weight: 600;
        padding: 0 2px 4px 2px;
    }}
    QLabel#mutedLabel, QLabel[class="muted"] {{ color: {c["muted"]}; }}
    QLabel#metricValue {{ color: {c["text"]}; font-size: 20pt; font-weight: 600; }}
    QLabel#metricLabel {{ color: {c["text"]}; font-size: 11pt; font-weight: 600; }}
    QLabel#bodyLabel {{ color: {c["secondary"]}; }}
    QToolButton {{
        color: {c["secondary"]}; background: transparent; border: 1px solid transparent;
        border-radius: 6px; padding: 7px 9px; font-weight: 500;
    }}
    QToolButton:hover {{ color: {c["text"]}; background: {c["hover"]}; }}
    QToolButton:pressed {{ background: {c["elevated"]}; }}
    QToolButton:focus {{ border-color: {c["accent"]}; }}
    QFrame#columnPanel, QFrame#goalPanel, QFrame#metricCard, QFrame#progressRow {{
        background: {c["surface"]}; border: 1px solid {c["border"]}; border-radius: 8px;
    }}
    QListWidget, QTreeWidget, QTableWidget, QTableView {{
        background: {c["surface"]}; color: {c["text"]};
        border: 1px solid {c["border"]}; border-radius: 8px;
        padding: 4px; outline: none; selection-background-color: {c["selection"]};
        selection-color: {c["text"]};
    }}
    QListWidget:focus, QTreeWidget:focus, QTableWidget:focus, QTableView:focus {{
        border-color: {c["accent"]};
    }}
    QListWidget::item, QTreeWidget::item {{
        color: {c["text"]}; padding: 8px; margin: 1px; border-radius: 5px;
    }}
    QListWidget::item:hover, QTreeWidget::item:hover {{ background: {c["hover"]}; }}
    QListWidget::item:selected, QTreeWidget::item:selected {{
        background: {c["selection"]}; color: {c["text"]};
        border-left: 2px solid {c["accent"]}; font-weight: 600;
    }}
    QHeaderView::section {{
        color: {c["secondary"]}; background: {c["surface2"]};
        border: 0; border-bottom: 1px solid {c["border"]}; padding: 8px;
    }}
    QPushButton {{
        min-height: 18px; background: {c["surface2"]}; color: {c["text"]};
        border: 1px solid {c["border"]}; border-radius: 6px;
        padding: 6px 10px; font-weight: 500;
    }}
    QPushButton:hover {{ background: {c["hover"]}; border-color: {c["border_strong"]}; }}
    QPushButton:pressed {{ background: {c["elevated"]}; }}
    QPushButton:focus {{ border-color: {c["accent"]}; }}
    QPushButton:disabled {{
        color: {c["muted"]}; background: {c["surface"]}; border-color: {c["border"]};
    }}
    QPushButton#primaryButton {{
        background: {c["accent"]}; color: {c["on_accent"]};
        border: 1px solid {c["accent"]}; font-weight: 600;
    }}
    QPushButton#primaryButton:hover {{
        background: {c["accent_hover"]}; border-color: {c["accent_hover"]};
    }}
    QPushButton#primaryButton:pressed {{ background: {c["accent"]}; }}
    QPushButton#dangerButton {{
        background: transparent; color: {c["danger"]}; border-color: {c["border"]};
    }}
    QPushButton#dangerButton:hover {{ background: {c["hover"]}; border-color: {c["danger"]}; }}
    QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
        background: {c["input"]}; color: {c["text"]};
        border: 1px solid {c["border"]}; border-radius: 6px;
        padding: 7px 9px; selection-background-color: {c["selection"]};
        min-height: 18px;
    }}
    QLineEdit:hover, QPlainTextEdit:hover, QTextEdit:hover, QSpinBox:hover,
    QDoubleSpinBox:hover, QComboBox:hover {{ border-color: {c["border_strong"]}; }}
    QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus,
    QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {c["accent"]}; }}
    QLineEdit:disabled, QComboBox:disabled {{ color: {c["muted"]}; }}
    QLineEdit::placeholder {{ color: {c["muted"]}; }}
    QComboBox::drop-down {{ border: 0; width: 24px; }}
    QComboBox QAbstractItemView {{
        background: {c["surface"]}; color: {c["text"]};
        border: 1px solid {c["border"]}; selection-background-color: {c["selection"]};
        outline: none;
    }}
    QCheckBox, QRadioButton {{ color: {c["text"]}; spacing: 8px; }}
    QCheckBox:disabled, QRadioButton:disabled {{ color: {c["muted"]}; }}
    QCheckBox::indicator, QRadioButton::indicator {{
        width: 16px; height: 16px; border: 1px solid {c["border_strong"]};
        border-radius: 4px; background: {c["input"]};
    }}
    QCheckBox::indicator:checked {{
        background: {c["accent"]}; border-color: {c["accent"]};
    }}
    QRadioButton::indicator, QRadioButton::indicator:checked {{
        border-radius: 8px;
    }}
    QRadioButton::indicator:checked {{
        background: {c["accent"]}; border-color: {c["accent"]};
    }}
    QTabWidget::pane {{
        background: {c["surface"]}; border: 1px solid {c["border"]}; border-radius: 8px;
        top: -1px;
    }}
    QTabBar::tab {{
        color: {c["secondary"]}; background: transparent; padding: 9px 13px;
        margin-right: 2px; border: 0; border-bottom: 2px solid transparent;
    }}
    QTabBar::tab:hover {{ color: {c["text"]}; background: {c["hover"]}; }}
    QTabBar::tab:selected {{
        color: {c["text"]}; border-bottom-color: {c["accent"]}; font-weight: 600;
    }}
    QProgressBar {{
        background: {c["surface2"]}; color: {c["secondary"]};
        border: 0; border-radius: 4px; text-align: center; min-height: 10px;
    }}
    QProgressBar::chunk {{ background: {c["accent"]}; border-radius: 4px; }}
    QProgressBar#activityHistoryBar {{ background: {c["surface2"]}; }}
    QProgressBar#activityHistoryBar::chunk {{ background: {c["progress"]}; }}
    QStatusBar {{ background: {c["surface"]}; color: {c["secondary"]}; border-top: 1px solid {c["border"]}; }}
    QStatusBar::item {{ border: 0; }}
    QMenu {{
        background: {c["surface"]}; color: {c["text"]};
        border: 1px solid {c["border"]}; padding: 4px;
    }}
    QMenu::item {{ padding: 7px 24px 7px 10px; border-radius: 4px; }}
    QMenu::item:selected {{ background: {c["hover"]}; }}
    QMenu::separator {{ height: 1px; background: {c["border"]}; margin: 4px 6px; }}
    QToolTip {{
        color: {c["text"]}; background: {c["elevated"]};
        border: 1px solid {c["border_strong"]}; padding: 5px 7px;
    }}
    QDialogButtonBox QPushButton {{ min-width: 76px; }}
    QSplitter::handle {{ background: transparent; width: 6px; }}
    QScrollArea, QAbstractScrollArea {{ background: transparent; border: 0; }}
    QScrollBar:vertical, QScrollBar:horizontal {{
        background: transparent; border: 0; margin: 2px; width: 9px; height: 9px;
    }}
    QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
        background: {c["border_strong"]}; border-radius: 4px; min-height: 26px; min-width: 26px;
    }}
    QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{
        background: {c["muted"]};
    }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    """
