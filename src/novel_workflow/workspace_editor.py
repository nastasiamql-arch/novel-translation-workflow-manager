from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetrics, QPainter, QTextBlockFormat, QTextCursor, QTextDocument, QTextFormat, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
    QPushButton, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)


TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".json", ".yaml", ".yml", ".toml",
    ".py", ".js", ".ts", ".css", ".html", ".xml", ".csv",
}
AUTO_SAVE_DELAY_MS = 1000


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

    def __init__(self, parent=None, font_size=11.0):
        super().__init__(parent)
        self.setObjectName("codeEditor")
        self.line_number_area = LineNumberArea(self)
        self.line_number_area.setObjectName("lineNumberArea")
        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self.highlight_current_line)

        families = set(QFontDatabase.families())
        preferred = ["Cascadia Code", "Cascadia Mono", "Consolas", "Leelawadee UI", "Segoe UI"]
        chosen = [name for name in preferred if name in families]

        font = QFont()
        if chosen:
            font.setFamilies(chosen)
        else:
            font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        font.setPointSizeF(float(font_size))
        try:
            font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
            font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        except AttributeError:
            pass

        self.setFont(font)
        self.setCursorWidth(2)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.document().setDefaultStyleSheet(
            "p { margin-top: 0; margin-bottom: 6px; line-height: 135%; }"
        )
        self.setStyleSheet(
            f"""
            QPlainTextEdit#codeEditor {{
                background: #1E1E1E;
                color: #D4D4D4;
                border: 0;
                padding: 7px 10px;
                selection-background-color: #264F78;
                selection-color: #FFFFFF;
                font-size: {float(font_size):g}pt;
            }}
            """
        )
        metrics = QFontMetrics(font)
        self.setTabStopDistance(metrics.horizontalAdvance(" ") * 4)
        self.update_line_number_area_width()
        self.highlight_current_line()

    def set_font_size(self, size):
        font = self.font()
        font.setPointSizeF(float(size))
        self.setFont(font)
        self.setStyleSheet(
            f"""
            QPlainTextEdit#codeEditor {{
                background: #1E1E1E; color: #D4D4D4; border: 0;
                padding: 7px 10px; selection-background-color: #264F78;
                selection-color: #FFFFFF; font-size: {float(size):g}pt;
            }}
            """
        )
        self.setTabStopDistance(QFontMetrics(font).horizontalAdvance(" ") * 4)
        self.update_line_number_area_width()

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
        painter.fillRect(event.rect(), QColor("#1E1E1E"))

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = round(
            self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        )
        bottom = top + round(self.blockBoundingRect(block).height())

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.setPen(QColor("#858585"))
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
        selections = []
        line = QTextEdit.ExtraSelection()
        line.format.setBackground(QColor("#252a32"))
        line.format.setProperty(QTextFormat.FullWidthSelection, True)
        line.cursor = self.textCursor()
        line.cursor.clearSelection()
        selections.append(line)
        query = str(getattr(self, "_find_query", ""))
        if query:
            cursor = QTextCursor(self.document())
            while True:
                cursor = self.document().find(query, cursor)
                if cursor.isNull():
                    break
                match = QTextEdit.ExtraSelection()
                match.cursor = cursor
                match.format.setBackground(QColor("#665523"))
                match.format.setForeground(QColor("#fff4ce"))
                selections.append(match)
        self.setExtraSelections(selections)


class EditorTabs(QWidget):
    """Multi-tab text editor that auto-saves the original file after typing stops."""

    statusChanged = Signal(str)
    fontSizeChanged = Signal(float)
    documentSaved = Signal(str)

    def __init__(self, parent=None, font_size=11.0):
        super().__init__(parent)
        self._font_size = float(font_size)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("editorTabs")
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.tabBar().setDrawBase(False)
        self.tabs.tabBar().setExpanding(False)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self._active_editor = None
        self.tabs.currentChanged.connect(self._handle_tab_change)
        self._search_text = ""

        self.status = QLabel("ยังไม่ได้เปิดไฟล์")
        self.status.setObjectName("editorStatus")
        self.status.setContentsMargins(8, 2, 8, 2)

        self.setStyleSheet(
            """
            QTabWidget#editorTabs::pane {
                background: #1E1E1E;
                border: 0;
                border-radius: 0;
            }
            QTabWidget#editorTabs, QTabWidget#editorTabs::tab-bar,
            QTabWidget#editorTabs QTabBar, QTabWidget#editorTabs QTabBar::base {
                background: #1E1E1E;
                border: 0;
            }
            QTabWidget#editorTabs QTabBar::tab {
                background: #181818;
                color: #969696;
                border: 0;
                border-right: 1px solid #2A2A2A;
                border-bottom: 1px solid #2A2A2A;
                padding: 8px 13px;
                min-width: 92px;
            }
            QTabWidget#editorTabs QTabBar::tab:hover {
                background: #202020;
                color: #CCCCCC;
            }
            QTabWidget#editorTabs QTabBar::tab:selected {
                background: #1E1E1E;
                color: #FFFFFF;
                border-top: 1px solid #007ACC;
                border-bottom: 0;
            }
            QLabel#editorStatus {
                background: #181818;
                color: #B3B3B3;
                border-top: 1px solid #2A2A2A;
                padding: 4px 8px;
                font-size: 9.5pt;
            }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.tabs, 1)
        # Status is supplied by the application status bar; retain the label
        # for compatibility with older UI smoke checks, but keep it hidden.
        self.status.hide()

        self.find_panel = QFrame(self)
        self.find_panel.setObjectName("editorFindPanel")
        self.find_panel.setStyleSheet(
            "QFrame#editorFindPanel { background:#20242b; color:#e6e8eb; "
            "border:1px solid #414854; border-radius:8px; }"
            "QLineEdit { background:#171a20; color:#f0f2f5; border:1px solid #4b5563; "
            "border-radius:5px; padding:5px 8px; min-height:20px; }"
            "QPushButton { background:#2b3039; color:#e6e8eb; border:0; "
            "border-radius:5px; padding:5px 8px; }"
            "QPushButton:hover { background:#394150; }"
        )
        find_layout = QHBoxLayout(self.find_panel)
        find_layout.setContentsMargins(8, 6, 8, 6)
        find_layout.setSpacing(5)
        self.find_input = QLineEdit(self.find_panel)
        self.find_input.setPlaceholderText("ค้นหาในไฟล์…")
        self.find_count = QLabel("0/0", self.find_panel)
        previous = QPushButton("↑", self.find_panel)
        next_match = QPushButton("↓", self.find_panel)
        close_find = QPushButton("×", self.find_panel)
        for widget in (self.find_input, self.find_count, previous, next_match, close_find):
            find_layout.addWidget(widget)
        previous.clicked.connect(lambda: self._find_next(backward=True))
        next_match.clicked.connect(self._find_next)
        close_find.clicked.connect(self.close_find)
        self.find_input.textChanged.connect(self._update_find_matches)
        self.find_input.returnPressed.connect(self._find_next)
        self.find_panel.hide()
        self._place_find_panel()
        self._find_shortcut = QShortcut(QKeySequence("Ctrl+H"), self)
        self._find_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self._find_shortcut.activated.connect(self.show_find)
        self._escape_shortcut = QShortcut(QKeySequence("Escape"), self)
        self._escape_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self._escape_shortcut.activated.connect(self.close_find)

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

    def _set_dirty(self, editor, dirty: bool, state: str | None = None):
        editor.setProperty("documentDirty", dirty)
        if state is not None:
            editor.setProperty("saveState", state)
        index = self.tabs.indexOf(editor)
        if index >= 0:
            path = self._path(editor)
            label = path.name if path else "Untitled"
            self.tabs.setTabText(index, label + (" ●" if dirty else ""))
        self._update_status(self.tabs.currentIndex())

    def _on_text_changed(self, editor):
        self._set_dirty(editor, True, "กำลังรอบันทึกอัตโนมัติ…")
        timer = getattr(editor, "autosave_timer", None)
        if timer is not None:
            timer.start(AUTO_SAVE_DELAY_MS)

    def _autosave_editor(self, editor):
        if self._dirty(editor):
            self.save_editor(editor, quiet=True, autosave=True)

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
                current = self.tabs.currentWidget()
                if current is not None and current is not editor and self._dirty(current):
                    if not self.save_editor(current, quiet=True):
                        return None
                self.tabs.setCurrentIndex(index)
                return editor

        current = self.tabs.currentWidget()
        if current is not None and self._dirty(current):
            if not self.save_editor(current, quiet=True):
                QMessageBox.warning(self, "บันทึกไฟล์ไม่ได้", "บันทึกไฟล์ปัจจุบันไม่สำเร็จ จึงยังเปิดไฟล์ใหม่ไม่ได้")
                return None

        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError as exc:
            QMessageBox.warning(self, "อ่านไฟล์ไม่ได้", str(exc))
            return None

        editor = CodeEditor(font_size=self._font_size)
        editor.setProperty("documentPath", str(path))
        editor.setProperty("documentDirty", False)
        editor.setProperty("saveState", "บันทึกแล้ว")
        editor.blockSignals(True)
        editor.setPlainText(text)
        editor.blockSignals(False)
        self._format_document(editor)

        editor.autosave_timer = QTimer(editor)
        editor.autosave_timer.setSingleShot(True)
        editor.autosave_timer.setInterval(AUTO_SAVE_DELAY_MS)
        editor.autosave_timer.timeout.connect(
            lambda e=editor: self._autosave_editor(e)
        )
        editor.textChanged.connect(lambda e=editor: self._on_text_changed(e))
        editor.cursorPositionChanged.connect(
            lambda e=editor: self._update_status(self.tabs.indexOf(e))
        )
        editor.textChanged.connect(lambda e=editor: self._update_find_matches() if e is self.tabs.currentWidget() else None)

        index = self.tabs.addTab(editor, path.name)
        self.tabs.setTabToolTip(index, str(path))
        self.tabs.setCurrentIndex(index)
        editor.setFocus()
        self._update_status(index)
        return editor

    def save_editor(self, editor, quiet=False, autosave=False) -> bool:
        path = self._path(editor)
        if path is None:
            return True

        timer = getattr(editor, "autosave_timer", None)
        if timer is not None:
            timer.stop()

        try:
            path.write_text(editor.toPlainText(), encoding="utf-8")
        except OSError as exc:
            editor.setProperty(
                "saveState",
                "บันทึกอัตโนมัติไม่สำเร็จ" if autosave else "บันทึกไม่สำเร็จ",
            )
            self._update_status(self.tabs.indexOf(editor))
            if not quiet:
                QMessageBox.warning(self, "บันทึกไฟล์ไม่ได้", str(exc))
            return False

        self._set_dirty(
            editor,
            False,
            "บันทึกอัตโนมัติแล้ว" if autosave else "บันทึกแล้ว",
        )
        self.documentSaved.emit(str(path))
        return True

    def set_font_size(self, size):
        self._font_size = max(8.0, min(28.0, float(size)))
        for index in range(self.tabs.count()):
            self.tabs.widget(index).set_font_size(self._font_size)
        self.fontSizeChanged.emit(self._font_size)

    def font_size(self):
        return self._font_size

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
        if self._dirty(editor) and not self.save_editor(editor):
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
                timer = getattr(editor, "autosave_timer", None)
                if timer is not None:
                    timer.stop()
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
            self.statusChanged.emit("พร้อมใช้งาน  ·  0 คำ  ·  0 อักขระ")
            return
        editor = self.tabs.widget(index)
        if editor is None:
            return
        path = self._path(editor)
        cursor = editor.textCursor()
        suffix = path.suffix.lower().lstrip(".").upper() if path else "TEXT"
        state = str(editor.property("saveState") or "")
        self.status.setText(
            f"Ln {cursor.blockNumber()+1}, Col {cursor.positionInBlock()+1}   "
            f"UTF-8   {suffix}   •   {state}"
        )
        text = editor.toPlainText()
        words = len(text.split())
        self.statusChanged.emit(
            f"{state}  ·  {words:,} คำ  ·  {len(text):,} อักขระ  ·  "
            f"Ln {cursor.blockNumber()+1}, Col {cursor.positionInBlock()+1}  ·  UTF-8 {suffix}"
        )
        self._update_find_matches()

    @staticmethod
    def _format_document(editor):
        cursor = QTextCursor(editor.document())
        cursor.select(QTextCursor.Document)
        block_format = QTextBlockFormat()
        block_format.setLineHeight(135.0, QTextBlockFormat.ProportionalHeight.value)
        block_format.setBottomMargin(6)
        cursor.mergeBlockFormat(block_format)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place_find_panel()

    def _place_find_panel(self):
        if hasattr(self, "find_panel"):
            self.find_panel.adjustSize()
            self.find_panel.move(max(8, self.width() - self.find_panel.width() - 22), 14)
            self.find_panel.raise_()

    def show_find(self):
        editor = self.tabs.currentWidget()
        selected = editor.textCursor().selectedText() if editor else ""
        selected = selected.replace("\u2029", " ").strip()
        if selected:
            self.find_input.setText(selected)
        self.find_panel.show()
        self.find_panel.raise_()
        self._update_find_matches()
        self.find_input.setFocus(Qt.ShortcutFocusReason)
        if not selected:
            self.find_input.selectAll()

    def close_find(self):
        if self.find_panel.isVisible():
            self.find_panel.hide()
            editor = self.tabs.currentWidget()
            if editor:
                editor.setFocus(Qt.ShortcutFocusReason)
                editor.highlight_current_line()

    def _update_find_matches(self, *_args):
        editor = self.tabs.currentWidget()
        query = self.find_input.text() if hasattr(self, "find_input") else ""
        if editor is None:
            return
        editor._find_query = query
        editor.highlight_current_line()
        text = editor.toPlainText()
        folded_text = text.casefold()
        folded_query = query.casefold()
        starts = []
        if folded_query:
            offset = 0
            while (offset := folded_text.find(folded_query, offset)) >= 0:
                starts.append(offset)
                offset += max(1, len(folded_query))
        count = len(starts)
        cursor = editor.textCursor()
        current = next(
            (i + 1 for i, start in enumerate(starts) if start <= cursor.selectionStart() < start + len(folded_query)),
            0,
        )
        if query and count and current == 0:
            cursor.movePosition(QTextCursor.Start)
            editor.setTextCursor(cursor)
            editor.find(query)
            cursor = editor.textCursor()
            current = 1
        if hasattr(self, "find_count"):
            self.find_count.setText(f"{current}/{count}")

    def _find_next(self, backward=False):
        editor = self.tabs.currentWidget()
        query = self.find_input.text()
        if editor is None or not query:
            return
        flags = QTextDocument.FindBackward if backward else QTextDocument.FindFlags()
        if not editor.find(query, flags):
            cursor = editor.textCursor()
            cursor.movePosition(QTextCursor.End if backward else QTextCursor.Start)
            editor.setTextCursor(cursor)
            editor.find(query, flags)
        self._update_find_matches()

    def _handle_tab_change(self, index):
        editor = self.tabs.widget(index) if index >= 0 else None
        previous = self._active_editor
        if previous is not None and previous is not editor and self._dirty(previous):
            if not self.save_editor(previous, quiet=True):
                old_index = self.tabs.indexOf(previous)
                self.tabs.blockSignals(True)
                if old_index >= 0:
                    self.tabs.setCurrentIndex(old_index)
                self.tabs.blockSignals(False)
                self._update_status(old_index)
                return
        self._active_editor = editor
        self._update_status(index)
