"""Original scalable line icons; no platform-dependent folder glyphs."""
import math
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QIcon, QIconEngine, QPainter, QPainterPath, QPen, QColor, QPixmap


class LineIconEngine(QIconEngine):
    def __init__(self, name, color, disabled):
        super().__init__()
        self.name, self.color, self.disabled = name, color, disabled

    def clone(self):
        return LineIconEngine(self.name, self.color, self.disabled)

    def paint(self, painter, rect, mode, state):
        painter.save()
        side = min(rect.width(), rect.height())
        painter.translate(rect.x() + (rect.width()-side)/2, rect.y() + (rect.height()-side)/2)
        painter.scale(side/24, side/24)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(self.disabled if mode == QIcon.Disabled else self.color), 1.7)
        pen.setCapStyle(Qt.RoundCap); pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen); painter.setBrush(Qt.NoBrush)
        path = QPainterPath()
        if self.name == 'library':
            path.moveTo(12, 5); path.cubicTo(9, 3, 5, 3, 3, 4)
            path.lineTo(3, 19); path.cubicTo(6, 18, 9, 18, 12, 20)
            path.cubicTo(15, 18, 18, 18, 21, 19); path.lineTo(21, 4)
            path.cubicTo(18, 3, 15, 3, 12, 5); path.lineTo(12, 20)
        elif self.name == 'workspace':
            path.moveTo(14, 3); path.lineTo(4, 3); path.lineTo(4, 21); path.lineTo(17, 21); path.lineTo(17, 17)
            path.moveTo(8, 7); path.lineTo(12, 7); path.moveTo(8, 11); path.lineTo(11, 11)
            path.moveTo(12, 17); path.lineTo(13, 13); path.lineTo(20, 6); path.lineTo(23, 9)
            path.lineTo(16, 16); path.closeSubpath()
        elif self.name == 'progress':
            path.moveTo(3, 3); path.lineTo(3, 21); path.lineTo(21, 21)
            for x, y in ((7, 13), (12, 9), (17, 5)):
                path.moveTo(x, 17); path.lineTo(x, y)
        elif self.name == 'groups':
            for x, y in ((3, 7), (8, 4), (13, 1)):
                path.moveTo(x+7, y); path.lineTo(x, y); path.lineTo(x, y+15)
                path.lineTo(x+7, y+15); path.lineTo(x+7, y+3)
        elif self.name == 'settings':
            for index in range(32):
                angle = index * math.pi / 16
                radius = 9 if index % 4 in (1, 2) else 7
                point = (12 + radius*math.cos(angle), 12 + radius*math.sin(angle))
                if index == 0: path.moveTo(*point)
                else: path.lineTo(*point)
            path.closeSubpath(); path.addEllipse(QRectF(8.5, 8.5, 7, 7))
        painter.drawPath(path)
        painter.restore()

    def pixmap(self, size, mode, state):
        pixmap = QPixmap(size); pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        self.paint(painter, pixmap.rect(), mode, state); painter.end()
        return pixmap

    def scaledPixmap(self, size, mode, state, scale):
        pixmap = self.pixmap(size * scale, mode, state)
        pixmap.setDevicePixelRatio(scale)
        return pixmap


def navigation_icon(name, tokens):
    return QIcon(LineIconEngine(name, tokens['secondary'], tokens['disabled_text']))
