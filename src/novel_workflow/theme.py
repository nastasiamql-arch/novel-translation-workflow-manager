"""Shared modern UI tokens and Qt styles for NovelWorkflow."""
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication

TOKENS = {
    "spacing": (4, 8, 12, 16, 20, 24, 32),
    "radius": 12,
    "radius_card": 18,
    "radius_glass": 22,
    "control_height": 40,
    "motion_ms": 160,
}

# Dark follows VS Code's softer charcoal contrast instead of pure black.
_DARK = {
    "app": "#111318",
    "surface": "#191C23",
    "surface2": "#222733",
    "hover": "#2B3442",
    "elevated": "#293241",
    "glass": "rgba(28, 34, 44, 0.84)",
    "glass_strong": "rgba(31, 38, 50, 0.96)",
    "border": "rgba(220, 230, 245, 0.10)",
    "border_strong": "rgba(220, 230, 245, 0.18)",
    "text": "#F5F7FA",
    "secondary": "#B4BBC7",
    "muted": "#858E9C",
    "accent": "#5AA9FF",
    "accent_hover": "#83BEFF",
    "success": "#56C596",
    "warning": "#F3C969",
    "danger": "#F17A78",
    "selection": "#284B71",
    "input": "#171A20",
    "primary": "#4C9FFF",
    "primary_hover": "#6AAEFF",
    "primary_text": "#08121F",
}

# Light follows the quiet neutral shell used by modern ChatGPT desktop UI.
_LIGHT = {
    "app": "#F3F6FA",
    "surface": "#FFFFFF",
    "surface2": "#F3F6FA",
    "hover": "#E8F1FB",
    "elevated": "#FFFFFF",
    "glass": "rgba(255, 255, 255, 0.78)",
    "glass_strong": "rgba(255, 255, 255, 0.96)",
    "border": "rgba(35, 64, 105, 0.10)",
    "border_strong": "rgba(35, 64, 105, 0.18)",
    "text": "#182333",
    "secondary": "#566579",
    "muted": "#8290A2",
    "accent": "#1677D2",
    "accent_hover": "#0E68BF",
    "success": "#21815B",
    "warning": "#986D15",
    "danger": "#C7474F",
    "selection": "#D9EAFB",
    "input": "#FFFFFF",
    "primary": "#1677D2",
    "primary_hover": "#0E68BF",
    "primary_text": "#FFFFFF",
}

_EDITOR_DARK = {
    "background": "#1E1E1E",
    "foreground": "#D4D4D4",
    "gutter": "#18191B",
    "gutter_text": "#858B95",
    "current_line": "#252A32",
    "selection": "#264F78",
    "selection_text": "#FFFFFF",
    "find": "#665523",
    "find_text": "#FFF4CE",
    "tab": "#292D35",
    "tab_selected": "#353C48",
    "border": "#343A44",
    "accent": "#69AEFF",
}

_EDITOR_LIGHT = {
    "background": "#FFFFFF",
    "foreground": "#24262B",
    "gutter": "#F7F7F8",
    "gutter_text": "#697386",
    "current_line": "#F1F5FA",
    "selection": "#B9D7F5",
    "selection_text": "#202123",
    "find": "#FFE08A",
    "find_text": "#202123",
    "tab": "#F2F5F9",
    "tab_selected": "#FFFFFF",
    "border": "#E4EAF1",
    "accent": "#1677D2",
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
    """Return a softer, readable shell with adaptive light or dark work surfaces."""
    c = _DARK if _use_dark(appearance) else _LIGHT
    return f"""
    QWidget {{
        color: {c["text"]};
        font-family: "Segoe UI Variable Text", "Leelawadee UI", "Segoe UI", "Tahoma", sans-serif;
        font-size: 10pt;
    }}
    QMainWindow, QDialog {{ background: {c["app"]}; }}
    QWidget#appShell {{ background: transparent; }}
    QFrame#editorHeader, QFrame#utilityHeader, QFrame#profileHeader {{
        background: {c["glass_strong"]};
        border: 1px solid {c["border"]};
        border-radius: 16px;
    }}
    QFrame#settingsCard, QFrame#groupCard, QFrame#progressCard,
    QFrame#metricCard, QFrame#goalPanel, QFrame#progressRow,
    QFrame#explorerPanel, QFrame#editorPanel {{
        background: {c["glass_strong"]};
        border: 1px solid {c["border"]};
        border-radius: 18px;
    }}
    QLabel#pageTitle {{ font-size: 22pt; font-weight: 650; color: {c["text"]}; }}
    QLabel#pageSubtitle {{ color: {c["secondary"]}; font-size: 10pt; }}
    QLineEdit#librarySearch {{ min-height: 24px; border-radius: 18px; padding: 8px 15px; }}

    QToolBar#mainToolbar {{
        background: {c["glass_strong"]};
        border: 1px solid {c["border"]};
        border-radius: 18px;
        spacing: 5px;
        margin: 8px 14px 4px 14px;
        padding: 7px 12px;
    }}
    QToolBar#mainToolbar QToolButton {{
        padding: 8px 11px;
        border-radius: 11px;
        font-size: 9.5pt;
    }}
    QToolBar#mainToolbar QToolButton:hover {{ background: {c["hover"]}; }}
    QToolBar#mainToolbar QToolButton:pressed {{ background: {c["selection"]}; }}
    QLabel#brandTitle {{
        color: {c["text"]};
        font-size: 15pt;
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
        color: {c["text"]};
        background: transparent;
        border: 1px solid transparent;
        border-radius: 8px;
        padding: 7px 9px;
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
        background: {c["app"]};
        border: 0;
        padding: 8px;
    }}
    QListWidget#novelLibrary::item {{
        background: {c["surface"]};
        border: 1px solid {c["border"]};
        border-radius: 18px;
        padding: 10px;
        min-height: 274px;
    }}
    QListWidget#novelLibrary::item:hover {{
        background: {c["hover"]};
        border-color: {c["border_strong"]};
    }}
    QListWidget#novelLibrary::item:selected {{
        background: {c["surface2"]};
        border: 1px solid {c["accent"]};
    }}
    QFrame#workflowSidebar {{
        background: {c["surface"]};
        border: 1px solid {c["border"]};
        border-radius: 18px;
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
        border-radius: 12px;
        padding: 9px 14px 9px 34px;
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
        border-radius: 12px;
        padding: 8px 14px;
        font-weight: 650;
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
        border-radius: 12px;
        padding: 9px 14px;
        font-weight: 550;
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
        border-radius: 12px;
        padding: 8px 12px;
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
        padding: 10px 14px;
        margin-right: 3px;
        border-radius: 10px;
        border: 0;
        border-bottom: 2px solid transparent;
    }}
    QTabBar::tab:hover {{ color: {c["text"]}; background: {c["hover"]}; }}
    QTabBar::tab:selected {{
        color: {c["text"]};
        border-bottom-color: {c["accent"]};
        font-weight: 600;
    }}
    QTabBar#libraryStatusTabs {{
        background: {c["glass"]};
        border: 1px solid {c["border"]};
        border-radius: 15px;
        padding: 4px;
    }}
    QTabBar#libraryStatusTabs::tab {{
        min-width: 112px;
        min-height: 28px;
        padding: 8px 16px;
        margin: 0 2px;
        border: 0;
        border-radius: 11px;
    }}
    QTabBar#libraryStatusTabs::tab:selected {{
        color: {c["text"]};
        background: {c["surface"]};
        border: 1px solid {c["border"]};
    }}
    QTabBar#libraryStatusTabs::tab:hover {{
        background: {c["hover"]};
    }}


    QGroupBox {{
        background: {c["glass_strong"]};
        border: 1px solid {c["border"]};
        border-radius: 16px;
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
        width: 10px;
        height: 10px;
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
