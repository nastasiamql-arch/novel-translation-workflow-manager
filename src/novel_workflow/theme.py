"""Accessible semantic color tokens for the Palantir Slate Blue themes."""

from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

_SYSTEM_APPEARANCE_DARK: bool | None = None


# Quiet neutral surfaces share an understated blue accent. Selection, focus,
# current line and hover have independent roles across every appearance.
_LIGHT = {
    "scroll_track": "#E9EEF6", "scroll_thumb": "#808080", "scroll_thumb_hover": "#626262",
    "app": "#F6F8FC", "surface": "#FFFFFF", "sidebar": "#F0F3F8",
    "surface2": "#E9EEF6", "item_selection": "#DDEAFF", "hover": "#E7ECF5", "current_line": "#F0F4FC", "elevated": "#FFFFFF",
    "control_border": "#7A808A", "border": "#DCE3ED", "text": "#1E293B", "secondary": "#526176",
    "muted": "#526176", "disabled_text": "#526176",
    "accent": "#2459A6", "focus": "#474747", "success": "#127561",
    "warning": "#A05B18", "danger": "#B63838", "selection": "#DDEAFF",
    "selection_text": "#19457F", "input": "#FFFFFF", "primary": "#2459A6",
    "primary_hover": "#19457F", "primary_text": "#FFFFFF",
    "status": "#F0F3F8", "status_text": "#19457F",
}
_DARK = {
    "scroll_track": "#1C2430", "scroll_thumb": "#858585", "scroll_thumb_hover": "#A0A0A0",
    "app": "#181D27", "surface": "#222A37", "sidebar": "#1C2430",
    "surface2": "#303B4C", "item_selection": "#385374", "hover": "#374357", "current_line": "#293546", "elevated": "#303B4C",
    "control_border": "#858FA0", "border": "#3C4758", "text": "#EDF2F8", "secondary": "#ADB9CC",
    "muted": "#ADB9CC", "disabled_text": "#ADB9CC",
    "accent": "#80ADFF", "focus": "#C2C2C2", "success": "#56C5A7",
    "warning": "#F1B963", "danger": "#FF8585", "selection": "#344D70",
    "selection_text": "#EDF2F8", "input": "#303B4C", "primary": "#80ADFF",
    "primary_hover": "#A2C4FF", "primary_text": "#181D27",
    "status": "#222A37", "status_text": "#EDF2F8",
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
        "find_text": c["primary_text"],
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
        (QPalette.Link, "accent"), (QPalette.PlaceholderText, "muted"),
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
    resources = Path(__file__).parent / 'resources'
    arrow_theme = 'dark' if _use_dark(appearance) else 'light'
    up_arrow = (resources / f'spin-up-{arrow_theme}.svg').as_posix()
    down_arrow = (resources / f'spin-down-{arrow_theme}.svg').as_posix()
    check_mark = (resources / f'check-{arrow_theme}.svg').as_posix()
    return f"""
    QWidget {{ color: {c['text']}; font-family: "Segoe UI", "Leelawadee UI", "Tahoma", sans-serif; font-size: 11pt; }}
    QFrame#navigationSidebar {{ background: {c['sidebar']}; border-right: 1px solid {c['border']}; }}
    QFrame#novelHeader {{ background: {c['surface']}; border-bottom: 1px solid {c['border']}; }}
    QToolButton#navigationBrand {{ color: {c['text']}; background: transparent; border: 0; border-radius: 10px; font-size: 10pt; font-weight: 700; text-align: left; padding: 10px 6px; min-height: 34px; }}
    QToolButton#navigationBrand:hover {{ background: {c['hover']}; }}
    QToolButton#navigationItem {{ border: 0; border-radius: 10px; padding: 11px 10px; text-align: left; min-height: 34px; }}
    QToolButton#navigationItem:hover {{ background: {c['hover']}; }}
    QToolButton#navigationItem:checked {{ background: {c['item_selection']}; color: {c['text']}; font-weight: 600; }}
    QToolButton#navigationItem[keyboardFocus="true"] {{ border-bottom: 2px solid {c['focus']}; }}
    QWidget:disabled {{ color: {c['disabled_text']}; }}
    QLabel:disabled, QAbstractButton:disabled, QTabBar::tab:disabled {{ color: {c['disabled_text']}; }}
    QMainWindow, QDialog, QWidget#appShell, QWidget#novelLibraryPage {{ background: {c['app']}; }}
    QWidget#polishHistoryCards {{ background: {c['app']}; }}
    QLabel#completedTranslationSummary {{ color: {c['text']}; font-family: "Segoe UI"; font-size: 10pt; }}
    QLabel#novelGoalLabel {{ color: {c['secondary']}; font-size: 10pt; }}
    QProgressBar#novelGoalProgress {{ background: {c['surface2']}; min-height: 7px; max-height: 7px; border-radius: 3px; }}
    QProgressBar#novelGoalProgress::chunk {{ background: {c['accent']}; border-radius: 3px; }}
    QProgressBar#novelGoalProgress[goalComplete="true"]::chunk {{ background: {c['success']}; }}
    QToolButton#novelGoalEdit, QToolButton#novelGoalReset {{ color: {c['accent']}; border: 0; border-radius: 5px; min-width: 0; min-height: 24px; padding: 2px 6px; font-size: 9pt; }}
    QToolButton#novelGoalEdit:hover, QToolButton#novelGoalReset:hover {{ background: {c['item_selection']}; }}
    QToolButton#novelGoalEdit:focus, QToolButton#novelGoalReset:focus {{ border-bottom: 2px solid {c['focus']}; }}
    QLabel#historyRangeTitle {{ color: {c['text']}; font-size: 11pt; font-weight: 600; }}
    QLabel#historySequenceNumber {{ color: {c['text']}; background: {c['surface2']}; border: 1px solid {c['border']}; border-radius: 7px; padding: 2px 3px; font-size: 12pt; font-weight: 700; }}
    QFrame#polishHistoryRow {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 6px; }}
    QPushButton#polishHistoryCopy {{ background: {c['primary']}; color: {c['primary_text']}; border: 0; border-radius: 8px; padding: 7px 16px; font-weight: 600; }}
    QPushButton#polishHistoryCopy:hover {{ background: {c['primary_hover']}; }}
    QPushButton#polishHistoryCopy[keyboardFocus="true"] {{ border: 2px solid {c['focus']}; }}
    QPushButton#polishHistoryCopy:disabled {{ color: {c['disabled_text']}; background: {c['surface2']}; }}
    QLabel#pageTitle {{ color: {c['text']}; font-size: 16pt; font-weight: 600; }}
    QToolBar#mainToolbar {{ background: {c['sidebar']}; border: 0; border-bottom: 1px solid {c['border']}; spacing: 6px; padding: 3px 10px; margin: 0; min-height: 44px; }}
    QToolBar#mainToolbar QToolButton {{ color: {c['text']}; min-height: 36px; padding: 6px 12px; border: 0; border-radius: 0; }}
    QToolBar#mainToolbar QToolButton:disabled {{ color: {c['disabled_text']}; background: {c['surface2']}; }}
    QToolBar#mainToolbar QToolButton[keyboardFocus="true"] {{ border-bottom: 3px solid {c['focus']}; }}
    QToolBar#mainToolbar QToolButton:hover, QToolButton:hover {{ background: transparent; }}
    QLabel#brandTitle {{ color: {c['text']}; font-size: 12pt; font-weight: 600; padding: 0 8px; }}
    QLabel#toolbarStory {{ color: {c['muted']}; padding-left: 12px; border-left: 1px solid {c['border']}; }}
    QLabel#sectionHeading {{ color: {c['secondary']}; font-size: 11pt; font-weight: 600; padding: 4px 0 7px; }}
    QLabel#mutedLabel, QLabel[class="muted"], QLabel#librarySubtitle, QLabel#emptyStateDescription {{ color: {c['muted']}; }}
    QLabel#metricValue {{ color: {c['text']}; font-size: 21pt; font-weight: 650; }}
    QLabel#metricLabel, QLabel#bodyLabel {{ color: {c['secondary']}; }}
    QLabel#progressStoryTitle {{ color: {c['text']}; font-size: 12pt; font-weight: 600; }}
    QLabel#progressExport {{ color: {c['secondary']}; font-size: 10pt; }}
    QLabel#progressGoalCount {{ color: {c['text']}; font-weight: 600; }}
    QLabel#progressCover {{ background: {c['surface2']}; border-radius: 7px; }}
    QProgressBar#progressGoalBar {{ border: 0; background: {c['surface2']}; min-height: 8px; max-height: 8px; border-radius: 4px; text-align: center; }}
    QProgressBar#progressGoalBar::chunk {{ background: {c['accent']}; border-radius: 4px; }}
    QFrame#progressRow {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 12px; }}
    QPushButton#statisticsDisclosure {{ border: 1px solid {c['border']}; background: {c['surface']}; min-height: 28px; padding: 4px 11px; border-radius: 8px; }}
    QPushButton#statisticsDisclosure:checked {{ background: {c['item_selection']}; }}
    QPushButton#progressAction {{ border: 1px solid {c['border']}; background: {c['surface2']}; min-height: 25px; padding: 3px 8px; border-radius: 7px; font-size: 9pt; }}
    QPushButton#progressAction:hover {{ background: {c['hover']}; }}
    QFrame#storyStrip, QFrame#modeStrip, QFrame#bottomBar, QFrame#goalPanel,
    QFrame#metricCard, QFrame#editorPanel,
    QFrame#settingsCard, QFrame#libraryEmptyState {{ background: transparent; border: 0; border-radius: 0; }}
    QFrame#settingsCard, QFrame#metricCard {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 10px; }}
    QFrame#explorerPanel, QFrame#workflowSidebar, QFrame#editorHeader,
    QFrame#utilityHeader {{ background: {c['sidebar']}; border: 0; }}
    QFrame#editorHeader, QFrame#utilityHeader {{ border-bottom: 1px solid {c['border']}; }}
    QFrame#editorHeader QToolButton {{ color: {c['text']}; background: transparent; border: 0; min-height: 36px; padding: 6px 10px; }}
    QFrame#editorHeader QToolButton:disabled {{ color: {c['disabled_text']}; background: {c['surface2']}; }}
    QFrame#editorHeader QToolButton:hover {{ color: {c['text']}; background: transparent; }}
    QFrame#editorHeader QToolButton[keyboardFocus="true"] {{ border-bottom: 3px solid {c['focus']}; }}
    QFrame#editorHeader QLabel#mutedLabel {{ color: {c['secondary']}; }}
    QToolButton {{ color: {c['text']}; background: transparent; border: 0; border-radius: 0; min-width: 30px; min-height: 30px; padding: 6px 9px; }}
    QToolButton:disabled {{ color: {c['disabled_text']}; background: {c['surface2']}; }}
    QToolButton:pressed {{ background: {c['item_selection']}; }}
    QToolButton[keyboardFocus="true"] {{ border-bottom: 3px solid {c['focus']}; }}
    QListWidget, QTreeWidget, QTreeView, QTableWidget, QTableView {{ background: {c['surface']}; color: {c['text']}; border: 0; outline: none; selection-background-color: {c['selection']}; selection-color: {c['selection_text']}; }}
    QListWidget#novelLibrary {{ background: {c['app']}; border: 0; padding: 9px 1px; }}
    QListWidget#novelLibrary::item {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 12px; padding: 8px 8px; }}
    QListWidget#novelLibrary::item:hover {{ background: {c['hover']}; }}
    QListWidget#novelLibrary::item:selected {{ background: {c['surface']}; border: 2px solid {c['accent']}; color: {c['text']}; }}
    QLabel#emptyStateIcon {{ color: {c['accent']}; font-size: 25pt; }}
    QLineEdit#librarySearch {{ background: {c['input']}; border: 1px solid {c['border']}; border-radius: 10px; padding: 8px 12px; min-height: 32px; }}
    QTabBar#libraryStatusTabs {{ background: transparent; border: 0; }}
    QTabBar#libraryStatusTabs::tab {{ color: {c['secondary']}; background: transparent; border: 0; border-bottom: 2px solid transparent; min-height: 38px; padding: 6px 14px; margin: 0; }}
    QTabBar#libraryStatusTabs::tab:disabled {{ color: {c['disabled_text']}; background: {c['surface2']}; }}
    QTabBar#libraryStatusTabs::tab:hover {{ color: {c['text']}; background: {c['hover']}; }}
    QTabBar#libraryStatusTabs::tab:selected {{ color: {c['text']}; border-bottom: 3px solid {c['accent']}; font-weight: 600; }}
    QTabBar#libraryStatusTabs[keyboardFocus="true"]::tab:selected {{ border-bottom: 3px solid {c['focus']}; }}
    QListWidget#workflowSteps {{ background: transparent; border: 0; outline: 0; }}
    QListWidget#workflowSteps::item, QListWidget#workflowSteps::item:selected {{ background: transparent; color: {c['text']}; border: 0; }}
    QListWidget#workflowSteps::item:hover {{ background: {c['hover']}; }}
    QPushButton#workflowStageButton, QPushButton#vocabularyButton {{ color: {c['text']}; background: transparent; border: 0; border-radius: 0; min-height: 36px; padding: 0 10px; text-align: left; }}
    QPushButton#workflowStageButton:hover, QPushButton#vocabularyButton:hover {{ background: {c['hover']}; }}
    QPushButton#workflowStageButton[workflowActive="true"], QPushButton#vocabularyButton[workflowActive="true"] {{ background: {c['item_selection']}; color: {c['text']}; font-weight: 600; }}
    QPushButton#workflowStageButton[keyboardFocus="true"], QPushButton#vocabularyButton[keyboardFocus="true"] {{ border-bottom: 2px solid {c['focus']}; }}
    QPushButton#copyStepButton {{ color: {c['text']}; background: transparent; border: 0; border-radius: 0; min-height: 34px; padding: 7px 14px; font-weight: 600; }}
    QPushButton#copyStepButton:hover {{ color: {c['muted']}; background: transparent; text-decoration: none; }}
    QPushButton#copyStepButton[keyboardFocus="true"] {{ color: {c['focus']}; background: transparent; border: 0; text-decoration: none; }}
    QPushButton#copyStepButton:disabled {{ color: {c['disabled_text']}; background: transparent; }}
    QLabel#editorStatusBar, QLabel#progressStatusBar, QLabel#goalStatusBar, QLabel#contextStatusBar {{ color: {c['status_text']}; background: transparent; border: 0; padding: 3px 9px; min-height: 24px; font-size: 9pt; }}
    QProgressBar#goalProgressStatusBar {{ background: {c['surface2']}; border: 0; border-radius: 0; min-height: 8px; max-height: 8px; }}
    QProgressBar#goalProgressStatusBar::chunk {{ background: {c['accent']}; border-radius: 0; }}
    QLabel#inspectorScanStatus {{ color: {c['secondary']}; font-size: 10pt; }}
    QProgressBar#inspectorScanProgress {{ background: {c['surface2']}; border: 0; border-radius: 6px; min-height: 12px; max-height: 12px; }}
    QProgressBar#inspectorScanProgress::chunk {{ background: {c['accent']}; border-radius: 6px; }}
    QTreeView#fileTree {{ border: 0; padding: 2px; background: {c['surface']}; }}
    QListWidget[keyboardFocus="true"], QTreeWidget[keyboardFocus="true"], QTreeView[keyboardFocus="true"], QTableWidget[keyboardFocus="true"], QTableView[keyboardFocus="true"] {{ outline: 0; border-bottom: 2px solid {c['focus']}; }}
    QListWidget::item, QTreeWidget::item, QTreeView::item {{ color: {c['text']}; min-height: 28px; padding: 4px 7px; margin: 0; border: 0; }}
    QListWidget::item:hover, QTreeWidget::item:hover, QTreeView::item:hover {{ background: transparent; }}
    QListWidget::item:selected, QTreeWidget::item:selected, QTreeView::item:selected {{ background: {c['item_selection']}; color: {c['selection_text']}; }}
    QListWidget::item:focus, QTreeWidget::item:focus, QTreeView::item:focus, QTableView::item:focus {{ outline: 0; border: 0; }}
    QHeaderView::section {{ color: {c['secondary']}; background: {c['sidebar']}; border: 0; border-bottom: 1px solid {c['border']}; padding: 7px; }}
    QScrollArea#txtVocabularyBatchScroll {{ background: transparent; border: 0; }}
    QFrame#txtVocabularyRow {{ background: transparent; border: 0; border-bottom: 1px solid {c['border']}; border-radius: 0; }}
    QFrame#txtVocabularyRow:hover {{ background: {c['hover']}; }}
    QLabel#txtVocabularyBatchNumber {{ color: {c['secondary']}; font-size: 10pt; font-weight: 600; }}
    QLabel#txtVocabularyBatchRange {{ color: {c['text']}; font-size: 10pt; font-weight: 600; }}
    QLabel#txtVocabularyBatchCount {{ color: {c['muted']}; font-size: 9pt; }}
    QFrame#txtVocabularyRow QPushButton[batchDetails="true"] {{ background: transparent; border: 0; color: {c['secondary']}; padding: 2px 6px; min-height: 28px; }}
    QFrame#txtVocabularyRow QPushButton[batchDetails="true"]:hover {{ color: {c['text']}; background: {c['hover']}; }}
    QPushButton[batchCopyPrimary="true"] {{ background: {c['primary']}; color: {c['primary_text']}; border-color: {c['primary']}; font-weight: 600; }}
    QPushButton[batchCopyPrimary="true"]:hover {{ background: {c['primary_hover']}; }}
    QPushButton {{ min-height: 34px; background: {c['surface2']}; color: {c['text']}; border: 1px solid {c['control_border']}; border-radius: 8px; padding: 6px 12px; }}
    QPushButton:hover {{ background: {c['surface2']}; }}
    QPushButton:pressed {{ background: {c['hover']}; }}
    QPushButton[keyboardFocus="true"] {{ border: 2px solid {c['focus']}; }}
    QPushButton:disabled {{ color: {c['disabled_text']}; background: {c['surface2']}; border-color: {c['border']}; }}
    QPushButton#primaryButton {{ background: {c['primary']}; color: {c['primary_text']}; border: 0; border-radius: 8px; font-weight: 600; padding: 7px 16px; }}
    QPushButton#primaryButton:hover {{ background: {c['primary']}; }}
    QPushButton#primaryButton:pressed {{ background: {c['primary_hover']}; }}
    QPushButton#primaryButton[keyboardFocus="true"] {{ border: 2px solid {c['focus']}; }}
    QPushButton#primaryButton:disabled {{ color: {c['disabled_text']}; background: {c['surface2']}; border: 1px solid {c['border']}; }}
    QPushButton#dangerButton {{ background: transparent; color: {c['danger']}; border: 1px solid {c['border']}; }}
    QLineEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{ background: {c['input']}; color: {c['text']}; border: 1px solid {c['control_border']}; border-radius: 8px; padding: 7px 9px; selection-background-color: {c['selection']}; selection-color: {c['selection_text']}; min-height: 28px; }}
    QLineEdit:disabled, QTextEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{ color: {c['disabled_text']}; background: {c['surface2']}; }}
    QPlainTextEdit {{ background: {c['surface']}; color: {c['text']}; border: 0; selection-background-color: {c['selection']}; selection-color: {c['selection_text']}; }}
    QLineEdit:hover, QTextEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {{ border-color: {c['muted']}; }}
    QLineEdit[keyboardFocus="true"], QTextEdit[keyboardFocus="true"], QSpinBox[keyboardFocus="true"], QDoubleSpinBox[keyboardFocus="true"], QComboBox[keyboardFocus="true"] {{ border: 2px solid {c['focus']}; }}
    QLineEdit::placeholder {{ color: {c['muted']}; }}
    QSpinBox, QDoubleSpinBox {{ padding-right: 34px; min-height: 30px; }}
    QSpinBox::up-button, QDoubleSpinBox::up-button {{ subcontrol-origin: border; subcontrol-position: top right; width: 28px; height: 22px; margin: 1px; border: 0; background: transparent; }}
    QSpinBox::down-button, QDoubleSpinBox::down-button {{ subcontrol-origin: border; subcontrol-position: bottom right; width: 28px; height: 22px; margin: 1px; border: 0; background: transparent; }}
    QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background: {c['item_selection']}; }}
    QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url("{up_arrow}"); width: 12px; height: 10px; }}
    QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url("{down_arrow}"); width: 12px; height: 10px; }}
    QSpinBox::up-button, QDoubleSpinBox::up-button {{ border-top-right-radius: 7px; }}
    QSpinBox::down-button, QDoubleSpinBox::down-button {{ border-bottom-right-radius: 7px; }}
    QSpinBox::up-button:pressed, QSpinBox::down-button:pressed,
    QDoubleSpinBox::up-button:pressed, QDoubleSpinBox::down-button:pressed {{ background: {c['selection']}; }}
    QListWidget#preferencesCategory {{ background: transparent; border: 0; }}
    QListWidget#preferencesCategory::item {{ border-radius: 8px; padding: 8px 12px; min-height: 24px; margin: 2px 0; }}
    QListWidget#preferencesCategory::item:selected {{ background: {c['item_selection']}; color: {c['selection_text']}; font-weight: 600; }}
    QToolButton#navigationItem {{ border-radius: 10px; }}
    QComboBox::drop-down {{ border: 0; width: 26px; }}
    QComboBox::down-arrow {{ image: url("{down_arrow}"); width: 12px; height: 10px; }}
    QComboBox QAbstractItemView {{ background: {c['surface']}; color: {c['text']}; border: 1px solid {c['border']}; selection-background-color: {c['selection']}; selection-color: {c['selection_text']}; outline: none; }}
    QCheckBox, QRadioButton {{ color: {c['text']}; spacing: 8px; min-height: 28px; }}
    QCheckBox:disabled, QRadioButton:disabled {{ color: {c['disabled_text']}; }}
    QCheckBox::indicator, QRadioButton::indicator {{ width: 17px; height: 17px; border: 1px solid {c['muted']}; border-radius: 4px; background: {c['input']}; }}
    QCheckBox::indicator:checked, QRadioButton::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; }}
    QCheckBox::indicator:checked {{ image: url("{check_mark}"); }}
    QCheckBox[keyboardFocus="true"]::indicator, QRadioButton[keyboardFocus="true"]::indicator {{ border: 2px solid {c['focus']}; }}
    QRadioButton::indicator, QRadioButton::indicator:checked {{ border-radius: 9px; }}
    QTabWidget::pane {{ background: {c['surface']}; border: 0; border-top: 1px solid {c['border']}; }}
    QTabBar::tab {{ color: {c['secondary']}; background: {c['surface2']}; padding: 8px 14px; margin: 0; border: 0; border-right: 1px solid {c['border']}; min-height: 32px; }}
    QTabBar::tab:disabled {{ color: {c['disabled_text']}; background: {c['surface2']}; }}
    QTabBar::tab:hover {{ color: {c['text']}; background: {c['hover']}; }}
    QTabBar::tab:selected {{ color: {c['text']}; background: {c['surface']}; border-top: 2px solid {c['accent']}; }}
    QTabBar[keyboardFocus="true"]::tab:selected {{ border-bottom: 3px solid {c['focus']}; }}
    QGroupBox {{ background: transparent; border: 0; border-top: 1px solid {c['border']}; margin-top: 14px; padding-top: 9px; font-weight: 600; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 0; padding: 0 6px 0 0; color: {c['secondary']}; }}
    QProgressBar {{ background: {c['surface2']}; color: {c['text']}; border: 0; border-radius: 0; text-align: center; min-height: 20px; }}
    QProgressBar::chunk {{ background: {c['accent']}; border-radius: 0; }}
    QProgressDialog QLabel, QMessageBox QLabel {{ color: {c['text']}; font-size: 11pt; }}
    QProgressDialog QPushButton {{ min-width: 92px; min-height: 36px; }}
    QProgressDialog QProgressBar {{ min-height: 24px; font-size: 10pt; font-weight: 600; }}
    QStatusBar {{ background: {c['status']}; color: {c['status_text']}; border: 0; min-height: 30px; padding: 0; }}
    QStatusBar::item {{ border: 0; }}
    QMenu {{ background: {c['sidebar']}; color: {c['text']}; border: 1px solid {c['border']}; padding: 4px; }}
    QMenuBar {{ background: {c['app']}; color: {c['text']}; border: 0; }}
    QMenuBar::item {{ background: transparent; color: {c['text']}; padding: 5px 10px; }}
    QMenuBar::item:selected {{ background: {c['item_selection']}; }}
    QMenu::item {{ padding: 8px 26px 8px 12px; min-height: 28px; }}
    QMenu::item:selected {{ background: {c['item_selection']}; color: {c['selection_text']}; }}
    QMenu::item:disabled {{ color: {c['disabled_text']}; }}
    QMenu::separator {{ height: 1px; background: {c['border']}; margin: 5px 7px; }}
    QToolTip {{ color: {c['text']}; background: {c['surface']}; border: 1px solid {c['border']}; padding: 5px 7px; }}
    QDialogButtonBox QPushButton {{ min-width: 84px; }}
    QSplitter::handle {{ background: {c['border']}; width: 1px; height: 1px; }}
    QScrollArea, QAbstractScrollArea {{ background: transparent; border: 0; }}
    QScrollBar:vertical {{ background: {c['scroll_track']}; border: 0; margin: 0; width: 16px; }}
    QScrollBar:horizontal {{ background: {c['scroll_track']}; border: 0; margin: 0; height: 16px; }}
    QScrollBar::handle:vertical {{ background: {c['scroll_thumb']}; border: 3px solid {c['scroll_track']}; border-radius: 7px; min-height: 36px; }}
    QScrollBar::handle:horizontal {{ background: {c['scroll_thumb']}; border: 3px solid {c['scroll_track']}; border-radius: 7px; min-width: 36px; }}
    QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover,
    QScrollBar::handle:vertical:pressed, QScrollBar::handle:horizontal:pressed {{ background: {c['scroll_thumb_hover']}; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical,
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: {c['scroll_track']}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; background: transparent; border: 0; }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; background: transparent; border: 0; }}
    """
