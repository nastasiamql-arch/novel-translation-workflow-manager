"""Desktop dragging shared by novel covers and settings rows."""
from PySide6.QtCore import Qt, Signal, QPoint, QTimer
from PySide6.QtGui import QDrag, QPainter, QPen
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
        self.setDropIndicatorShown(False)
        self.setAutoScroll(False)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setToolTip("กดแล้วลากนิยายเพื่อจัดลำดับ")
        self._press_position = None
        self._dragging = False
        self._drag_profile_id = None
        self._drag_point = None
        self._marker = None
        self._edge_scroll = QTimer(self)
        self._edge_scroll.setInterval(16)
        self._edge_scroll.timeout.connect(self._scroll_drag_edge)
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
                    self._clear_drag_target()
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

    def _drop_row(self, point):
        visible=[i for i in range(self.count()) if not self.item(i).isHidden()]
        if not visible:return self.count()
        target=self.indexAt(point).row()
        if target < 0:
            last=visible[-1]
            if point.y() > self.visualItemRect(self.item(last)).bottom():return last+1
            target=min(visible,key=lambda i:(self.visualItemRect(self.item(i)).center()-point).manhattanLength())
        rect=self.visualItemRect(self.item(target))
        after=point.x() >= rect.center().x() if self.viewMode() == QListWidget.IconMode else point.y() >= rect.center().y()
        return target+int(after)

    def _show_drag_target(self, point):
        self._drag_point=point
        slot=self._drop_row(point)
        visible=[i for i in range(self.count()) if not self.item(i).isHidden()]
        if not visible:return
        next_row=next((i for i in visible if i >= slot),None)
        rect=self.visualItemRect(self.item(next_row if next_row is not None else visible[-1]))
        if self.viewMode() == QListWidget.IconMode:
            x=rect.left() if next_row is not None else rect.right()
            self._marker=(QPoint(x,rect.top()+4),QPoint(x,rect.bottom()-4))
        else:
            y=rect.top() if next_row is not None else rect.bottom()
            self._marker=(QPoint(rect.left(),y),QPoint(rect.right(),y))
        self.viewport().update()

    def dragMoveEvent(self, event):
        if self._drag_profile_id is None:event.ignore();return
        self._show_drag_target(event.position().toPoint())
        event.setDropAction(Qt.MoveAction);event.accept()
        if not self._edge_scroll.isActive():self._edge_scroll.start()

    def _scroll_drag_edge(self):
        if self._drag_point is None:return
        y=self._drag_point.y();height=self.viewport().height();margin=40
        delta=-(margin-y) if y < margin else y-(height-margin) if y > height-margin else 0
        if delta:
            bar=self.verticalScrollBar()
            bar.setValue(bar.value()+max(-12,min(12,round(delta/4))))
            self._show_drag_target(self._drag_point)

    def _clear_drag_target(self):
        self._edge_scroll.stop();self._marker=None;self._drag_point=None
        self.viewport().update()

    def dragLeaveEvent(self, event):
        self._clear_drag_target();super().dragLeaveEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._marker:
            painter=QPainter(self.viewport())
            # Neutral drop markers match the current surface's text contrast.
            color=self.palette().color(self.foregroundRole())
            painter.setPen(QPen(color,2));painter.drawLine(*self._marker);painter.end()

    def dropEvent(self, event):
        # Explicit model order also works in IconMode; native QListWidget moves
        # can otherwise move grid positions without changing the stored order.
        source = next((i for i in range(self.count())
                       if self.item(i).data(Qt.UserRole) == self._drag_profile_id), -1)
        if self._drag_profile_id is None or source < 0:
            event.ignore()
            return
        target = self._drop_row(event.position().toPoint())
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
        self._clear_drag_target()
