"""Desktop dragging shared by novel covers and settings rows."""
from PySide6.QtCore import Qt, Signal, QPoint, QTimer, QRect, QSize
from PySide6.QtGui import QDrag, QPainter, QPen, QPalette, QIcon, QFontMetrics, QTextLayout, QTextOption
from PySide6.QtWidgets import QListWidget, QApplication, QAbstractItemView, QStyledItemDelegate, QStyle, QStyleOptionViewItem


class ProfileItemDelegate(QStyledItemDelegate):
    """Use exclusive cover/title/status rectangles for icon-mode library cards."""

    MAX_TITLE_LINES = 3

    def _library(self):
        return self.parent() is not None and self.parent().objectName() == "novelLibrary"

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.state &= ~QStyle.State_HasFocus

    def card_size(self):
        view = self.parent()
        if view is None:
            return QSize(210, 310)
        height = (12 + view.iconSize().height() + 10
                  + self.MAX_TITLE_LINES * (view.fontMetrics().lineSpacing() + 5)
                  + 8 + view.fontMetrics().height() + 7 + 15)
        return QSize(max(210, view.iconSize().width() + 24), height)

    def sizeHint(self, option, index):
        if self._library():
            return self.card_size()
        return super().sizeHint(option, index)

    def card_rects(self, item_rect, metrics=None):
        view = self.parent()
        metrics = metrics or view.fontMetrics()
        icon = view.iconSize()
        cover = QRect(item_rect.center().x() - icon.width() // 2,
                      item_rect.top() + 12, icon.width(), icon.height())
        status_height = metrics.height() + 7
        status = QRect(item_rect.left() + 12, item_rect.bottom() - 12 - status_height,
                       item_rect.width() - 24, status_height)
        title_top = cover.bottom() + 11
        title = QRect(item_rect.left() + 12, title_top,
                      item_rect.width() - 24, max(0, status.top() - 8 - title_top))
        return {"cover": cover, "title": title, "status": status}

    @staticmethod
    def title_lines(text, font, width):
        """Qt text shaping/wrap decides breaks for Thai, CJK and emoji."""
        text = str(text).replace("\r", " ").replace("\n", " ")
        layout = QTextLayout(text, font)
        options = QTextOption()
        options.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        layout.setTextOption(options)
        lines = []
        layout.beginLayout()
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(max(1, width))
            lines.append(text[line.textStart():line.textStart() + line.textLength()])
        layout.endLayout()
        return lines or [""]

    def paint(self, painter, option, index):
        if not self._library():
            super().paint(painter, option, index)
            return
        # Draw the styled item surface ONLY. Standard text/icon painting would
        # place Qt's wrapped title in the same space as our status footer.
        surface = QStyleOptionViewItem(option)
        self.initStyleOption(surface, index)
        surface.text = ""
        surface.icon = QIcon()
        surface.widget = self.parent()
        if surface.widget is not None:
            surface.widget.style().drawPrimitive(QStyle.PE_PanelItemViewItem, surface, painter, surface.widget)
        painter.save()
        try:
            painter.setClipRect(option.rect)
            metrics = QFontMetrics(option.font)
            regions = self.card_rects(option.rect, metrics)
            icon = index.data(Qt.DecorationRole)
            if isinstance(icon, QIcon) and not icon.isNull():
                pixmap = icon.pixmap(regions["cover"].size())
                painter.drawPixmap(regions["cover"].topLeft(), pixmap)
            painter.setFont(option.font)
            painter.setPen(option.palette.color(QPalette.Text))
            lines = self.title_lines(index.data(Qt.DisplayRole) or "", option.font,
                                     regions["title"].width())
            line_step = metrics.lineSpacing() + 5
            title = regions["title"]
            painter.save()
            painter.setClipRect(title)
            for number, line in enumerate(lines[:self.MAX_TITLE_LINES]):
                if number == self.MAX_TITLE_LINES - 1 and len(lines) > self.MAX_TITLE_LINES:
                    line = metrics.elidedText("".join(lines[number:]), Qt.ElideRight, title.width())
                bounds = QRect(title.left(), title.top() + number * line_step,
                               title.width(), line_step)
                painter.drawText(bounds, Qt.AlignLeft | Qt.AlignVCenter | Qt.TextSingleLine, line)
            painter.restore()
            footer = index.data(Qt.UserRole + 2)
            if footer:
                small = option.font
                if small.pointSizeF() > 0:
                    small.setPointSizeF(max(8, small.pointSizeF() - 1))
                painter.setFont(small)
                footer_text = QFontMetrics(small).elidedText(
                    str(footer), Qt.ElideRight, regions["status"].width())
                painter.drawText(regions["status"], Qt.AlignLeft | Qt.AlignVCenter |
                                 Qt.TextSingleLine, footer_text)
        finally:
            painter.restore()


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
