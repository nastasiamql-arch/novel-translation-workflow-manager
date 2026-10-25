"""Reusable Thai Buddhist-era date display; ISO/Gregorian QDate remains canonical."""
from __future__ import annotations

from PySide6.QtCore import QDate, QPoint, Qt, QEvent, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLineEdit, QToolButton, QDialog,
    QVBoxLayout, QCalendarWidget, QSizePolicy,
)
from PySide6.QtCore import QLocale


THAI_MONTHS = (
    "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
    "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม",
)


def buddhist_date_text(day: QDate) -> str:
    """Format for humans only; never persist the Buddhist-era year."""
    if not day.isValid():
        return ""
    return f"{day.day()} {THAI_MONTHS[day.month() - 1]} {day.year() + 543}"


class ThaiDatePicker(QWidget):
    """Keyboard-accessible calendar control with Gregorian QDate API."""

    dateChanged = Signal(QDate)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._date = QDate.currentDate()
        self._popup = None
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self.display = QLineEdit(self)
        self.display.setObjectName("thaiDateDisplay")
        self.display.setReadOnly(True)
        self.display.setFocusPolicy(Qt.NoFocus)
        self.display.installEventFilter(self)
        self.display.setAccessibleName("วันที่ที่เลือก")
        self.button = QToolButton(self)
        self.button.setObjectName("thaiDateButton")
        self.button.setText("📅")
        self.button.setToolTip("เปิดปฏิทินเลือกวันที่")
        self.button.setAccessibleName("เปิดปฏิทินเลือกวันที่")
        self.button.setFocusPolicy(Qt.StrongFocus)
        self.button.clicked.connect(self.open_calendar)
        row.addWidget(self.display)
        row.addWidget(self.button)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setFocusProxy(self.button)
        self._resize_to_font()
        self._refresh_text()

    def _resize_to_font(self):
        metrics = self.display.fontMetrics()
        widest = max(metrics.horizontalAdvance(f"28 {month} 2569")
                     for month in THAI_MONTHS)
        control_height = max(40, metrics.height() + 18)
        # Keep enough room for the longest month even when the platform font
        # metrics settle after the picker has been constructed.
        self.display.setFixedWidth(max(widest + 30, 260))
        self.display.setMinimumHeight(control_height)
        self.button.setFixedSize(control_height, control_height)
        self.updateGeometry()

    def event(self, event):
        if event.type() in (QEvent.FontChange, QEvent.StyleChange):
            if hasattr(self, "display"):
                self._resize_to_font()
        return super().event(event)

    def eventFilter(self, watched, event):
        if watched is self.display and event.type() == QEvent.MouseButtonRelease:
            if event.button() == Qt.LeftButton and self.isEnabled():
                self.open_calendar()
                return True
        return super().eventFilter(watched, event)

    def _refresh_text(self):
        self.display.setText(buddhist_date_text(self._date))
        self.setAccessibleDescription(f"วันที่ {self.display.text()}")

    def date(self) -> QDate:
        return QDate(self._date)

    def setDate(self, day: QDate):
        if not day.isValid():
            return
        if day != self._date:
            self._date = QDate(day)
            self._refresh_text()
            self.dateChanged.emit(self.date())
        else:
            self._refresh_text()

    def open_calendar(self):
        if not self.isEnabled():
            return
        if self._popup is not None:
            self._popup.raise_()
            return
        popup = QDialog(self, Qt.Popup)
        popup.setObjectName("thaiDatePopup")
        popup.setWindowTitle("เลือกวันที่")
        column = QVBoxLayout(popup)
        calendar = QCalendarWidget(popup)
        calendar.setLocale(QLocale(QLocale.Thai, QLocale.Thailand))
        calendar.setGridVisible(True)
        calendar.setSelectedDate(self._date)
        column.addWidget(calendar)
        calendar.clicked.connect(lambda day: (self.setDate(day), popup.close()))
        popup.finished.connect(lambda _result: setattr(self, "_popup", None))
        self._popup = popup
        popup.adjustSize()
        screen = QGuiApplication.screenAt(self.mapToGlobal(QPoint(0, 0))) or self.screen()
        available = screen.availableGeometry()
        origin = self.mapToGlobal(QPoint(0, self.height()))
        x = min(max(origin.x(), available.left()), max(available.left(), available.right() - popup.width() + 1))
        y = origin.y()
        if y + popup.height() > available.bottom() + 1:
            y = self.mapToGlobal(QPoint(0, 0)).y() - popup.height()
        y = min(max(y, available.top()), max(available.top(), available.bottom() - popup.height() + 1))
        popup.move(x, y)
        popup.show()
        calendar.setFocus(Qt.PopupFocusReason)
