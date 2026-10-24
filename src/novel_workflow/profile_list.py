"""Desktop dragging shared by novel covers and settings rows."""
from PySide6.QtCore import Qt, Signal, QPoint, QTimer, QRect, QSize, QEvent
from PySide6.QtGui import QDrag, QPainter, QPen, QPalette, QIcon, QColor, QFontMetrics, QTextLayout, QTextOption
from PySide6.QtWidgets import QListWidget, QApplication, QAbstractItemView, QStyledItemDelegate, QStyle, QStyleOptionViewItem


class ProfileItemDelegate(QStyledItemDelegate):
    """Paint one gallery/list item; every field owns a non-overlapping region."""

    MAX_TITLE_LINES = 2
    CARD_WIDTH = 250
    CELL_GAP = 16
    COVER_SIZE = QSize(222, 296)
    LIST_HEIGHT = 112

    def _library(self):
        return self.parent() is not None and self.parent().objectName() == "novelLibrary"

    def _list_mode(self):
        return self._library() and self.parent().viewMode() == QListWidget.ListMode

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        # A painted focus outline is drawn by the library item background.
        # Other legacy profile lists keep their existing focus behaviour.
        option.state &= ~QStyle.State_HasFocus

    def card_size(self):
        view = self.parent()
        if self._list_mode():
            return QSize(self.CARD_WIDTH, self.LIST_HEIGHT)
        if view is None:
            return QSize(self.CARD_WIDTH, 460)
        metrics = view.fontMetrics()
        cover = view.iconSize()
        # Maximum two title lines; one-line titles place metadata immediately
        # after the painted line (without a reserved empty title slot).
        line = metrics.lineSpacing() + 4
        height = (14 + cover.height() + 10 + self.MAX_TITLE_LINES * line
                  + 8 + line + 7 + line + 7 + 4 + 14)
        return QSize(max(self.CARD_WIDTH, cover.width() + 28), height)

    def sizeHint(self, option, index):
        if self._library():
            if self._list_mode():
                return QSize(max(self.CARD_WIDTH, option.rect.width()), self.LIST_HEIGHT)
            size = self.card_size()
            return QSize(size.width() + self.CELL_GAP,
                         size.height() + self.CELL_GAP)
        return super().sizeHint(option, index)

    def _card_bounds(self, item_rect):
        if self._list_mode():
            return QRect(item_rect)
        size = self.card_size()
        inset = self.CELL_GAP // 2
        return QRect(item_rect.left() + inset, item_rect.top() + inset,
                     size.width(), size.height())

    def card_rects(self, item_rect, metrics=None, title_text=None):
        view = self.parent()
        metrics = metrics or view.fontMetrics()
        if self._list_mode():
            cover = QRect(item_rect.left() + 13, item_rect.top() + 12, 65, 88)
            x = cover.right() + 17
            width = max(0, item_rect.right() - 16 - x)
            title = QRect(x, item_rect.top() + 13, width, metrics.lineSpacing() + 9)
            status = QRect(x, title.bottom() + 6, width, metrics.lineSpacing() + 4)
            progress = QRect(x, status.bottom() + 5, width, metrics.lineSpacing() + 4)
            return {"card": QRect(item_rect), "cover": cover, "title": title,
                    "status": status, "progress": progress, "bar": QRect()}
        card = self._card_bounds(item_rect)
        icon = view.iconSize()
        cover = QRect(card.center().x() - icon.width() // 2,
                      card.top() + 14, icon.width(), icon.height())
        title_top = cover.bottom() + 11
        title_width = card.width() - 28
        line_step = metrics.lineSpacing() + 4
        lines = self.title_lines(title_text or "", view.font(), title_width)
        title_height = min(self.MAX_TITLE_LINES, len(lines)) * line_step
        title = QRect(card.left() + 14, title_top, title_width, title_height)
        status = QRect(title.left(), title.bottom() + 8,
                       title.width(), line_step)
        progress = QRect(title.left(), status.bottom() + 7,
                         title.width(), line_step)
        bar = QRect(title.left(), progress.bottom() + 7, title.width(), 4)
        return {"card": card, "cover": cover, "title": title, "status": status,
                "progress": progress, "bar": bar}

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
        surface = QStyleOptionViewItem(option)
        self.initStyleOption(surface, index)
        surface.text = ""
        surface.icon = QIcon()
        surface.widget = self.parent()
        if not self._list_mode():
            surface.rect = self._card_bounds(option.rect)
        if surface.widget is not None:
            surface.widget.style().drawPrimitive(
                QStyle.PE_PanelItemViewItem, surface, painter, surface.widget)
        painter.save()
        try:
            painter.setClipRect(surface.rect)
            metrics = QFontMetrics(option.font)
            regions = self.card_rects(
                option.rect, metrics, index.data(Qt.DisplayRole) or "")
            icon = index.data(Qt.DecorationRole)
            if isinstance(icon, QIcon) and not icon.isNull():
                # QIcon retains scaled pixmaps: hover never reopens a cover file.
                pixmap = icon.pixmap(regions["cover"].size())
                painter.drawPixmap(regions["cover"].topLeft(), pixmap)
            painter.setFont(option.font)
            painter.setPen(option.palette.color(QPalette.Text))
            title = regions["title"]
            lines = self.title_lines(index.data(Qt.DisplayRole) or "", option.font,
                                     title.width())
            line_step = metrics.lineSpacing() + (5 if self._list_mode() else 4)
            visible = 1 if self._list_mode() else min(
                self.MAX_TITLE_LINES, max(1, title.height() // max(1, line_step)))
            painter.save()
            painter.setClipRect(title)
            for number, line in enumerate(lines[:visible]):
                if number == visible - 1 and len(lines) > visible:
                    line = metrics.elidedText("".join(lines[number:]), Qt.ElideRight,
                                              title.width())
                bounds = QRect(title.left(), title.top() + number * line_step,
                               title.width(), line_step)
                painter.drawText(bounds, Qt.AlignLeft | Qt.AlignVCenter |
                                 Qt.TextSingleLine, line)
            painter.restore()

            from .theme import theme_colors
            dark = self.parent().palette().color(QPalette.Window).lightness() < 128
            colors = theme_colors("Dark" if dark else "Light")
            if option.state & QStyle.State_HasFocus:
                painter.setPen(QPen(QColor(colors["focus"]), 2))
                painter.setBrush(Qt.NoBrush)
                painter.drawRoundedRect(regions["card"].adjusted(2, 2, -3, -3), 10, 10)
            status = str(index.data(Qt.UserRole + 1) or "translating")
            label = {"translating": "กำลังแปล", "paused": "พักแปล",
                     "caught_up": "ชนต้นฉบับแล้ว",
                     "checking_web": "กำลังเช็กกับเว็บ"}.get(status, "กำลังแปล")
            color_token = {"translating": "success", "paused": "warning",
                           "caught_up": "accent", "checking_web": "warning"}.get(
                               status, "success")
            status_rect = regions["status"]
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(colors[color_token]))
            dot_y = status_rect.center().y()
            painter.drawEllipse(QRect(status_rect.left(), dot_y - 4, 8, 8))
            painter.setPen(option.palette.color(QPalette.Text))
            painter.drawText(status_rect.adjusted(15, 0, 0, 0),
                             Qt.AlignLeft | Qt.AlignVCenter | Qt.TextSingleLine,
                             label)
            progress_text = str(index.data(Qt.UserRole + 3) or "")
            progress_rect = regions["progress"]
            painter.setPen(QColor(colors["secondary"]))
            painter.drawText(progress_rect, Qt.AlignLeft | Qt.AlignVCenter |
                             Qt.TextSingleLine,
                             metrics.elidedText(progress_text, Qt.ElideRight,
                                                progress_rect.width()))
            fraction = index.data(Qt.UserRole + 4)
            bar = regions["bar"]
            if fraction is not None and bar.isValid() and not bar.isEmpty():
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(colors["surface2"]))
                painter.drawRoundedRect(bar, 2, 2)
                painter.setBrush(QColor(colors["accent"]))
                filled = QRect(bar)
                filled.setWidth(round(bar.width() * max(0.0, min(1.0, float(fraction)))))
                if filled.width() > 0:
                    painter.drawRoundedRect(filled, 2, 2)
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

    def set_library_view(self, mode):
        """Switch presentation only; model items and their persisted IDs stay put."""
        if self.objectName() != "novelLibrary":
            return
        gallery = mode != "list"
        self.setViewMode(QListWidget.IconMode if gallery else QListWidget.ListMode)
        self.setFlow(QListWidget.LeftToRight if gallery else QListWidget.TopToBottom)
        self.setWrapping(gallery)
        self.setResizeMode(QListWidget.Adjust)
        self.setMovement(QListWidget.Static)
        self.setGridSize(QSize())
        # QListView's explicit gridSize overrides gallery item spacing.
        # Reserve an actual 16px gutter *inside each grid cell*.
        self.setSpacing(0 if gallery else 9)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self._update_library_grid_size()
        self.doItemsLayout()

    def _update_library_grid_size(self):
        if self.objectName() != "novelLibrary":
            return
        delegate = self.itemDelegate()
        if isinstance(delegate, ProfileItemDelegate):
            desired = delegate.card_size()
            if self.viewMode() == QListWidget.ListMode:
                desired.setWidth(max(desired.width(), self.viewport().width() - 20))
            else:
                desired += QSize(delegate.CELL_GAP, delegate.CELL_GAP)
            if self.gridSize() != desired:
                self.setGridSize(desired)

    def changeEvent(self, event):
        super().changeEvent(event)
        # Styles and application font changes may arrive after an initial
        # geometry pass. Recompute the gallery cell when metrics change.
        if event.type() in (QEvent.FontChange, QEvent.StyleChange):
            self._update_library_grid_size()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_library_grid_size()

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
        """Reorder visible slots without changing hidden profiles' relative slots."""
        source = next((i for i in range(self.count())
                       if self.item(i).data(Qt.UserRole) == self._drag_profile_id), -1)
        if self._drag_profile_id is None or source < 0 or self.item(source).isHidden():
            event.ignore()
            self._clear_drag_target()
            return
        visible = [i for i in range(self.count()) if not self.item(i).isHidden()]
        insertion = self._drop_row(event.position().toPoint())
        destination = sum(i < insertion for i in visible)
        origin = visible.index(source)
        if origin < destination:
            destination -= 1
        destination = max(0, min(destination, len(visible) - 1))
        if origin != destination:
            items = [self.item(i) for i in range(self.count())]
            ordered = [items[i] for i in visible]
            moved = ordered.pop(origin)
            ordered.insert(destination, moved)
            for slot, item in zip(visible, ordered):
                items[slot] = item
            previous = self.blockSignals(True)
            try:
                for i in range(self.count() - 1, -1, -1):
                    self.takeItem(i)
                for item in items:
                    self.addItem(item)
                self.setCurrentItem(moved)
                self.doItemsLayout()
            finally:
                self.blockSignals(previous)
            self.orderChanged.emit([self.item(i).data(Qt.UserRole)
                                    for i in range(self.count())])
        event.setDropAction(Qt.MoveAction)
        event.accept()
        self._clear_drag_target()
