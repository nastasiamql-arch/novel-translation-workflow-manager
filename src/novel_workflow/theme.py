"""Shared modern UI tokens and Qt styles for NovelWorkflow."""
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication

TOKENS = {
    "spacing": (4, 8, 12, 16, 20, 24, 32),
    "radius": 10,
    "radius_small": 8,
    "radius_control": 12,
    "radius_card": 16,
    "radius_glass": 20,
    "radius_floating": 24,
    "control_height": 38,
    "motion_ms": 160,
}

# Dark glass values are deliberately opaque enough to preserve dense Thai text.
_DARK = {
    "app": "#101216",
    "surface": "#171A20",
    "surface2": "#20242C",
    "hover": "#292E38",
    "elevated": "#262B35",
    "glass": "#20242C",
    "glass_strong": "#262B35",
    "border": "rgba(255, 255, 255, 0.16)",
    "border_strong": "rgba(255, 255, 255, 0.28)",
    "text": "#F5F5F7",
    "secondary": "#D0D4DB",
    "muted": "#B0B6C0",
    "accent": "#55A4FF",
    "accent_hover": "#3B9AFF",
    "success": "#30D158",
    "warning": "#FFD60A",
    "danger": "#FF453A",
    "selection": "#294E74",
    "input": "#171A20",
    "primary": "#1769B0",
    "primary_hover": "#125A98",
    "primary_text": "#FFFFFF",
}

# Cool manuscript-paper surfaces keep the editor distinct from glass controls.
_LIGHT = {
    "app": "#F3F5F8",
    "surface": "#FFFFFF",
    "surface2": "#EDF1F6",
    "hover": "#E8EFF7",
    "elevated": "#FFFFFF",
    "glass": "#FFFFFF",
    "glass_strong": "#FFFFFF",
    "border": "rgba(20, 30, 50, 0.16)",
    "border_strong": "rgba(20, 30, 50, 0.28)",
    "text": "#17181A",
    "secondary": "#343B45",
    "muted": "#505966",
    "accent": "#075DBA",
    "accent_hover": "#3196FF",
    "success": "#248A4B",
    "warning": "#A56A00",
    "danger": "#D33D36",
    "selection": "#D6E7F8",
    "input": "#FFFFFF",
    "primary": "#075DBA",
    "primary_hover": "#064D99",
    "primary_text": "#FFFFFF",
}

_EDITOR_DARK = {
    "background": "#171A20",
    "foreground": "#E6E8ED",
    "gutter": "#14171C",
    "gutter_text": "#B0B6C0",
    "current_line": "#202630",
    "selection": "#294E74",
    "selection_text": "#FFFFFF",
    "find": "#665523",
    "find_active": "#385B36",
    "find_text": "#FFF4CE",
    "tab": "#14171C",
    "tab_selected": "#171A20",
    "border": "rgba(255, 255, 255, 0.18)",
    "accent": "#55A4FF",
    "panel": "#20242C",
}

_EDITOR_LIGHT = {
    "background": "#FFFFFF",
    "foreground": "#252A32",
    "gutter": "#F7F9FC",
    "gutter_text": "#505966",
    "current_line": "#F4F7FB",
    "selection": "#C9DDF2",
    "selection_text": "#17181A",
    "find": "#F4E6B2",
    "find_active": "#D4E5F7",
    "find_text": "#17181A",
    "tab": "#F3F5F8",
    "tab_selected": "#FFFFFF",
    "border": "rgba(20, 30, 50, 0.16)",
    "accent": "#075DBA",
    "panel": "#FFFFFF",
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


def editor_colors(appearance: str = "Light") -> dict[str, str]:
    """Colors for the writing surface and its line-number gutter."""
    return _EDITOR_DARK if _use_dark(appearance) else _EDITOR_LIGHT


def application_stylesheet(appearance: str = "Light") -> str:
    """Return the adaptive Palantir: Novel writing-workspace design system."""
    c = _DARK if _use_dark(appearance) else _LIGHT
    return f"""
    QWidget {{
        color: {c["text"]};
        font-family: "Segoe UI Variable Text", "Leelawadee UI", "Segoe UI", "Tahoma", sans-serif;
        font-size: 11pt;
    }}
    QWidget:disabled {{ color: {c["muted"]}; }}
    QMainWindow, QDialog {{
        background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 1,
            stop: 0 {c["app"]}, stop: 1 {c["surface2"]});
    }}
    QWidget#appShell, QWidget#novelLibraryPage {{ background: transparent; }}

    QToolBar#mainToolbar {{
        background: {c["glass_strong"]};
        border: 1px solid {c["border_strong"]};
        border-radius: 20px;
        spacing: 6px;
        padding: 4px 10px;
        margin: 10px 16px 4px 16px;
        min-height: 48px;
    }}
    QToolBar#mainToolbar QToolButton {{
        padding: 8px 11px;
        border-radius: 12px;
        font-size: 10.5pt;
    }}
    QToolBar#mainToolbar QToolButton:hover {{
        background: {c["hover"]};
    }}
    QLabel#brandTitle {{
        color: {c["text"]};
        font-size: 15pt;
        font-weight: 650;
        padding: 0 8px 0 3px;
    }}
    QLabel#toolbarStory {{
        color: {c["muted"]};
        font-size: 10.5pt;
        padding-left: 14px;
        border-left: 1px solid {c["border_strong"]};
    }}
    QLabel#sectionHeading {{
        color: {c["secondary"]};
        font-size: 10pt;
        font-weight: 600;
        letter-spacing: 0.4px;
        padding: 2px 3px 5px 3px;
    }}
    QLabel#mutedLabel, QLabel[class="muted"] {{ color: {c["muted"]}; }}
    QLabel#metricValue {{ color: {c["text"]}; font-size: 22pt; font-weight: 600; }}
    QLabel#metricLabel {{ color: {c["text"]}; font-size: 11pt; font-weight: 600; }}
    QLabel#bodyLabel {{ color: {c["secondary"]}; }}

    QFrame#storyStrip, QFrame#modeStrip, QFrame#bottomBar {{
        background: {c["glass"]};
        border: 1px solid {c["border"]};
        border-radius: 16px;
    }}
    QFrame#goalPanel, QFrame#metricCard, QFrame#progressRow {{
        background: {c["elevated"]};
        border: 1px solid {c["border"]};
        border-radius: 18px;
    }}
    QFrame#explorerPanel, QFrame#editorPanel, QFrame#editorHeader,
    QFrame#utilityHeader {{
        background: {c["glass"]};
        border: 1px solid {c["border"]};
        border-radius: 14px;
    }}
    QFrame#settingsCard {{
        background: {c["glass"]};
        border: 1px solid {c["border"]};
        border-radius: 18px;
    }}

    QToolButton {{
        color: {c["text"]};
        background: transparent;
        border: 1px solid transparent;
        border-radius: 11px;
        padding: 8px 10px;
        font-weight: 550;
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
    QListWidget#novelLibrary {{
        background: transparent;
        border: 0;
        padding: 10px 2px 14px 2px;
    }}
    QListWidget#novelLibrary::item {{
        background: {c["glass_strong"]};
        border: 1px solid {c["border"]};
        border-radius: 18px;
        padding: 10px;
        min-height: 270px;
    }}
    QListWidget#novelLibrary::item:hover {{
        background: {c["hover"]};
        border-color: {c["border_strong"]};
    }}
    QListWidget#novelLibrary::item:selected {{
        background: {c["elevated"]};
        border: 1px solid {c["accent"]};
    }}
    QFrame#workflowSidebar {{
        background: {c["glass"]};
        border: 1px solid {c["border_strong"]};
        border-radius: 20px;
    }}
    QFrame#libraryEmptyState {{
        background: {c["glass"]};
        border: 1px solid {c["border"]};
        border-radius: 22px;
    }}
    QLabel#librarySubtitle, QLabel#emptyStateDescription {{
        color: {c["muted"]};
        font-size: 10.5pt;
    }}
    QLabel#emptyStateIcon {{
        color: {c["accent"]};
        font-size: 28pt;
        font-weight: 300;
    }}
    QLineEdit#librarySearch {{
        min-height: 28px;
        border-radius: 20px;
        padding-left: 14px;
        background: {c["glass_strong"]};
    }}
    QTabBar#libraryStatusTabs {{
        background: {c["glass"]};
        border: 1px solid {c["border"]};
        border-radius: 16px;
        padding: 4px;
    }}
    QTabBar#libraryStatusTabs::tab {{
        color: {c["muted"]};
        background: transparent;
        border: 0;
        border-radius: 12px;
        min-height: 34px;
        padding: 5px 20px;
        margin-right: 3px;
    }}
    QTabBar#libraryStatusTabs::tab:hover {{
        color: {c["text"]};
        background: {c["hover"]};
    }}
    QTabBar#libraryStatusTabs::tab:selected {{
        color: {c["text"]};
        background: {c["elevated"]};
        border: 1px solid {c["border"]};
        font-weight: 600;
    }}
    QListWidget#workflowSteps {{
        background: transparent;
        border: 0;
        outline: 0;
    }}
    QListWidget#workflowSteps::item,
    QListWidget#workflowSteps::item:selected,
    QListWidget#workflowSteps::item:focus,
    QListWidget#workflowSteps::item:hover {{
        background: transparent;
        color: {c["text"]};
        border: 0;
        outline: 0;
    }}
    QPushButton#workflowStageButton, QPushButton#vocabularyButton {{
        color: {c["text"]};
        background: {c["surface2"]};
        border: 1px solid {c["border"]};
        border-radius: 8px;
        padding: 7px 12px 7px 32px;
        text-align: left;
        font-weight: 600;
    }}
    QPushButton#workflowStageButton:hover, QPushButton#vocabularyButton:hover {{
        background: {c["surface2"]};
        border-color: {c["border"]};
    }}
    QPushButton#workflowStageButton:focus, QPushButton#vocabularyButton:focus {{
        border: 1px solid {c["border"]};
        outline: none;
    }}
    QPushButton#copyStepButton {{
        color: {c["text"]};
        background: {c["selection"]};
        border: 1px solid {c["accent"]};
        border-radius: 8px;
        padding: 7px 12px;
        font-weight: 700;
    }}
    QLabel#editorStatusBar {{
        color: {c["secondary"]};
        background: {c["surface"]};
        padding: 3px 10px;
        min-height: 20px;
    }}
    QLabel#progressStatusBar, QLabel#goalStatusBar {{
        color: {c["secondary"]};
        background: {c["surface"]};
        padding: 3px 8px;
        min-height: 20px;
    }}
    QProgressBar#goalProgressStatusBar {{
        background: {c["surface2"]};
        border: 0;
        border-radius: 6px;
        min-height: 12px;
        max-height: 12px;
    }}
    QProgressBar#goalProgressStatusBar::chunk {{
        background: {c["accent"]};
        border-radius: 6px;
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
    QPushButton:focus {{ border: 2px solid {c["accent"]}; }}
    QPushButton:disabled {{
        color: {c["secondary"]};
        background: {c["surface2"]};
        border-color: {c["border_strong"]};
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
    QPlainTextEdit {{
        background: {c["surface"]};
        color: {c["text"]};
        border: 1px solid {c["border"]};
        selection-background-color: {c["selection"]};
        selection-color: {c["text"]};
    }}
    QLineEdit:hover, QTextEdit:hover, QSpinBox:hover,
    QDoubleSpinBox:hover, QComboBox:hover {{ border-color: {c["border_strong"]}; }}
    QLineEdit:focus, QTextEdit:focus, QSpinBox:focus,
    QDoubleSpinBox:focus, QComboBox:focus {{ border: 2px solid {c["accent"]}; }}
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
        color: {c["text"]};
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
        color: {c["text"]};
        border: 0;
        border-radius: 4px;
        text-align: center;
        min-height: 18px;
        font-weight: 600;
    }}
    QProgressBar::chunk {{ background: {c["accent"]}; border-radius: 4px; }}

    QProgressDialog QLabel {{
        color: {c["text"]};
        font-size: 11pt;
        font-weight: 600;
    }}
    QMessageBox QLabel {{ color: {c["text"]}; font-size: 11pt; }}

    QStatusBar {{
        background: {c["surface"]};
        color: {c["secondary"]};
        border-top: 1px solid {c["border"]};
        min-height: 28px;
        padding-top: 2px;
        padding-bottom: 2px;
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
        background: {c["surface2"]};
        border: 0;
        margin: 1px;
        width: 16px;
        height: 16px;
    }}
    QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
        background: {c["border_strong"]};
        border: 2px solid {c["surface2"]};
        border-radius: 7px;
        min-height: 42px;
        min-width: 42px;
    }}
    QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{
        background: {c["accent"]};
    }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    """
