"""Bounded, scrollable modal confirmation for unbounded preview text."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QLabel, QPlainTextEdit,
    QPushButton, QSizePolicy, QVBoxLayout,
)


def fit_dialog(dialog, width=800, height=560):
    parent = dialog.parentWidget()
    screen = None
    if parent is not None:
        window = parent.window()
        handle = window.windowHandle()
        screen = handle.screen() if handle else None
        if screen is None:
            screen = QApplication.screenAt(window.mapToGlobal(window.rect().center()))
    screen = screen or QApplication.primaryScreen()
    available = screen.availableGeometry()
    max_width = max(1, int(available.width() * 0.90))
    max_height = max(1, int(available.height() * 0.84))
    dialog.setMaximumSize(max_width, max_height)
    dialog.resize(min(width, max_width), min(height, max_height))
    center = parent.mapToGlobal(parent.rect().center()) if parent else available.center()
    dialog.move(
        max(available.left(), min(center.x() - dialog.width() // 2, available.right() - dialog.width() + 1)),
        max(available.top(), min(center.y() - dialog.height() // 2, available.bottom() - dialog.height() + 1)),
    )


class ScrollableConfirmation(QDialog):
    """Only a real click on the affirmative action can confirm changes."""

    def __init__(self, parent, title, summary, details):
        super().__init__(parent)
        self.setObjectName("scrollableConfirmation")
        self.setWindowTitle(title)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        layout = QVBoxLayout(self)
        self.summary = QLabel(summary)
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.details = QPlainTextEdit()
        self.details.setObjectName("scrollableConfirmationDetails")
        self.details.setReadOnly(True)
        self.details.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.details.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.details.setPlainText(details)
        layout.addWidget(self.details, 1)
        self.actions = QDialogButtonBox()
        self.actions.setObjectName("scrollableConfirmationActions")
        self.confirm = self.actions.addButton("ยืนยัน", QDialogButtonBox.AcceptRole)
        self.cancel = self.actions.addButton("ยกเลิก", QDialogButtonBox.RejectRole)
        self.confirm.setAutoDefault(False)
        self.cancel.setDefault(True)
        self.cancel.setFocus(Qt.TabFocusReason)
        self.actions.accepted.connect(self.accept)
        self.actions.rejected.connect(self.reject)
        layout.addWidget(self.actions)
        fit_dialog(self)

    def showEvent(self, event):
        super().showEvent(event)
        fit_dialog(self)


def confirm_scrollable(parent, title, summary, details):
    return ScrollableConfirmation(parent, title, summary, details).exec() == QDialog.Accepted
