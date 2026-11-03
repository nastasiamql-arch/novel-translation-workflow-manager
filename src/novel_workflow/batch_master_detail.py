"""Small presentation helpers shared by the two batch pages."""
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QSizePolicy, QVBoxLayout, QWidget


def batch_key(profile_id, identity, revision, group):
    return {"profile": profile_id, "source": identity, "revision": revision,
            "index": group.index, "start": group.start, "end": group.end,
            "chapters": [chapter.number for chapter in group.chapters]}


def cancel_scroll_restore(scroll):
    bar = scroll.verticalScrollBar()
    bar.setProperty("batchRestoreGeneration", (bar.property("batchRestoreGeneration") or 0) + 1)


def restore_scroll_when_ready(scroll, value):
    """Wait for Qt to publish the new range after lazy rows are laid out."""
    bar = scroll.verticalScrollBar()
    cancel_scroll_restore(scroll)
    generation = bar.property("batchRestoreGeneration")
    initial = bar.value()
    active = True
    def finish(_minimum=None, maximum=None):
        nonlocal active
        maximum = bar.maximum() if maximum is None else maximum
        if not active or maximum < value:
            return
        active = False
        try:
            bar.rangeChanged.disconnect(finish)
        except (RuntimeError, TypeError):
            return
        if bar.property("batchRestoreGeneration") == generation and bar.value() == initial:
            bar.setValue(value)
    if bar.maximum() >= value:
        bar.setValue(value)
        return
    bar.rangeChanged.connect(finish)
    def fallback():
        nonlocal active
        if not active:
            return
        active = False
        try:
            bar.rangeChanged.disconnect(finish)
        except (RuntimeError, TypeError):
            return
        if bar.property("batchRestoreGeneration") == generation and bar.value() == initial:
            bar.setValue(value)
    QTimer.singleShot(250, fallback)


class BatchRow(QFrame):
    selected = Signal()
    move = Signal(int)

    def __init__(self):
        super().__init__()
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.setFocus(Qt.MouseFocusReason)
            self.selected.emit()
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Up, Qt.Key_Down):
            self.move.emit(-1 if event.key() == Qt.Key_Up else 1)
            event.accept()
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.selected.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class BatchWorkspace(QWidget):
    """Keep list and detail independently bounded, using the available page width."""
    def __init__(self, list_widget, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        self.list_widget = list_widget
        self.list_widget.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        self._show_detail = False
        self._narrow = False
        self.layout_ = QHBoxLayout(self)
        self.layout_.setContentsMargins(0, 0, 0, 0)
        self.layout_.addWidget(list_widget, 2)
        self.detail = QWidget()
        self.detail.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        detail_layout = QVBoxLayout(self.detail)
        detail_layout.setContentsMargins(6, 0, 0, 0)
        self.back = QPushButton("← กลับรายการชุด")
        self.back.clicked.connect(self.show_list)
        detail_layout.addWidget(self.back)
        self.title = QLabel("เลือกรายการชุดเพื่อดูรายละเอียด")
        self.title.setWordWrap(True)
        self.title.setAccessibleName("รายละเอียดชุดงานที่เลือก")
        detail_layout.addWidget(self.title)
        self.text = QPlainTextEdit()
        self.text.setObjectName("batchDetailText")
        self.text.setReadOnly(True)
        self.text.setAccessibleName("รายชื่อไฟล์และคำเตือนของชุดงาน")
        detail_layout.addWidget(self.text, 1)
        self.copy = QPushButton("คัดลอกชุดที่เลือก")
        self.copy.setEnabled(False)
        detail_layout.addWidget(self.copy)
        self.layout_.addWidget(self.detail, 3)
        self._update_layout()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.reflow()

    def reflow(self):
        # Leave enough room for the widest compact row and a larger detail pane.
        # The row's size hint includes its translated labels and action button.
        row = self.list_widget.findChild(BatchRow)
        row_width = row.minimumSizeHint().width() if row is not None else 0
        threshold = max(720, int((row_width + 24) * 2.5),
                        self.fontMetrics().horizontalAdvance("รายละเอียดชุดงานที่เลือก  รายการชุดงาน  คัดลอกอีกครั้ง") * 2)
        narrow = self.width() < threshold
        if narrow != self._narrow:
            self._narrow = narrow
            self._update_layout()

    def _update_layout(self):
        self.back.setVisible(self._narrow)
        self.list_widget.setVisible(not self._narrow or not self._show_detail)
        self.detail.setVisible(not self._narrow or self._show_detail)

    def show_selection(self, title, text, *, switch=True):
        self.title.setText(title)
        self.text.setPlainText(text)
        self.copy.setEnabled(True)
        if switch:
            self._show_detail = True
        self._update_layout()

    def clear_selection(self, message="เลือกรายการชุดเพื่อดูรายละเอียด"):
        self.title.setText(message)
        self.text.clear()
        self.copy.setEnabled(False)
        self._show_detail = False
        self._update_layout()

    def show_list(self):
        self._show_detail = False
        self._update_layout()
