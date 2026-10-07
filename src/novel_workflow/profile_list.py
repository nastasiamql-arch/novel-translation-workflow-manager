"""Desktop dragging shared by novel covers and settings rows."""
from PySide6.QtCore import Qt, Signal, QPoint
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import QListWidget, QApplication, QAbstractItemView, QStyledItemDelegate, QStyle


class ProfileItemDelegate(QStyledItemDelegate):
    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        if option.state & QStyle.State_Selected:
            option.font.setBold(True)
        option.state &= ~QStyle.State_HasFocus


class ReorderableProfileList(QListWidget):
    """Profile list with native click-and-drag reordering."""

    orderChanged = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setToolTip("กดแล้วลากนิยายเพื่อจัดลำดับ")
        self._press_position = None
        self._dragging = False
        self._drag_profile_id = None
        self.setItemDelegate(ProfileItemDelegate(self))

    selectionCommitted = Signal(int)

    def mousePressEvent(self, event):
        point = event.position().toPoint()
        self._press_position = point if event.button() == Qt.LeftButton and self.indexAt(point).isValid() else None
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._press_position is not None and event.buttons() & Qt.LeftButton:
            if (event.position().toPoint() - self._press_position).manhattanLength() >= QApplication.startDragDistance():
                self._dragging = True
                try:
                    self.setState(QAbstractItemView.DraggingState)
                    self.startDrag(Qt.MoveAction)
                finally:
                    self._press_position = None
                    self._dragging = False
                    self._drag_profile_id = None
                    self.setState(QAbstractItemView.NoState)
                return
        super().mouseMoveEvent(event)

    def startDrag(self, supported_actions):
        item = self.currentItem()
        if item is None:
            return
        self._drag_profile_id = item.data(Qt.UserRole)
        drag = QDrag(self)
        drag.setMimeData(self.mimeData([item]))
        rect = self.visualItemRect(item).intersected(self.viewport().rect())
        preview = item.icon().pixmap(self.iconSize()) if not item.icon().isNull() else self.viewport().grab(rect)
        drag.setPixmap(preview)
        if self._press_position is not None:
            offset = self._press_position - rect.topLeft()
            drag.setHotSpot(QPoint(max(0, min(offset.x(), preview.width()-1)),
                                  max(0, min(offset.y(), preview.height()-1))))
        drag.exec(Qt.MoveAction)

    def mouseReleaseEvent(self, event):
        clicked = self._press_position is not None and not self._dragging
        self._press_position = None
        super().mouseReleaseEvent(event)
        if clicked and event.button() == Qt.LeftButton:
            self.selectionCommitted.emit(self.currentRow())

    def keyPressEvent(self, event):
        previous = self.currentRow()
        super().keyPressEvent(event)
        if self.currentRow() != previous or event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.selectionCommitted.emit(self.currentRow())

    def dropEvent(self, event):
        # Explicit model order also works in IconMode; native QListWidget moves
        # can otherwise move grid positions without changing the stored order.
        source = next((i for i in range(self.count())
                       if self.item(i).data(Qt.UserRole) == self._drag_profile_id), -1)
        if self._drag_profile_id is None or source < 0:
            event.ignore()
            return
        point = event.position().toPoint()
        target = self.indexAt(point).row()
        if target < 0:
            visible = [i for i in range(self.count()) if not self.item(i).isHidden()]
            target = visible[-1] + 1 if visible else self.count()
        else:
            rect = self.visualItemRect(self.item(target))
            after = point.x() >= rect.center().x() if self.viewMode() == QListWidget.IconMode else point.y() >= rect.center().y()
            target += int(after)
        target -= int(source < target)
        target = max(0, min(target, self.count()-1))
        if source != target:
            previous = self.blockSignals(True)
            try:
                item = self.takeItem(source)
                self.insertItem(target, item)
                self.setCurrentItem(item)
                self.doItemsLayout()
            finally:
                self.blockSignals(previous)
            self.orderChanged.emit([self.item(i).data(Qt.UserRole) for i in range(self.count())])
        event.setDropAction(Qt.MoveAction)
        event.accept()
        self.viewport().update()
