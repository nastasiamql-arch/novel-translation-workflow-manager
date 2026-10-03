"""Flat Visual Studio Code-inspired themes for the Palantir: Novel UI."""
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication


_DARK = {
    "app": "#1E1E1E", "surface": "#1E1E1E", "sidebar": "#252526",
    "surface2": "#2D2D2D", "hover": "#2A2D2E", "elevated": "#252526",
    "border": "#3C3C3C", "text": "#D4D4D4", "secondary": "#CCCCCC",
    "muted": "#A8A8A8", "accent": "#007ACC", "success": "#89D185",
    "warning": "#CCA700", "danger": "#F48771", "selection": "#264F78",
    "input": "#3C3C3C", "primary": "#0E639C", "primary_hover": "#1177BB",
    "primary_text": "#FFFFFF", "status": "#007ACC",
}
_LIGHT = {
    "app": "#F3F3F3", "surface": "#FFFFFF", "sidebar": "#F3F3F3",
    "surface2": "#E5E5E5", "hover": "#E8E8E8", "elevated": "#F3F3F3",
    "border": "#D4D4D4", "text": "#333333", "secondary": "#3B3B3B",
    "muted": "#616161", "accent": "#007ACC", "success": "#388A34",
    "warning": "#8A6D00", "danger": "#A1260D", "selection": "#ADD6FF",
    "input": "#FFFFFF", "primary": "#0E639C", "primary_hover": "#1177BB",
    "primary_text": "#FFFFFF", "status": "#007ACC",
}
_EDITOR_DARK = {
    "background": "#1E1E1E", "foreground": "#D4D4D4", "gutter": "#1E1E1E",
    "gutter_text": "#B0B0B0", "current_line": "#2A2D2E", "selection": "#264F78",
    "selection_text": "#FFFFFF", "find": "#613214", "find_active": "#A8AC6C",
    "find_text": "#FFFFFF", "tab": "#2D2D2D", "tab_selected": "#1E1E1E",
    "border": "#3C3C3C", "accent": "#007ACC", "panel": "#252526",
}
_EDITOR_LIGHT = {
    "background": "#FFFFFF", "foreground": "#333333", "gutter": "#FFFFFF",
    "gutter_text": "#237893", "current_line": "#F3F3F3", "selection": "#ADD6FF",
    "selection_text": "#333333", "find": "#F5D96B", "find_active": "#A8AC6C",
    "find_text": "#333333", "tab": "#F3F3F3", "tab_selected": "#FFFFFF",
    "border": "#D4D4D4", "accent": "#007ACC", "panel": "#F3F3F3",
}


def _use_dark(appearance: str) -> bool:
    if appearance.lower() == "dark":
        return True
    if appearance.lower() == "light":
        return False
    app = QApplication.instance()
    return app is None or app.palette().color(QPalette.Window).lightness() < 128


def editor_colors(appearance: str = "Dark") -> dict[str, str]:
    """Return VS Code Dark+ or Light+ editor colors."""
    return _EDITOR_DARK if _use_dark(appearance) else _EDITOR_LIGHT


def application_stylesheet(appearance: str = "Dark") -> str:
    """Return a flat VS Code-inspired stylesheet with no decorative card frames."""
    c = _DARK if _use_dark(appearance) else _LIGHT
    return f"""
    QWidget {{ color: {c['text']}; font-family: "Segoe UI", "Leelawadee UI", "Tahoma", sans-serif; font-size: 11pt; }}
    QWidget:disabled {{ color: {c['muted']}; }}
    QLabel:disabled, QAbstractButton:disabled, QTabBar::tab:disabled {{ color: {c['muted']}; }}
    QMainWindow, QDialog, QWidget#appShell, QWidget#novelLibraryPage {{ background: {c['app']}; }}
    QLabel#pageTitle {{ color: {c['text']}; font-size: 18pt; font-weight: 600; }}
    QToolBar#mainToolbar {{ background: {c['sidebar']}; border: 0; border-bottom: 1px solid {c['border']}; spacing: 4px; padding: 2px 8px; margin: 0; min-height: 42px; }}
    QToolBar#mainToolbar QToolButton {{ color: {c['text']}; min-height: 32px; padding: 6px 10px; border: 0; border-radius: 0; }}
    QToolBar#mainToolbar QToolButton:disabled {{ color: {c['muted']}; background: transparent; }}
    QToolBar#mainToolbar QToolButton:focus {{ border-bottom: 2px solid {c['accent']}; }}
    QToolBar#mainToolbar QToolButton:hover, QToolButton:hover {{ background: {c['hover']}; }}
    QLabel#brandTitle {{ color: {c['text']}; font-size: 12pt; font-weight: 600; padding: 0 8px; }}
    QLabel#toolbarStory {{ color: {c['muted']}; padding-left: 12px; border-left: 1px solid {c['border']}; }}
    QLabel#sectionHeading {{ color: {c['secondary']}; font-size: 11pt; font-weight: 600; padding: 3px 0 6px; }}
    QLabel#mutedLabel, QLabel[class="muted"], QLabel#librarySubtitle, QLabel#emptyStateDescription {{ color: {c['muted']}; }}
    QLabel#metricValue {{ color: {c['text']}; font-size: 20pt; font-weight: 600; }}
    QLabel#metricLabel, QLabel#bodyLabel {{ color: {c['secondary']}; }}
    QFrame#storyStrip, QFrame#modeStrip, QFrame#bottomBar, QFrame#goalPanel,
    QFrame#metricCard, QFrame#progressRow, QFrame#editorPanel,
    QFrame#settingsCard, QFrame#libraryEmptyState {{ background: transparent; border: 0; border-radius: 0; }}
    QFrame#explorerPanel, QFrame#workflowSidebar, QFrame#editorHeader,
    QFrame#utilityHeader {{ background: {c['sidebar']}; border: 0; }}
    QFrame#editorHeader, QFrame#utilityHeader {{ border-bottom: 1px solid {c['border']}; }}
    QToolButton {{ color: {c['text']}; background: transparent; border: 0; border-radius: 0; min-width: 26px; min-height: 26px; padding: 6px 8px; }}
    QToolButton:disabled {{ color: {c['muted']}; background: transparent; }}
    QToolButton:pressed {{ background: {c['selection']}; }}
    QToolButton:focus {{ border-bottom: 2px solid {c['accent']}; }}
    QListWidget, QTreeWidget, QTreeView, QTableWidget, QTableView {{ background: {c['surface']}; color: {c['text']}; border: 0; outline: none; selection-background-color: {c['selection']}; selection-color: {c['text']}; }}
    QListWidget#novelLibrary {{ background: {c['sidebar']}; border: 0; padding: 4px 0; }}
    QListWidget#novelLibrary::item {{ background: transparent; border: 0; padding: 8px; min-height: 42px; }}
    QListWidget#novelLibrary::item:hover {{ background: {c['hover']}; }}
    QListWidget#novelLibrary::item:selected {{ background: {c['selection']}; border: 0; }}
    QLabel#emptyStateIcon {{ color: {c['accent']}; font-size: 28pt; }}
    QLineEdit#librarySearch {{ background: {c['input']}; border: 1px solid {c['border']}; border-radius: 0; padding: 5px 8px; }}
    QTabBar#libraryStatusTabs {{ background: transparent; border: 0; }}
    QTabBar#libraryStatusTabs::tab {{ color: {c['secondary']}; background: transparent; border: 0; border-bottom: 1px solid transparent; min-height: 34px; padding: 5px 14px; margin: 0; }}
    QTabBar#libraryStatusTabs::tab:disabled {{ color: {c['muted']}; }}
    QTabBar#libraryStatusTabs::tab:hover {{ color: {c['text']}; background: {c['hover']}; }}
    QTabBar#libraryStatusTabs::tab:selected {{ color: {c['text']}; border-bottom: 2px solid {c['accent']}; font-weight: 600; }}
    QListWidget#workflowSteps {{ background: transparent; border: 0; outline: 0; }}
    QListWidget#workflowSteps::item, QListWidget#workflowSteps::item:selected, QListWidget#workflowSteps::item:focus {{ background: transparent; color: {c['text']}; border: 0; }}
    QListWidget#workflowSteps::item:hover {{ background: {c['hover']}; }}
    QPushButton#workflowStageButton, QPushButton#vocabularyButton {{ color: {c['text']}; background: transparent; border: 0; border-left: 2px solid transparent; border-radius: 0; padding: 7px 10px 7px 32px; text-align: left; }}
    QPushButton#workflowStageButton:hover, QPushButton#vocabularyButton:hover {{ background: {c['hover']}; }}
    QPushButton#workflowStageButton:checked, QPushButton#vocabularyButton:checked {{ background: {c['hover']}; border-left-color: {c['accent']}; }}
    QPushButton#copyStepButton {{ color: {c['primary_text']}; background: {c['primary']}; border: 0; border-radius: 0; padding: 7px 12px; font-weight: 600; }}
    QLabel#editorStatusBar, QLabel#progressStatusBar, QLabel#goalStatusBar, QLabel#contextStatusBar {{ color: #FFFFFF; background: transparent; border: 0; padding: 2px 8px; min-height: 22px; font-size: 10pt; }}
    QProgressBar#goalProgressStatusBar {{ background: {c['surface2']}; border: 0; border-radius: 0; min-height: 8px; max-height: 8px; }}
    QProgressBar#goalProgressStatusBar::chunk {{ background: {c['accent']}; border-radius: 0; }}
    QTreeView#fileTree {{ border: 0; padding: 2px; background: {c['surface']}; }}
    QListWidget:focus, QTreeWidget:focus, QTreeView:focus, QTableWidget:focus, QTableView:focus {{ outline: 1px solid {c['accent']}; }}
    QListWidget::item, QTreeWidget::item, QTreeView::item {{ color: {c['text']}; min-height: 24px; padding: 3px 6px; margin: 0; border: 0; }}
    QListWidget::item:hover, QTreeWidget::item:hover, QTreeView::item:hover {{ background: {c['hover']}; }}
    QListWidget::item:selected, QTreeWidget::item:selected, QTreeView::item:selected {{ background: {c['selection']}; color: {c['text']}; }}
    QHeaderView::section {{ color: {c['secondary']}; background: {c['sidebar']}; border: 0; border-bottom: 1px solid {c['border']}; padding: 6px; }}
    QPushButton {{ min-height: 28px; background: {c['surface2']}; color: {c['text']}; border: 1px solid {c['border']}; border-radius: 0; padding: 5px 10px; }}
    QPushButton:hover {{ background: {c['hover']}; }}
    QPushButton:pressed {{ background: {c['selection']}; }}
    QPushButton:focus {{ border: 1px solid {c['accent']}; }}
    QPushButton:disabled {{ color: {c['muted']}; background: {c['surface2']}; border-color: {c['border']}; }}
    QPushButton#primaryButton {{ background: {c['primary']}; color: {c['primary_text']}; border: 0; border-radius: 0; font-weight: 600; padding: 6px 16px; }}
    QPushButton#primaryButton:hover {{ background: {c['primary_hover']}; }}
    QPushButton#dangerButton {{ background: transparent; color: {c['danger']}; border: 1px solid {c['border']}; }}
    QLineEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{ background: {c['input']}; color: {c['text']}; border: 1px solid {c['border']}; border-radius: 0; padding: 6px 8px; selection-background-color: {c['selection']}; min-height: 24px; }}
    QPlainTextEdit {{ background: {c['surface']}; color: {c['text']}; border: 0; selection-background-color: {c['selection']}; selection-color: {c['text']}; }}
    QLineEdit:hover, QTextEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {{ border-color: {c['muted']}; }}
    QLineEdit:focus, QTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border: 1px solid {c['accent']}; }}
    QLineEdit::placeholder {{ color: {c['muted']}; }}
    QComboBox::drop-down {{ border: 0; width: 22px; }}
    QComboBox QAbstractItemView {{ background: {c['surface']}; color: {c['text']}; border: 1px solid {c['border']}; selection-background-color: {c['selection']}; outline: none; }}
    QCheckBox, QRadioButton {{ color: {c['text']}; spacing: 7px; }}
    QCheckBox::indicator, QRadioButton::indicator {{ width: 15px; height: 15px; border: 1px solid {c['muted']}; border-radius: 0; background: {c['input']}; }}
    QCheckBox::indicator:checked, QRadioButton::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; }}
    QRadioButton::indicator, QRadioButton::indicator:checked {{ border-radius: 8px; }}
    QTabWidget::pane {{ background: {c['surface']}; border: 0; border-top: 1px solid {c['border']}; }}
    QTabBar::tab {{ color: {c['secondary']}; background: {c['surface2']}; padding: 8px 14px; margin: 0; border: 0; border-right: 1px solid {c['border']}; min-height: 28px; }}
    QTabBar::tab:disabled {{ color: {c['muted']}; }}
    QTabBar::tab:hover {{ color: {c['text']}; background: {c['hover']}; }}
    QTabBar::tab:selected {{ color: {c['text']}; background: {c['surface']}; border-top: 1px solid {c['accent']}; }}
    QGroupBox {{ background: transparent; border: 0; border-top: 1px solid {c['border']}; margin-top: 12px; padding-top: 8px; font-weight: 600; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 0; padding: 0 6px 0 0; color: {c['secondary']}; }}
    QProgressBar {{ background: {c['surface2']}; color: {c['text']}; border: 0; border-radius: 0; text-align: center; min-height: 18px; }}
    QProgressBar::chunk {{ background: {c['accent']}; border-radius: 0; }}
    QProgressDialog QLabel, QMessageBox QLabel {{ color: {c['text']}; font-size: 11pt; }}
    QProgressDialog QPushButton {{ min-width: 88px; min-height: 32px; }}
    QProgressDialog QProgressBar {{ min-height: 22px; font-size: 10pt; font-weight: 600; }}
    QStatusBar {{ background: {c['status']}; color: #FFFFFF; border: 0; min-height: 28px; padding: 0; }}
    QStatusBar::item {{ border: 0; }}
    QMenu {{ background: {c['sidebar']}; color: {c['text']}; border: 1px solid {c['border']}; padding: 3px; }}
    QMenu::item {{ padding: 6px 24px 6px 10px; }}
    QMenu::item:selected {{ background: {c['selection']}; }}
    QMenu::separator {{ height: 1px; background: {c['border']}; margin: 4px 6px; }}
    QToolTip {{ color: {c['text']}; background: {c['sidebar']}; border: 1px solid {c['border']}; padding: 4px 6px; }}
    QDialogButtonBox QPushButton {{ min-width: 76px; }}
    QSplitter::handle {{ background: {c['border']}; width: 1px; height: 1px; }}
    QScrollArea, QAbstractScrollArea {{ background: transparent; border: 0; }}
    QScrollBar:vertical, QScrollBar:horizontal {{ background: {c['app']}; border: 0; margin: 0; width: 14px; height: 14px; }}
    QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{ background: {c['border']}; border: 3px solid {c['app']}; border-radius: 0; min-height: 36px; min-width: 36px; }}
    QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{ background: {c['muted']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    """
