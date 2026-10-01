from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetrics, QPainter, QTextBlockFormat, QTextCursor, QTextDocument, QTextFormat, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
    QPushButton, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from .theme import editor_colors


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

    def __init__(self, parent=None, font_size=11.0, appearance="Light"):
        super().__init__(parent)
        self.appearance = appearance
        self.colors = editor_colors(appearance)
        self.setObjectName("codeEditor")
        self.line_number_area = LineNumberArea(self)
        self.line_number_area.setObjectName("lineNumberArea")
        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self.highlight_current_line)

        families = set(QFontDatabase.families())
        preferred = ["Segoe UI Variable Text", "Segoe UI", "Leelawadee UI", "Microsoft YaHei UI"]
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
            "p { margin-top: 0; margin-bottom: 2px; line-height: 120%; }"
        )
        self._apply_style(font_size)
        metrics = QFontMetrics(font)
        self.setTabStopDistance(metrics.horizontalAdvance(" ") * 4)
        self.update_line_number_area_width()
        self.highlight_current_line()

    def set_font_size(self, size):
        font = self.font()
        font.setPointSizeF(float(size))
        self.setFont(font)
        self._apply_style(size)
        self.setTabStopDistance(QFontMetrics(font).horizontalAdvance(" ") * 4)
        self.update_line_number_area_width()

    def set_appearance(self, appearance):
        self.appearance = appearance
        self.colors = editor_colors(appearance)
        self._apply_style(self.font().pointSizeF())
        self.highlight_current_line()
        self.line_number_area.update()

    def _apply_style(self, size):
        colors = self.colors
        self.setStyleSheet(
            f"""
            QPlainTextEdit#codeEditor {{
                background: {colors['background']};
                color: {colors['foreground']};
                border: 0;
                padding: 7px 10px;
                selection-background-color: {colors['selection']};
                selection-color: {colors['selection_text']};
                font-size: {float(size):g}pt;
            }}
            """
        )

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
        painter.fillRect(event.rect(), QColor(self.colors["gutter"]))

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = round(
            self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        )
        bottom = top + round(self.blockBoundingRect(block).height())

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.setPen(QColor(self.colors["gutter_text"]))
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
        line.format.setBackground(QColor(self.colors["current_line"]))
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
                match.format.setBackground(QColor(self.colors["find"]))
                match.format.setForeground(QColor(self.colors["find_text"]))
                selections.append(match)
        self.setExtraSelections(selections)


class EditorTabs(QWidget):
    """Multi-tab text editor that auto-saves the original file after typing stops."""

    statusChanged = Signal(str)
    fontSizeChanged = Signal(float)
    documentSaved = Signal(str)

    def __init__(self, parent=None, font_size=11.0, appearance="Light"):
        super().__init__(parent)
        self._font_size = float(font_size)
        self.appearance = appearance
        self.colors = editor_colors(appearance)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("editorTabs")
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.tabBar().setDrawBase(False)
        self.tabs.tabBar().setExpanding(False)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self._active_editor = None
        self._status_text = "พร้อมใช้งาน  ·  0 คำ  ·  0 อักขระ"
        self.tabs.currentChanged.connect(self._handle_tab_change)
        self._search_text = ""

        self.status = QLabel("ยังไม่ได้เปิดไฟล์")
        self.status.setObjectName("editorStatus")
        self.status.setContentsMargins(8, 2, 8, 2)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.tabs, 1)
        # Status is supplied by the application status bar; retain the label
        # for compatibility with older UI smoke checks, but keep it hidden.
        self.status.hide()

        self.find_panel = QFrame(self)
        self.find_panel.setObjectName("editorFindPanel")
        panel_layout = QVBoxLayout(self.find_panel)
        panel_layout.setContentsMargins(10, 8, 10, 8)
        panel_layout.setSpacing(6)
        find_row = QHBoxLayout()
        find_row.setSpacing(6)
        self.find_input = QLineEdit(self.find_panel)
        self.find_input.setPlaceholderText("ค้นหาในไฟล์…")
        self.find_input.setMinimumWidth(230)
        self.find_count = QLabel("0/0", self.find_panel)
        self.find_count.setMinimumWidth(42)
        self.find_count.setAlignment(Qt.AlignCenter)
        previous = QPushButton("↑", self.find_panel)
        previous.setToolTip("ผลก่อนหน้า · Shift+Enter")
        next_match = QPushButton("↓", self.find_panel)
        next_match.setToolTip("ผลถัดไป · Enter")
        self.replace_toggle = QPushButton("แทนที่", self.find_panel)
        close_find = QPushButton("×", self.find_panel)
        close_find.setToolTip("ปิด · Esc")
        for widget in (self.find_input, self.find_count, previous, next_match,
                       self.replace_toggle, close_find):
            find_row.addWidget(widget)
        panel_layout.addLayout(find_row)

        self.replace_row = QWidget(self.find_panel)
        replace_layout = QHBoxLayout(self.replace_row)
        replace_layout.setContentsMargins(0, 0, 0, 0)
        replace_layout.setSpacing(6)
        self.replace_input = QLineEdit(self.replace_row)
        self.replace_input.setPlaceholderText("แทนที่ด้วย…")
        self.replace_input.setMinimumWidth(230)
        self.replace_current_button = QPushButton("แทนที่", self.replace_row)
        self.replace_all_button = QPushButton("แทนที่ทั้งหมด", self.replace_row)
        replace_layout.addWidget(self.replace_input, 1)
        replace_layout.addWidget(self.replace_current_button)
        replace_layout.addWidget(self.replace_all_button)
        panel_layout.addWidget(self.replace_row)
        self.replace_row.hide()

        previous.clicked.connect(lambda: self._find_next(backward=True))
        next_match.clicked.connect(self._find_next)
        close_find.clicked.connect(self.close_find)
        self.replace_toggle.clicked.connect(self._toggle_replace)
        self.replace_current_button.clicked.connect(self._replace_current)
        self.replace_all_button.clicked.connect(self._replace_all)
        self.replace_input.returnPressed.connect(self._replace_current)
        self.find_input.textChanged.connect(self._on_find_text_changed)
        self.find_input.returnPressed.connect(self._find_next)
        self.find_panel.hide()
        self._place_find_panel()
        self._find_shortcut = QShortcut(QKeySequence("Ctrl+H"), self)
        self._find_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self._find_shortcut.activated.connect(self.show_find)
        self._escape_shortcut = QShortcut(QKeySequence("Escape"), self)
        self._escape_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self._escape_shortcut.activated.connect(self.close_find)
        self.set_appearance(appearance)

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

        editor = CodeEditor(font_size=self._font_size, appearance=self.appearance)
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
            self._status_text = "พร้อมใช้งาน  ·  0 คำ  ·  0 อักขระ"
            self.statusChanged.emit(self._status_text)
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
        self._status_text = (
            f"{state}  ·  {words:,} คำ  ·  {len(text):,} อักขระ  ·  "
            f"Ln {cursor.blockNumber()+1}, Col {cursor.positionInBlock()+1}  ·  UTF-8 {suffix}"
        )
        self.statusChanged.emit(self._status_text)
        self._update_find_matches()

    def current_status_text(self):
        return self._status_text

    @staticmethod
    def _format_document(editor):
        cursor = QTextCursor(editor.document())
        cursor.select(QTextCursor.Document)
        block_format = QTextBlockFormat()
        block_format.setLineHeight(120.0, QTextBlockFormat.ProportionalHeight.value)
        block_format.setBottomMargin(2)
        cursor.mergeBlockFormat(block_format)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place_find_panel()

    def _place_find_panel(self):
        if hasattr(self, "find_panel"):
            self.find_panel.adjustSize()
            self.find_panel.move(max(8, self.width() - self.find_panel.width() - 22), 14)
            self.find_panel.raise_()

    def set_appearance(self, appearance):
        self.appearance = appearance
        self.colors = editor_colors(appearance)
        colors = self.colors
        self.tabs.setStyleSheet(
            f"""
            QTabWidget#editorTabs::pane {{
                background: {colors['background']}; border: 0; border-radius: 0;
            }}
            QTabWidget#editorTabs, QTabWidget#editorTabs::tab-bar,
            QTabWidget#editorTabs QTabBar, QTabWidget#editorTabs QTabBar::base {{
                background: {colors['gutter']}; border: 0;
            }}
            QTabWidget#editorTabs QTabBar::tab {{
                background: {colors['tab']}; color: {colors['gutter_text']};
                border: 0; border-right: 1px solid {colors['border']};
                border-radius: 9px 9px 0 0;
                padding: 10px 15px; min-width: 92px;
            }}
            QTabWidget#editorTabs QTabBar::tab:hover {{
                background: {colors['current_line']}; color: {colors['foreground']};
            }}
            QTabWidget#editorTabs QTabBar::tab:selected {{
                background: {colors['tab_selected']}; color: {colors['foreground']};
                border-top: 2px solid {colors['accent']}; font-weight: 600;
            }}
            QFrame#editorFindPanel {{
                background: {colors['background']}; color: {colors['foreground']};
                border: 1px solid {colors['border']}; border-radius: 14px;
            }}
            QFrame#editorFindPanel QLineEdit {{
                background: {colors['background']}; color: {colors['foreground']};
                border: 1px solid {colors['border']}; border-radius: 9px;
                padding: 5px 8px; min-height: 22px;
            }}
            QFrame#editorFindPanel QPushButton {{
                background: {colors['current_line']}; color: {colors['foreground']};
                border: 1px solid {colors['gutter_text']}; border-radius: 6px;
                padding: 5px 9px; min-height: 22px;
            }}
            QFrame#editorFindPanel QPushButton:hover {{
                background: {colors['selection']};
            }}
            QFrame#editorFindPanel QLabel {{ color: {colors['foreground']}; }}
            """
        )
        for index in range(self.tabs.count()):
            self.tabs.widget(index).set_appearance(appearance)
        self._place_find_panel()

    def _toggle_replace(self):
        self.replace_row.setVisible(not self.replace_row.isVisible())
        self._place_find_panel()
        if self.replace_row.isVisible():
            self.replace_input.setFocus(Qt.ShortcutFocusReason)

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
            if hasattr(self, "find_count"):
                self.find_count.setText("0/0")
            return
        editor._find_query = query
        editor.highlight_current_line()
        cursor = editor.textCursor()
        matches = self._find_matches(editor, query)
        current = next(
            (
                index for index, match in enumerate(matches, 1)
                if cursor.hasSelection()
                and cursor.selectionStart() == match[0]
                and cursor.selectionEnd() == match[1]
            ),
            0,
        )
        if hasattr(self, "find_count"):
            self.find_count.setText(f"{current}/{len(matches)}")

    @staticmethod
    def _find_matches(editor, query):
        matches = []
        if not query:
            return matches
        cursor = QTextCursor(editor.document())
        while True:
            cursor = editor.document().find(query, cursor)
            if cursor.isNull():
                break
            start, end = cursor.selectionStart(), cursor.selectionEnd()
            matches.append((start, end))
            cursor.setPosition(end)
        return matches

    def _on_find_text_changed(self, *_args):
        self._update_find_matches()
        if self.find_input.text():
            self._find_next()

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

    def _replace_current(self):
        editor = self.tabs.currentWidget()
        query = self.find_input.text()
        if editor is None or not query:
            return
        cursor = editor.textCursor()
        selected = cursor.selectedText().replace("\u2029", "\n")
        if not cursor.hasSelection() or selected.casefold() != query.casefold():
            if not editor.find(query):
                cursor = editor.textCursor()
                cursor.movePosition(QTextCursor.Start)
                editor.setTextCursor(cursor)
                if not editor.find(query):
                    return
            cursor = editor.textCursor()
        cursor.insertText(self.replace_input.text())
        editor.setTextCursor(cursor)
        self._update_find_matches()

    def _replace_all(self):
        editor = self.tabs.currentWidget()
        query = self.find_input.text()
        if editor is None or not query:
            return
        matches = self._find_matches(editor, query)
        if not matches:
            return
        replacement = self.replace_input.text()
        cursor = QTextCursor(editor.document())
        cursor.beginEditBlock()
        for start, end in reversed(matches):
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.KeepAnchor)
            cursor.insertText(replacement)
        cursor.endEditBlock()
        editor.setTextCursor(cursor)
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
