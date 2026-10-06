"""Quiet pointer interaction with explicit keyboard-only focus indicators."""
from PySide6.QtCore import QObject, QEvent, Qt
from PySide6.QtWidgets import QApplication, QWidget, QProxyStyle, QStyle


class QuietFocusStyle(QProxyStyle):
    def drawPrimitive(self, element, option, painter, widget=None):
        # Native item focus rectangles surround text even after a mouse click.
        # Keyboard focus is rendered consistently through our stylesheet instead.
        if element != QStyle.PE_FrameFocusRect:
            super().drawPrimitive(element, option, painter, widget)


class FocusInputFilter(QObject):
    def mark(self, widget, visible):
        if isinstance(widget, QWidget) and widget.property('keyboardFocus') != visible:
            widget.setProperty('keyboardFocus', visible)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind == QEvent.MouseButtonPress:
            self.mark(QApplication.focusWidget(), False)
            self.mark(watched, False)
        elif kind == QEvent.KeyPress:
            self.mark(QApplication.focusWidget(), True)
        elif kind == QEvent.FocusIn:
            self.mark(watched, event.reason() in (
                Qt.TabFocusReason, Qt.BacktabFocusReason, Qt.ShortcutFocusReason))
        elif kind == QEvent.FocusOut:
            self.mark(watched, False)
        return False


def install_focus_behavior(app):
    if not hasattr(app, '_palantir_focus_filter'):
        app.setStyle(QuietFocusStyle())
        app._palantir_focus_filter = FocusInputFilter(app)
        app.installEventFilter(app._palantir_focus_filter)
