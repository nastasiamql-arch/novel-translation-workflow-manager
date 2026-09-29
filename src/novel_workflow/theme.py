"""Shared modern UI tokens and Qt styles for NovelWorkflow."""
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication

TOKENS = {
    "spacing": (4, 8, 12, 16, 20, 24, 32),
    "radius": 10,
    "control_height": 36,
    "motion_ms": 160,
}

# Dark follows VS Code's softer charcoal contrast instead of pure black.
_DARK = {
    "app": "#181818",
    "surface": "#1F1F1F",
    "surface2": "#252525",
    "hover": "#2B2B2B",
    "elevated": "#303030",
    "border": "#333333",
    "border_strong": "#454545",
    "text": "#E8E8E8",
    "secondary": "#B7B7B7",
    "muted": "#8F8F8F",
    "accent": "#4DAAFC",
    "accent_hover": "#69B8FF",
    "success": "#4EC9B0",
    "warning": "#DCDCAA",
    "danger": "#F48771",
    "selection": "#264F78",
    "input": "#1E1E1E",
    "primary": "#E8E8E8",
    "primary_hover": "#FFFFFF",
    "primary_text": "#202020",
}

# Light follows the quiet neutral shell used by modern ChatGPT desktop UI.
_LIGHT = {
    "app": "#F7F7F8",
    "surface": "#FFFFFF",
    "surface2": "#F1F1F2",
    "hover": "#ECECED",
    "elevated": "#E7E7E8",
    "border": "#E5E5E5",
    "border_strong": "#D1D1D1",
    "text": "#202123",
    "secondary": "#5D5D63",
    "muted": "#8B8B91",
    "accent": "#0E639C",
    "accent_hover": "#1177BB",
    "success": "#168B67",
    "warning": "#8A6D1F",
    "danger": "#C74444",
    "selection": "#DCEBFA",
    "input": "#FFFFFF",
    "primary": "#202123",
    "primary_hover": "#343541",
    "primary_text": "#FFFFFF",
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
    """Return a softer ChatGPT-like shell with VS Code-like dark work surfaces."""
    c = _DARK if _use_dark(appearance) else _LIGHT
    return f"""
    QWidget {{
        color: {c["text"]};
        font-family: "Segoe UI Variable Text", "Leelawadee UI", "Segoe UI", sans-serif;
        font-size: 10.5pt;
    }}
    QMainWindow, QDialog {{ background: {c["app"]}; }}

    QToolBar#mainToolbar {{
        background: {c["surface"]};
        border: 0;
        border-bottom: 1px solid {c["border"]};
        spacing: 5px;
        padding: 7px 12px;
    }}
    QToolBar#mainToolbar QToolButton {{
        padding: 7px 10px;
        border-radius: 8px;
    }}
    QLabel#brandTitle {{
        color: {c["text"]};
        font-size: 14pt;
        font-weight: 600;
        padding-left: 3px;
    }}
    QLabel#sectionHeading {{
        color: {c["secondary"]};
        font-size: 9pt;
        font-weight: 600;
        letter-spacing: 0.4px;
        padding: 2px 3px 5px 3px;
    }}
    QLabel#mutedLabel, QLabel[class="muted"] {{ color: {c["muted"]}; }}
    QLabel#metricValue {{ color: {c["text"]}; font-size: 22pt; font-weight: 600; }}
    QLabel#metricLabel {{ color: {c["text"]}; font-size: 11pt; font-weight: 600; }}
    QLabel#bodyLabel {{ color: {c["secondary"]}; }}

    QFrame#storyStrip, QFrame#modeStrip, QFrame#bottomBar {{
        background: {c["surface"]};
        border: 1px solid {c["border"]};
        border-radius: 12px;
    }}
    QFrame#goalPanel, QFrame#metricCard, QFrame#progressRow {{
        background: {c["surface"]};
        border: 1px solid {c["border"]};
        border-radius: 10px;
    }}
    QFrame#explorerPanel, QFrame#editorPanel {{
        background: {c["surface"]};
        border: 1px solid {c["border"]};
        border-radius: 10px;
    }}

    QToolButton {{
        color: {c["secondary"]};
        background: transparent;
        border: 1px solid transparent;
        border-radius: 8px;
        padding: 7px 9px;
        font-weight: 500;
    }}
    QToolButton:hover {{ color: {c["text"]}; background: {c["hover"]}; }}
    QToolButton:pressed {{ background: {c["elevated"]}; }}
    QToolButton:focus {{ border-color: {c["border_strong"]}; }}

    QListWidget, QTreeWidget, QTreeView, QTableWidget, QTableView {{
        background: {c["surface"]};
        color: {c["text"]};
        border: 1px solid {c["border"]};
        border-radius: 9px;
        padding: 4px;
        outline: none;
        selection-background-color: {c["selection"]};
        selection-color: {c["text"]};
    }}
    QTreeView#fileTree {{
        border: 0;
        border-radius: 6px;
        padding: 2px;
        background: {c["surface"]};
    }}
    QListWidget:focus, QTreeWidget:focus, QTreeView:focus,
    QTableWidget:focus, QTableView:focus {{
        border-color: {c["border_strong"]};
    }}
    QListWidget::item, QTreeWidget::item, QTreeView::item {{
        color: {c["text"]};
        min-height: 25px;
        padding: 4px 7px;
        margin: 1px;
        border-radius: 6px;
    }}
    QListWidget::item:hover, QTreeWidget::item:hover, QTreeView::item:hover {{
        background: {c["hover"]};
    }}
    QListWidget::item:selected, QTreeWidget::item:selected, QTreeView::item:selected {{
        background: {c["selection"]};
        color: {c["text"]};
        font-weight: 500;
    }}
    QHeaderView::section {{
        color: {c["secondary"]};
        background: {c["surface2"]};
        border: 0;
        border-bottom: 1px solid {c["border"]};
        padding: 8px;
    }}

    QPushButton {{
        min-height: 20px;
        background: {c["surface2"]};
        color: {c["text"]};
        border: 1px solid {c["border"]};
        border-radius: 9px;
        padding: 7px 12px;
        font-weight: 500;
    }}
    QPushButton:hover {{ background: {c["hover"]}; border-color: {c["border_strong"]}; }}
    QPushButton:pressed {{ background: {c["elevated"]}; }}
    QPushButton:focus {{ border-color: {c["border_strong"]}; }}
    QPushButton:disabled {{
        color: {c["muted"]};
        background: {c["surface"]};
        border-color: {c["border"]};
    }}
    QPushButton#primaryButton {{
        background: {c["primary"]};
        color: {c["primary_text"]};
        border: 1px solid {c["primary"]};
        border-radius: 11px;
        font-weight: 600;
        padding: 8px 22px;
    }}
    QPushButton#primaryButton:hover {{
        background: {c["primary_hover"]};
        border-color: {c["primary_hover"]};
    }}
    QPushButton#dangerButton {{
        background: transparent;
        color: {c["danger"]};
        border-color: {c["border"]};
    }}

    QLineEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
        background: {c["input"]};
        color: {c["text"]};
        border: 1px solid {c["border"]};
        border-radius: 9px;
        padding: 7px 9px;
        selection-background-color: {c["selection"]};
        min-height: 20px;
    }}
    QLineEdit:hover, QTextEdit:hover, QSpinBox:hover,
    QDoubleSpinBox:hover, QComboBox:hover {{ border-color: {c["border_strong"]}; }}
    QLineEdit:focus, QTextEdit:focus, QSpinBox:focus,
    QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {c["accent"]}; }}
    QLineEdit::placeholder {{ color: {c["muted"]}; }}
    QComboBox::drop-down {{ border: 0; width: 24px; }}
    QComboBox QAbstractItemView {{
        background: {c["surface"]};
        color: {c["text"]};
        border: 1px solid {c["border"]};
        selection-background-color: {c["selection"]};
        outline: none;
    }}

    QCheckBox, QRadioButton {{ color: {c["text"]}; spacing: 8px; }}
    QCheckBox::indicator, QRadioButton::indicator {{
        width: 16px;
        height: 16px;
        border: 1px solid {c["border_strong"]};
        border-radius: 4px;
        background: {c["input"]};
    }}
    QCheckBox::indicator:checked {{
        background: {c["accent"]};
        border-color: {c["accent"]};
    }}
    QRadioButton::indicator, QRadioButton::indicator:checked {{ border-radius: 8px; }}
    QRadioButton::indicator:checked {{
        background: {c["accent"]};
        border-color: {c["accent"]};
    }}

    QTabWidget::pane {{
        background: {c["surface"]};
        border: 1px solid {c["border"]};
        border-radius: 9px;
        top: -1px;
    }}
    QTabBar::tab {{
        color: {c["secondary"]};
        background: transparent;
        padding: 9px 13px;
        margin-right: 2px;
        border: 0;
        border-bottom: 2px solid transparent;
    }}
    QTabBar::tab:hover {{ color: {c["text"]}; background: {c["hover"]}; }}
    QTabBar::tab:selected {{
        color: {c["text"]};
        border-bottom-color: {c["accent"]};
        font-weight: 600;
    }}

    QTabBar#storyTabs {{
        background: transparent;
    }}
    QTabBar#storyTabs::tab {{
        border: 0;
        border-radius: 9px;
        border-bottom: 0;
        padding: 8px 12px;
        margin: 2px;
    }}
    QTabBar#storyTabs::tab:selected {{
        background: {c["elevated"]};
        color: {c["text"]};
        border-bottom: 0;
    }}

    QTabBar#workspaceModeTabs {{
        background: {c["surface2"]};
        border: 1px solid {c["border"]};
        border-radius: 18px;
        padding: 2px;
    }}
    QTabBar#workspaceModeTabs::tab {{
        min-width: 92px;
        padding: 7px 14px;
        margin: 0;
        border: 0;
        border-radius: 15px;
        background: transparent;
        color: {c["secondary"]};
    }}
    QTabBar#workspaceModeTabs::tab:hover {{
        background: {c["hover"]};
        color: {c["text"]};
    }}
    QTabBar#workspaceModeTabs::tab:selected {{
        background: {c["surface"]};
        color: {c["text"]};
        border: 1px solid {c["border"]};
        font-weight: 600;
    }}

    QGroupBox {{
        background: {c["surface"]};
        border: 1px solid {c["border"]};
        border-radius: 10px;
        margin-top: 14px;
        padding-top: 10px;
        font-weight: 600;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 5px;
        color: {c["secondary"]};
    }}

    QProgressBar {{
        background: {c["surface2"]};
        color: {c["secondary"]};
        border: 0;
        border-radius: 4px;
        text-align: center;
        min-height: 10px;
    }}
    QProgressBar::chunk {{ background: {c["accent"]}; border-radius: 4px; }}

    QStatusBar {{
        background: {c["surface"]};
        color: {c["secondary"]};
        border-top: 1px solid {c["border"]};
        min-height: 22px;
    }}
    QStatusBar::item {{ border: 0; }}

    QMenu {{
        background: {c["surface"]};
        color: {c["text"]};
        border: 1px solid {c["border"]};
        padding: 4px;
    }}
    QMenu::item {{ padding: 7px 24px 7px 10px; border-radius: 5px; }}
    QMenu::item:selected {{ background: {c["hover"]}; }}
    QMenu::separator {{ height: 1px; background: {c["border"]}; margin: 4px 6px; }}

    QToolTip {{
        color: {c["text"]};
        background: {c["elevated"]};
        border: 1px solid {c["border_strong"]};
        padding: 5px 7px;
    }}
    QDialogButtonBox QPushButton {{ min-width: 76px; }}
    QSplitter::handle {{ background: transparent; width: 6px; }}
    QScrollArea, QAbstractScrollArea {{ background: transparent; border: 0; }}
    QScrollBar:vertical, QScrollBar:horizontal {{
        background: transparent;
        border: 0;
        margin: 2px;
        width: 10px;
        height: 10px;
    }}
    QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
        background: {c["border_strong"]};
        border-radius: 5px;
        min-height: 28px;
        min-width: 28px;
    }}
    QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{
        background: {c["muted"]};
    }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    """
