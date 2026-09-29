from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QFontDatabase, QFontMetrics, QPainter, QTextFormat
from PySide6.QtWidgets import QLabel, QMessageBox, QPlainTextEdit, QTabWidget, QTextEdit, QVBoxLayout, QWidget


TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".json", ".yaml", ".yml", ".toml",
    ".py", ".js", ".ts", ".css", ".html", ".xml", ".csv",
}


class LineNumberArea(QWidget):
    def __init__(self, editor: "CodeEditor"):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QSize(self.editor.line_number_area_width(), 0)

    def paintEvent(self, event):
        self.editor.line_number_area_paint_event(event)


class CodeEditor(QPlainTextEdit):
    """Native text editor with a VS Code-style line-number gutter."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.line_number_area = LineNumberArea(self)
        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self.highlight_current_line)

        font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        self.setFont(font)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        metrics = QFontMetrics(font)
        self.setTabStopDistance(metrics.horizontalAdvance(" ") * 4)
        self.update_line_number_area_width()
        self.highlight_current_line()

    def line_number_area_width(self):
        digits = max(2, len(str(max(1, self.blockCount()))))
        return 12 + self.fontMetrics().horizontalAdvance("9") * digits

    def update_line_number_area_width(self, _=0):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def update_line_number_area(self, rect, dy):
        if dy:
            self.line_number_area.scroll(0, dy)
        else:
            self.line_number_area.update(
                0, rect.y(), self.line_number_area.width(), rect.height()
            )
        if rect.contains(self.viewport().rect()):
            self.update_line_number_area_width()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self.line_number_area.setGeometry(
            QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height())
        )

    def line_number_area_paint_event(self, event):
        painter = QPainter(self.line_number_area)
        painter.fillRect(event.rect(), self.palette().alternateBase())

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = round(
            self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        )
        bottom = top + round(self.blockBoundingRect(block).height())

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.setPen(self.palette().placeholderText().color())
                painter.drawText(
                    0,
                    top,
                    self.line_number_area.width() - 6,
                    self.fontMetrics().height(),
                    Qt.AlignRight,
                    str(block_number + 1),
                )
            block = block.next()
            top = bottom
            if block.isValid():
                bottom = top + round(self.blockBoundingRect(block).height())
            block_number += 1

    def highlight_current_line(self):
        selection = QTextEdit.ExtraSelection()
        selection.format.setBackground(self.palette().alternateBase())
        selection.format.setProperty(QTextFormat.FullWidthSelection, True)
        selection.cursor = self.textCursor()
        selection.cursor.clearSelection()
        self.setExtraSelections([selection])


class EditorTabs(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._update_status)

        self.status = QLabel("ยังไม่ได้เปิดไฟล์")
        self.status.setObjectName("mutedLabel")
        self.status.setContentsMargins(8, 2, 8, 2)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.tabs, 1)
        layout.addWidget(self.status)

    @staticmethod
    def supports(path: str | Path) -> bool:
        return Path(path).suffix.lower() in TEXT_EXTENSIONS

    @staticmethod
    def _path(editor) -> Path | None:
        value = editor.property("documentPath")
        return Path(value) if value else None

    @staticmethod
    def _dirty(editor) -> bool:
        return bool(editor.property("documentDirty"))

    def _set_dirty(self, editor, dirty: bool):
        editor.setProperty("documentDirty", dirty)
        index = self.tabs.indexOf(editor)
        if index >= 0:
            path = self._path(editor)
            label = path.name if path else "Untitled"
            self.tabs.setTabText(index, label + (" ●" if dirty else ""))
        self._update_status(self.tabs.currentIndex())

    def open_file(self, path: str | Path):
        path = Path(path).expanduser().resolve()
        if not path.is_file():
            QMessageBox.warning(self, "เปิดไฟล์ไม่ได้", f"ไม่พบไฟล์:\n{path}")
            return None
        if not self.supports(path):
            QMessageBox.information(
                self,
                "ไฟล์นี้เปิดด้วย Editor ไม่ได้",
                "Editor ภายในรองรับไฟล์ข้อความ เช่น .txt, .md และ .json",
            )
            return None

        for index in range(self.tabs.count()):
            editor = self.tabs.widget(index)
            if self._path(editor) == path:
                self.tabs.setCurrentIndex(index)
                return editor

        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError as exc:
            QMessageBox.warning(self, "อ่านไฟล์ไม่ได้", str(exc))
            return None

        editor = CodeEditor()
        editor.setProperty("documentPath", str(path))
        editor.setProperty("documentDirty", False)
        editor.blockSignals(True)
        editor.setPlainText(text)
        editor.blockSignals(False)
        editor.textChanged.connect(lambda e=editor: self._set_dirty(e, True))
        editor.cursorPositionChanged.connect(
            lambda e=editor: self._update_status(self.tabs.indexOf(e))
        )

        index = self.tabs.addTab(editor, path.name)
        self.tabs.setTabToolTip(index, str(path))
        self.tabs.setCurrentIndex(index)
        editor.setFocus()
        self._update_status(index)
        return editor

    def save_editor(self, editor) -> bool:
        path = self._path(editor)
        if path is None:
            return True
        try:
            path.write_text(editor.toPlainText(), encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "บันทึกไฟล์ไม่ได้", str(exc))
            return False
        self._set_dirty(editor, False)
        return True

    def save_current(self) -> bool:
        editor = self.tabs.currentWidget()
        return self.save_editor(editor) if editor else True

    def save_all(self) -> bool:
        for index in range(self.tabs.count()):
            editor = self.tabs.widget(index)
            if self._dirty(editor) and not self.save_editor(editor):
                return False
        return True

    def dirty_count(self) -> int:
        return sum(self._dirty(self.tabs.widget(i)) for i in range(self.tabs.count()))

    def close_tab(self, index: int):
        editor = self.tabs.widget(index)
        if editor is None:
            return
        if self._dirty(editor):
            result = QMessageBox.question(
                self,
                "ไฟล์ยังไม่ได้บันทึก",
                f"บันทึกการแก้ไข {self.tabs.tabText(index).replace(' ●', '')} ก่อนปิดหรือไม่?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save,
            )
            if result == QMessageBox.Cancel:
                return
            if result == QMessageBox.Save and not self.save_editor(editor):
                return
        self.tabs.removeTab(index)
        editor.deleteLater()
        self._update_status(self.tabs.currentIndex())

    def close_path(self, path: Path):
        path = path.resolve()
        for index in reversed(range(self.tabs.count())):
            editor = self.tabs.widget(index)
            existing = self._path(editor)
            if existing and existing.resolve() == path:
                editor.setProperty("documentDirty", False)
                self.tabs.removeTab(index)
                editor.deleteLater()

    def rename_path(self, old_path: Path, new_path: Path):
        old_path = old_path.resolve()
        new_path = new_path.resolve()
        for index in range(self.tabs.count()):
            editor = self.tabs.widget(index)
            existing = self._path(editor)
            if existing and existing.resolve() == old_path:
                editor.setProperty("documentPath", str(new_path))
                suffix = " ●" if self._dirty(editor) else ""
                self.tabs.setTabText(index, new_path.name + suffix)
                self.tabs.setTabToolTip(index, str(new_path))

    def open_paths(self) -> list[str]:
        result = []
        for index in range(self.tabs.count()):
            path = self._path(self.tabs.widget(index))
            if path:
                result.append(str(path))
        return result

    def restore_paths(self, paths, current_index=0):
        for path in paths or []:
            candidate = Path(path).expanduser()
            if candidate.is_file() and self.supports(candidate):
                self.open_file(candidate)
        if self.tabs.count():
            self.tabs.setCurrentIndex(
                max(0, min(int(current_index or 0), self.tabs.count() - 1))
            )

    def _update_status(self, index):
        if index < 0:
            self.status.setText("ยังไม่ได้เปิดไฟล์")
            return
        editor = self.tabs.widget(index)
        if editor is None:
            return
        path = self._path(editor)
        cursor = editor.textCursor()
        suffix = path.suffix.lower().lstrip(".").upper() if path else "TEXT"
        self.status.setText(
            f"Ln {cursor.blockNumber()+1}, Col {cursor.positionInBlock()+1}   UTF-8   {suffix}"
        )
