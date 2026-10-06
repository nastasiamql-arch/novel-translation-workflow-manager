"""Accessible shared color tokens and component styles for Palantir: Novel."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

_SYSTEM_APPEARANCE_DARK: bool | None = None


# Quiet neutral surfaces share an understated blue accent. Selection, focus,
# current line and hover have independent roles across every appearance.
_LIGHT = {
    "app": "#F5F5F5", "surface": "#FFFFFF", "sidebar": "#F0F0F0",
    "surface2": "#E8E8E8", "hover": "#EAEAEA", "current_line": "#F0F5FB", "elevated": "#FFFFFF",
    "border": "#D8D8D8", "text": "#242424", "secondary": "#555555",
    "muted": "#606060", "disabled_text": "#606060",
    "accent": "#3269A8", "focus": "#155CA4", "success": "#246B45",
    "warning": "#735100", "danger": "#A51D15", "selection": "#BDD8F4",
    "selection_text": "#242424", "input": "#FFFFFF", "primary": "#3269A8",
    "primary_hover": "#23578F", "primary_text": "#FFFFFF",
    "status": "#E8E8E8", "status_text": "#242424",
}
_DARK = {
    "app": "#1E1E1E", "surface": "#252526", "sidebar": "#252526",
    "surface2": "#303030", "hover": "#383838", "current_line": "#2C3540", "elevated": "#2B2B2B",
    "border": "#3F3F3F", "text": "#E6E6E6", "secondary": "#C2C2C2",
    "muted": "#A0A0A0", "disabled_text": "#A0A0A0",
    "accent": "#80B9EF", "focus": "#A5D2FF", "success": "#91D49A",
    "warning": "#F1C66D", "danger": "#FF8A80", "selection": "#285582",
    "selection_text": "#F2F2F2", "input": "#303030", "primary": "#80B9EF",
    "primary_hover": "#A2CDFA", "primary_text": "#1E1E1E",
    "status": "#252526", "status_text": "#E6E6E6",
}


def _use_dark(appearance: str) -> bool:
    if appearance.lower() == "dark":
        return True
    if appearance.lower() == "light":
        return False
    if _SYSTEM_APPEARANCE_DARK is not None:
        return _SYSTEM_APPEARANCE_DARK
    app = QApplication.instance()
    return app is None or app.palette().color(QPalette.Window).lightness() < 128


def capture_system_appearance(app: QApplication | None = None) -> None:
    """Remember the OS appearance before the app installs its own palette."""
    global _SYSTEM_APPEARANCE_DARK
    if _SYSTEM_APPEARANCE_DARK is not None:
        return
    app = app or QApplication.instance()
    if app is None:
        return
    scheme = app.styleHints().colorScheme()
    if scheme == Qt.ColorScheme.Dark:
        _SYSTEM_APPEARANCE_DARK = True
    elif scheme == Qt.ColorScheme.Light:
        _SYSTEM_APPEARANCE_DARK = False
    else:
        _SYSTEM_APPEARANCE_DARK = (
            app.style().standardPalette().color(QPalette.Window).lightness() < 128
        )


def theme_colors(appearance: str = "Dark") -> dict[str, str]:
    """Return the shared semantic color tokens for one appearance."""
    return _DARK if _use_dark(appearance) else _LIGHT


def editor_colors(appearance: str = "Dark") -> dict[str, str]:
    """Map shared tokens to editor roles so custom editor styles stay in sync."""
    c = theme_colors(appearance)
    is_dark = _use_dark(appearance)
    return {
        "background": c["surface"], "foreground": c["text"],
        "gutter": c["sidebar"], "gutter_text": c["muted"],
        "current_line": c["current_line"], "selection": c["selection"],
        "selection_text": c["selection_text"],
        "find": "#454545" if is_dark else "#E5E5E5",
        "find_active": c["accent"],
        "find_text": c["primary_text"] if is_dark else c["text"],
        "tab": c["surface2"], "tab_selected": c["surface"],
        "disabled_text": c["disabled_text"],
        "border": c["border"], "accent": c["accent"],
        "focus": c["focus"], "panel": c["sidebar"],
    }


def qt_palette(appearance: str = "Dark") -> QPalette:
    """Build the native palette, including explicit high-contrast disabled roles."""
    c = theme_colors(appearance)
    palette = QPalette()
    for role, token in (
        (QPalette.Window, "app"), (QPalette.WindowText, "text"),
        (QPalette.Base, "surface"), (QPalette.AlternateBase, "sidebar"),
        (QPalette.Text, "text"), (QPalette.Button, "surface2"),
        (QPalette.ButtonText, "text"), (QPalette.Highlight, "selection"),
        (QPalette.HighlightedText, "selection_text"),
        (QPalette.ToolTipBase, "surface"), (QPalette.ToolTipText, "text"),
        (QPalette.Link, "accent"),
    ):
        palette.setColor(QPalette.Active, role, QColor(c[token]))
        palette.setColor(QPalette.Inactive, role, QColor(c[token]))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        palette.setColor(QPalette.Disabled, role, QColor(c["disabled_text"]))
    palette.setColor(QPalette.Disabled, QPalette.Window, QColor(c["app"]))
    palette.setColor(QPalette.Disabled, QPalette.Base, QColor(c["surface"]))
    palette.setColor(QPalette.Disabled, QPalette.Button, QColor(c["surface2"]))
    return palette


def application_stylesheet(appearance: str = "Dark") -> str:
    """Return one flat, keyboard-visible stylesheet for every app surface."""
    c = theme_colors(appearance)
    return f"""
    QWidget {{ color: {c['text']}; font-family: "Segoe UI", "Leelawadee UI", "Tahoma", sans-serif; font-size: 12pt; }}
    QFrame#navigationSidebar, QFrame#novelHeader {{ background: {c['sidebar']}; }}
    QToolButton#navigationItem {{ border: 0; border-left: 3px solid transparent; border-radius: 6px; padding: 8px 6px; text-align: left; }}
    QToolButton#navigationItem:checked {{ background: {c['selection']}; border-left: 3px solid {c['accent']}; font-weight: 600; }}
    QToolButton#navigationItem:focus {{ border-bottom: 2px solid {c['focus']}; }}
    QWidget:disabled {{ color: {c['disabled_text']}; }}
    QLabel:disabled, QAbstractButton:disabled, QTabBar::tab:disabled {{ color: {c['disabled_text']}; }}
    QMainWindow, QDialog, QWidget#appShell, QWidget#novelLibraryPage {{ background: {c['app']}; }}
    QLabel#pageTitle {{ color: {c['text']}; font-size: 18pt; font-weight: 600; }}
    QToolBar#mainToolbar {{ background: {c['sidebar']}; border: 0; border-bottom: 1px solid {c['border']}; spacing: 6px; padding: 3px 10px; margin: 0; min-height: 44px; }}
    QToolBar#mainToolbar QToolButton {{ color: {c['text']}; min-height: 36px; padding: 6px 12px; border: 0; border-radius: 0; }}
    QToolBar#mainToolbar QToolButton:disabled {{ color: {c['disabled_text']}; background: {c['surface2']}; }}
    QToolBar#mainToolbar QToolButton:focus {{ border-bottom: 3px solid {c['focus']}; }}
    QToolBar#mainToolbar QToolButton:hover, QToolButton:hover {{ background: {c['hover']}; }}
    QLabel#brandTitle {{ color: {c['text']}; font-size: 13pt; font-weight: 600; padding: 0 8px; }}
    QLabel#toolbarStory {{ color: {c['muted']}; padding-left: 12px; border-left: 1px solid {c['border']}; }}
    QLabel#sectionHeading {{ color: {c['secondary']}; font-size: 12pt; font-weight: 600; padding: 4px 0 7px; }}
    QLabel#mutedLabel, QLabel[class="muted"], QLabel#librarySubtitle, QLabel#emptyStateDescription {{ color: {c['muted']}; }}
    QLabel#metricValue {{ color: {c['text']}; font-size: 20pt; font-weight: 600; }}
    QLabel#metricLabel, QLabel#bodyLabel {{ color: {c['secondary']}; }}
    QFrame#storyStrip, QFrame#modeStrip, QFrame#bottomBar, QFrame#goalPanel,
    QFrame#metricCard, QFrame#progressRow, QFrame#editorPanel,
    QFrame#settingsCard, QFrame#libraryEmptyState {{ background: transparent; border: 0; border-radius: 0; }}
    QFrame#explorerPanel, QFrame#workflowSidebar, QFrame#editorHeader,
    QFrame#utilityHeader {{ background: {c['sidebar']}; border: 0; }}
    QFrame#editorHeader, QFrame#utilityHeader {{ border-bottom: 1px solid {c['border']}; }}
    QFrame#editorHeader QToolButton {{ color: {c['text']}; background: transparent; border: 0; min-height: 36px; padding: 6px 10px; }}
    QFrame#editorHeader QToolButton:disabled {{ color: {c['disabled_text']}; background: {c['surface2']}; }}
    QFrame#editorHeader QToolButton:hover {{ color: {c['text']}; background: {c['hover']}; }}
    QFrame#editorHeader QToolButton:focus {{ border-bottom: 3px solid {c['focus']}; }}
    QFrame#editorHeader QLabel#mutedLabel {{ color: {c['secondary']}; }}
    QToolButton {{ color: {c['text']}; background: transparent; border: 0; border-radius: 0; min-width: 30px; min-height: 30px; padding: 6px 9px; }}
    QToolButton:disabled {{ color: {c['disabled_text']}; background: {c['surface2']}; }}
    QToolButton:pressed {{ background: {c['selection']}; }}
    QToolButton:focus {{ border-bottom: 3px solid {c['focus']}; }}
    QListWidget, QTreeWidget, QTreeView, QTableWidget, QTableView {{ background: {c['surface']}; color: {c['text']}; border: 0; outline: none; selection-background-color: {c['selection']}; selection-color: {c['selection_text']}; }}
    QListWidget#novelLibrary {{ background: {c['sidebar']}; border: 0; padding: 5px 0; }}
    QListWidget#novelLibrary::item {{ background: transparent; border: 0; padding: 9px 10px; min-height: 44px; }}
    QListWidget#novelLibrary::item:hover {{ background: {c['hover']}; }}
    QListWidget#novelLibrary::item:selected {{ background: {c['selection']}; border: 0; color: {c['selection_text']}; }}
    QListWidget#novelCoverRail {{ background: transparent; border: 0; padding: 5px 2px; }}
    QListWidget#novelCoverRail::item {{ background: transparent; border: 0; padding: 1px; }}
    QListWidget#novelCoverRail::item:hover {{ background: {c['hover']}; }}
    QListWidget#novelCoverRail::item:selected {{ background: {c["selection"]}; border-left: 3px solid {c["accent"]}; }}
    QLabel#emptyStateIcon {{ color: {c['accent']}; font-size: 28pt; }}
    QLineEdit#librarySearch {{ background: {c['input']}; border: 1px solid {c['border']}; border-radius: 0; padding: 7px 10px; min-height: 30px; }}
    QTabBar#libraryStatusTabs {{ background: transparent; border: 0; }}
    QTabBar#libraryStatusTabs::tab {{ color: {c['secondary']}; background: transparent; border: 0; border-bottom: 2px solid transparent; min-height: 38px; padding: 6px 14px; margin: 0; }}
    QTabBar#libraryStatusTabs::tab:disabled {{ color: {c['disabled_text']}; background: {c['surface2']}; }}
    QTabBar#libraryStatusTabs::tab:hover {{ color: {c['text']}; background: {c['hover']}; }}
    QTabBar#libraryStatusTabs::tab:selected {{ color: {c['text']}; border-bottom: 3px solid {c['accent']}; font-weight: 600; }}
    QTabBar#libraryStatusTabs::tab:focus {{ border-bottom: 3px solid {c['focus']}; }}
    QListWidget#workflowSteps {{ background: transparent; border: 0; outline: 0; }}
    QListWidget#workflowSteps::item, QListWidget#workflowSteps::item:selected, QListWidget#workflowSteps::item:focus {{ background: transparent; color: {c['text']}; border: 0; }}
    QListWidget#workflowSteps::item:hover {{ background: {c['hover']}; }}
    QPushButton#workflowStageButton, QPushButton#vocabularyButton {{ color: {c['text']}; background: transparent; border: 0; border-radius: 0; min-height: 36px; padding: 0 10px; text-align: left; }}
    QPushButton#workflowStageButton:hover, QPushButton#vocabularyButton:hover {{ background: {c['hover']}; }}
    QPushButton#workflowStageButton[workflowActive="true"], QPushButton#vocabularyButton[workflowActive="true"] {{ background: {c['selection']}; border-left: 3px solid {c['accent']}; font-weight: 600; }}
    QPushButton#copyStepButton {{ color: {c['text']}; background: transparent; border: 0; border-radius: 0; min-height: 34px; padding: 7px 14px; font-weight: 600; }}
    QPushButton#copyStepButton:hover {{ color: {c['muted']}; background: transparent; text-decoration: none; }}
    QPushButton#copyStepButton:focus {{ color: {c['focus']}; background: transparent; border: 0; text-decoration: none; }}
    QPushButton#copyStepButton:disabled {{ color: {c['disabled_text']}; background: transparent; }}
    QLabel#editorStatusBar, QLabel#progressStatusBar, QLabel#goalStatusBar, QLabel#contextStatusBar {{ color: {c['status_text']}; background: transparent; border: 0; padding: 3px 9px; min-height: 24px; font-size: 10pt; }}
    QProgressBar#goalProgressStatusBar {{ background: {c['surface2']}; border: 0; border-radius: 0; min-height: 8px; max-height: 8px; }}
    QProgressBar#goalProgressStatusBar::chunk {{ background: {c['accent']}; border-radius: 0; }}
    QTreeView#fileTree {{ border: 0; padding: 2px; background: {c['surface']}; }}
    QListWidget:focus, QTreeWidget:focus, QTreeView:focus, QTableWidget:focus, QTableView:focus {{ outline: 2px solid {c['focus']}; }}
    QListWidget::item, QTreeWidget::item, QTreeView::item {{ color: {c['text']}; min-height: 28px; padding: 4px 7px; margin: 0; border: 0; }}
    QListWidget::item:hover, QTreeWidget::item:hover, QTreeView::item:hover {{ background: {c['hover']}; }}
    QListWidget::item:selected, QTreeWidget::item:selected, QTreeView::item:selected {{ background: {c['selection']}; color: {c['selection_text']}; }}
    QHeaderView::section {{ color: {c['secondary']}; background: {c['sidebar']}; border: 0; border-bottom: 1px solid {c['border']}; padding: 7px; }}
    QPushButton {{ min-height: 34px; background: {c['surface2']}; color: {c['text']}; border: 1px solid {c['border']}; border-radius: 0; padding: 6px 12px; }}
    QPushButton:hover {{ background: {c['hover']}; }}
    QPushButton:pressed {{ background: {c['selection']}; }}
    QPushButton:focus {{ border: 2px solid {c['focus']}; }}
    QPushButton:disabled {{ color: {c['disabled_text']}; background: {c['surface2']}; border-color: {c['border']}; }}
    QPushButton#primaryButton {{ background: {c['primary']}; color: {c['primary_text']}; border: 0; border-radius: 0; font-weight: 600; padding: 7px 16px; }}
    QPushButton#primaryButton:hover {{ background: {c['primary_hover']}; }}
    QPushButton#primaryButton:disabled {{ color: {c['disabled_text']}; background: {c['surface2']}; border: 1px solid {c['border']}; }}
    QPushButton#dangerButton {{ background: transparent; color: {c['danger']}; border: 1px solid {c['border']}; }}
    QLineEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{ background: {c['input']}; color: {c['text']}; border: 1px solid {c['border']}; border-radius: 0; padding: 7px 9px; selection-background-color: {c['selection']}; selection-color: {c['selection_text']}; min-height: 28px; }}
    QLineEdit:disabled, QTextEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{ color: {c['disabled_text']}; background: {c['surface2']}; }}
    QPlainTextEdit {{ background: {c['surface']}; color: {c['text']}; border: 0; selection-background-color: {c['selection']}; selection-color: {c['selection_text']}; }}
    QLineEdit:hover, QTextEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {{ border-color: {c['muted']}; }}
    QLineEdit:focus, QTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border: 2px solid {c['focus']}; }}
    QLineEdit::placeholder {{ color: {c['muted']}; }}
    QComboBox::drop-down {{ border: 0; width: 26px; }}
    QComboBox QAbstractItemView {{ background: {c['surface']}; color: {c['text']}; border: 1px solid {c['border']}; selection-background-color: {c['selection']}; selection-color: {c['selection_text']}; outline: none; }}
    QCheckBox, QRadioButton {{ color: {c['text']}; spacing: 8px; min-height: 28px; }}
    QCheckBox:disabled, QRadioButton:disabled {{ color: {c['disabled_text']}; }}
    QCheckBox::indicator, QRadioButton::indicator {{ width: 17px; height: 17px; border: 1px solid {c['muted']}; border-radius: 0; background: {c['input']}; }}
    QCheckBox::indicator:checked, QRadioButton::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; }}
    QRadioButton::indicator, QRadioButton::indicator:checked {{ border-radius: 9px; }}
    QTabWidget::pane {{ background: {c['surface']}; border: 0; border-top: 1px solid {c['border']}; }}
    QTabBar::tab {{ color: {c['secondary']}; background: {c['surface2']}; padding: 8px 14px; margin: 0; border: 0; border-right: 1px solid {c['border']}; min-height: 32px; }}
    QTabBar::tab:disabled {{ color: {c['disabled_text']}; background: {c['surface2']}; }}
    QTabBar::tab:hover {{ color: {c['text']}; background: {c['hover']}; }}
    QTabBar::tab:selected {{ color: {c['text']}; background: {c['surface']}; border-top: 2px solid {c['accent']}; }}
    QTabBar::tab:focus {{ border-bottom: 3px solid {c['focus']}; }}
    QGroupBox {{ background: transparent; border: 0; border-top: 1px solid {c['border']}; margin-top: 14px; padding-top: 9px; font-weight: 600; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 0; padding: 0 6px 0 0; color: {c['secondary']}; }}
    QProgressBar {{ background: {c['surface2']}; color: {c['text']}; border: 0; border-radius: 0; text-align: center; min-height: 20px; }}
    QProgressBar::chunk {{ background: {c['accent']}; border-radius: 0; }}
    QProgressDialog QLabel, QMessageBox QLabel {{ color: {c['text']}; font-size: 12pt; }}
    QProgressDialog QPushButton {{ min-width: 92px; min-height: 36px; }}
    QProgressDialog QProgressBar {{ min-height: 24px; font-size: 11pt; font-weight: 600; }}
    QStatusBar {{ background: {c['status']}; color: {c['status_text']}; border: 0; min-height: 30px; padding: 0; }}
    QStatusBar::item {{ border: 0; }}
    QMenu {{ background: {c['sidebar']}; color: {c['text']}; border: 1px solid {c['border']}; padding: 4px; }}
    QMenu::item {{ padding: 8px 26px 8px 12px; min-height: 28px; }}
    QMenu::item:selected {{ background: {c['selection']}; color: {c['selection_text']}; }}
    QMenu::item:disabled {{ color: {c['disabled_text']}; }}
    QMenu::separator {{ height: 1px; background: {c['border']}; margin: 5px 7px; }}
    QToolTip {{ color: {c['text']}; background: {c['surface']}; border: 1px solid {c['border']}; padding: 5px 7px; }}
    QDialogButtonBox QPushButton {{ min-width: 84px; }}
    QSplitter::handle {{ background: {c['border']}; width: 1px; height: 1px; }}
    QScrollArea, QAbstractScrollArea {{ background: transparent; border: 0; }}
    QScrollBar:vertical, QScrollBar:horizontal {{ background: {c['app']}; border: 0; margin: 0; width: 14px; height: 14px; }}
    QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{ background: {c['border']}; border: 3px solid {c['app']}; border-radius: 0; min-height: 36px; min-width: 36px; }}
    QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{ background: {c['muted']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    """
