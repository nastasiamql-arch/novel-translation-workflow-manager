from __future__ import annotations

import os
import tempfile
from pathlib import Path
from weakref import WeakSet
from bisect import bisect_left

from PySide6.QtCore import QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetrics, QPainter, QTextBlockFormat, QTextCharFormat, QTextCursor, QTextDocument, QTextFormat, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPlainTextEdit, QPushButton, QSpinBox, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from .theme import editor_colors
from .models import AppSettings


TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".json", ".yaml", ".yml", ".toml",
    ".py", ".js", ".ts", ".css", ".html", ".xml", ".csv", ".tsv",
}
AUTO_SAVE_DELAY_MS = 1000
TXT_EXPORT_TAB = "TXT Export"


def _stage_text_file(destination: Path, text: str) -> Path:
    """Write beside the destination so the completed file can be atomically replaced."""
    staged_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="", dir=destination.parent,
            prefix=f".{destination.name}.", suffix=".part", delete=False,
        ) as staged:
            staged_path = Path(staged.name)
            staged.write(text)
            staged.flush()
            os.fsync(staged.fileno())
        return staged_path
    except OSError:
        if staged_path is not None:
            staged_path.unlink(missing_ok=True)
        raise


class TxtExportTab(QWidget):
    """Application-level text scratchpad with a persistent rotating TXT exporter."""

    instances = WeakSet()

    def __init__(self, settings, status_callback=None, settings_callback=None, parent=None,
                 font_size=11.0, appearance="Dark", context_path_callback=None,
                 context_saved_callback=None, notification_callback=None):
        super().__init__(parent)
        self.instances.add(self)
        self.settings = settings
        self.status_callback = status_callback or (lambda _message: None)
        self.settings_callback = settings_callback or (lambda: None)
        self.context_path_callback = context_path_callback or (lambda: None)
        self.context_saved_callback = context_saved_callback or (lambda _path, _text: None)
        self.notification_callback = notification_callback or (lambda _message: None)
        self.editor = CodeEditor(font_size=font_size, appearance=appearance, parent=self)
        self.filename = QLineEdit(str(settings.txt_export_filename or "segverified"))
        self.filename.setObjectName("txtExportFilename")
        self.directory = QLineEdit(str(settings.txt_export_directory or ""))
        self.directory.setObjectName("txtExportDirectory")
        self.directory.setPlaceholderText("เลือกโฟลเดอร์ปลายทาง")
        self.start = QSpinBox(); self.start.setRange(1, 2_147_483_647)
        self.end = QSpinBox(); self.end.setRange(1, 2_147_483_647)
        self.current = QSpinBox(); self.current.setRange(1, 2_147_483_647)
        self.start.setValue(max(1, int(settings.txt_export_start or 1)))
        self.end.setValue(max(self.start.value(), int(settings.txt_export_end or 100)))
        self.current.setValue(max(self.start.value(), min(self.end.value(), int(settings.txt_export_current or 1))))
        self.word_count = QLabel("0 คำ")
        self.character_count = QLabel("0 อักขระ")
        self._cached_word_count = 0
        self._cached_character_count = 0
        self.stats_timer = QTimer(self)
        self.stats_timer.setSingleShot(True)
        self.stats_timer.setInterval(300)
        self.stats_timer.timeout.connect(self._update_counts)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 8)
        layout.setSpacing(8)
        row = QHBoxLayout()
        row.addWidget(QLabel("ชื่อไฟล์"))
        row.addWidget(self.filename, 1)
        row.addWidget(QLabel("โฟลเดอร์ปลายทาง"))
        row.addWidget(self.directory, 2)
        browse = QPushButton("เลือกโฟลเดอร์")
        browse.clicked.connect(self.choose_directory)
        row.addWidget(browse)
        layout.addLayout(row)
        numbers = QHBoxLayout()
        for label, field in (("เริ่มต้น", self.start), ("สิ้นสุด", self.end)):
            numbers.addWidget(QLabel(label)); numbers.addWidget(field)
        self.number_current_label = QLabel("เลขถัดไป")
        numbers.addWidget(self.number_current_label); numbers.addWidget(self.current)
        numbers.addStretch(1)
        numbers.addWidget(self.word_count); numbers.addWidget(self.character_count)
        layout.addLayout(numbers)
        layout.addWidget(self.editor, 1)
        actions = QHBoxLayout()
        self.copy_button = QPushButton("คัดลอก")
        self.copy_export_button = QPushButton("คัดลอก + ส่งออก")
        self.submit_button = QPushButton("Submit")
        self.submit_button.setObjectName("primaryButton")
        self.submit_button.setToolTip("ส่งออก TXT และเขียนทับ Context ด้วยข้อความเดียวกัน")
        self.reset_button = QPushButton("รีเซ็ตเลข")
        actions.addWidget(self.copy_button); actions.addWidget(self.copy_export_button)
        actions.addStretch(1); actions.addWidget(self.reset_button)
        actions.addWidget(self.submit_button)
        layout.addLayout(actions)
        self.copy_button.clicked.connect(self.copy_text)
        self.copy_export_button.clicked.connect(self.copy_and_export)
        self.submit_button.clicked.connect(lambda: self.export(update_context=True))
        self.reset_button.clicked.connect(self.reset_number)
        self.editor.textChanged.connect(lambda: self.stats_timer.start())
        for field in (self.filename, self.directory):
            field.textChanged.connect(self._save_settings)
        for field in (self.start, self.end, self.current):
            field.valueChanged.connect(self._numbers_changed)
        self.start.valueChanged.connect(lambda value: self.end.setMinimum(value))
        self.start.valueChanged.connect(lambda value: self.current.setMinimum(value))
        self.end.valueChanged.connect(lambda value: self.current.setMaximum(value))
        self.set_tab_appearance(appearance)

    def set_font_size(self, size):
        self.editor.set_font_size(size)

    def set_appearance(self, appearance):
        self.editor.set_appearance(appearance)
        self.set_tab_appearance(appearance)

    def set_tab_appearance(self, appearance):
        colors = editor_colors(appearance)
        self.setStyleSheet(f"background:{colors['background']}; color:{colors['foreground']};")

    def _update_counts(self):
        text = self.editor.toPlainText()
        self._cached_word_count = len(text.split())
        self._cached_character_count = len(text)
        self.word_count.setText(f"{self._cached_word_count:,} คำ")
        self.character_count.setText(f"{self._cached_character_count:,} อักขระ")

    def _numbers_changed(self, *_args):
        self._save_settings()

    def _save_settings(self, *_args):
        self.settings.txt_export_filename = self.filename.text()
        self.settings.txt_export_directory = self.directory.text()
        self.settings.txt_export_start = self.start.value()
        self.settings.txt_export_end = self.end.value()
        self.settings.txt_export_current = self.current.value()
        try:
            self.settings_callback()
        except OSError as exc:
            self.status_callback(f"บันทึกการตั้งค่า TXT Export ไม่สำเร็จ: {exc}")
        for panel in list(self.instances):
            if panel is not self and panel.settings is self.settings:
                panel._load_shared_settings()

    def _load_shared_settings(self):
        fields = (self.filename, self.directory, self.start, self.end, self.current)
        old_states = [field.blockSignals(True) for field in fields]
        try:
            self.filename.setText(self.settings.txt_export_filename)
            self.directory.setText(self.settings.txt_export_directory)
            start = max(1, int(self.settings.txt_export_start or 1))
            end = max(start, int(self.settings.txt_export_end or 100))
            current = max(start, min(end, int(self.settings.txt_export_current or start)))
            self.start.setValue(start)
            self.end.setRange(start, 2_147_483_647)
            self.end.setValue(end)
            self.current.setRange(start, end)
            self.current.setValue(current)
        finally:
            for field, previous in zip(fields, old_states):
                field.blockSignals(previous)

    def choose_directory(self):
        folder = QFileDialog.getExistingDirectory(self, "เลือกโฟลเดอร์ปลายทาง", self.directory.text())
        if folder:
            self.directory.setText(folder)

    def copy_text(self):
        QApplication.clipboard().setText(self.editor.toPlainText())
        self.status_callback("คัดลอกแล้ว")

    def copy_and_export(self):
        self.copy_text()
        self.export()

    @staticmethod
    def normalized_filename(value):
        name = value.strip()
        if name.casefold().endswith(".txt"):
            name = name[:-4]
        if not name or name in {".", ".."} or any(char in '<>:"/\\|?*' or ord(char) < 32 for char in name):
            raise ValueError("ชื่อไฟล์ไม่ถูกต้อง")
        if name.endswith((" ", ".")):
            raise ValueError("ชื่อไฟล์ไม่สามารถลงท้ายด้วยช่องว่างหรือจุด")
        if name.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
            raise ValueError("ชื่อนี้เป็นชื่อสงวนของ Windows")
        return name

    def export(self, update_context=False):
        staged_files = []
        try:
            prefix = self.normalized_filename(self.filename.text())
            folder = Path(self.directory.text().strip()).expanduser()
            if not folder.is_dir():
                raise OSError("ไม่พบโฟลเดอร์ปลายทาง")
            context_path = None
            if update_context:
                selected_context = self.context_path_callback()
                if not selected_context:
                    raise OSError("ยังไม่ได้เลือกไฟล์ Context สำหรับนิยายนี้")
                context_path = Path(selected_context).expanduser()
                if not context_path.is_file():
                    raise OSError("ไม่พบไฟล์ Context")
            target = folder / f"{prefix}{self.current.value()}.txt"
            text = self.editor.toPlainText()
            destinations = [target]
            if context_path is not None:
                destinations.append(context_path)
            for destination in destinations:
                staged_files.append((destination, _stage_text_file(destination, text)))
            for destination, staged in staged_files:
                os.replace(staged, destination)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "ส่งออก TXT ไม่สำเร็จ", str(exc))
            return False
        finally:
            for _destination, staged in staged_files:
                try:
                    staged.unlink(missing_ok=True)
                except OSError:
                    pass
        completed = self.current.value()
        self.current.setValue(self.start.value() if completed >= self.end.value() else completed + 1)
        self._save_settings()
        if update_context:
            self.context_saved_callback(context_path, text)
            self.status_callback(
                f"ส่งออก {target.name} และอัปเดต Context แล้ว · เลขถัดไป {self.current.value()}"
            )
            self.notification_callback(
                f"ส่งออก {target.name} และอัปเดต Context แล้ว · เลขถัดไป {self.current.value()}"
            )
        else:
            self.status_callback(f"ส่งออก {target.name} แล้ว")
        return True

    def reset_number(self):
        self.current.setValue(self.start.value())
        self._save_settings()


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

    def __init__(self, parent=None, font_size=11.0, appearance="Dark"):
        super().__init__(parent)
        self.appearance = appearance
        self.colors = editor_colors(appearance)
        self.setObjectName("codeEditor")
        self.line_number_area = LineNumberArea(self)
        self.line_number_area.setObjectName("lineNumberArea")
        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self.highlight_current_line)
        self.verticalScrollBar().valueChanged.connect(
            lambda _value: self.highlight_current_line()
        )

        # Qt's per-script fallback keeps CJK glyphs on one consistent face.
        font = QFont("Segoe UI")
        if not QFontDatabase.hasFamily("Segoe UI"):
            font = QFontDatabase.systemFont(QFontDatabase.GeneralFont)
        font.setPointSizeF(float(font_size))
        try:
            font.setHintingPreference(QFont.HintingPreference.PreferDefaultHinting)
            font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        except AttributeError:
            pass

        self.setFont(font)
        self.setCursorWidth(2)
        self.setLineWrapMode(QPlainTextEdit.WidgetWidth)
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
        family = self.font().family().replace('"', '')
        self.setStyleSheet(
            f"""
            QPlainTextEdit#codeEditor {{
                background: {colors['background']};
                color: {colors['foreground']};
                border: 0;
                padding: 7px 10px;
                selection-background-color: {colors['selection']};
                selection-color: {colors['selection_text']};
                font-family: "{family}";
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

        matches = getattr(self, "_find_matches_cache", ())
        if matches:
            block = self.firstVisibleBlock()
            if block.isValid():
                visible_start = block.position()
                top = self.blockBoundingGeometry(block).translated(
                    self.contentOffset()
                ).top()
                bottom = top + self.blockBoundingRect(block).height()
                visible_end = visible_start
                viewport_bottom = self.viewport().rect().bottom()
                while block.isValid() and top <= viewport_bottom:
                    if block.isVisible():
                        visible_end = block.position() + block.length()
                    block = block.next()
                    top = bottom
                    if block.isValid():
                        bottom = top + self.blockBoundingRect(block).height()

                index = bisect_left(matches, (visible_start, -1))
                highlighted = 0
                while index < len(matches) and matches[index][0] < visible_end:
                    match_start, match_end = matches[index]
                    match_cursor = QTextCursor(self.document())
                    match_cursor.setPosition(match_start)
                    match_cursor.setPosition(match_end, QTextCursor.KeepAnchor)
                    match = QTextEdit.ExtraSelection()
                    match.cursor = match_cursor
                    active_cursor = self.textCursor()
                    is_active = (
                        active_cursor.hasSelection()
                        and active_cursor.selectionStart() == match_start
                        and active_cursor.selectionEnd() == match_end
                    )
                    if is_active:
                        match.format.setBackground(QColor(self.colors["find_active"]))
                        match.format.setForeground(QColor(self.colors["find_text"]))
                    else:
                        match.format.setForeground(QColor(self.colors["foreground"]))
                        match.format.setUnderlineStyle(
                            QTextCharFormat.UnderlineStyle.SingleUnderline
                        )
                        match.format.setUnderlineColor(QColor(self.colors["accent"]))
                    selections.append(match)
                    index += 1
                    highlighted += 1
                    if highlighted >= 500:
                        break
        self.setExtraSelections(selections)


class EditorTabs(QWidget):
    """Multi-tab text editor that auto-saves the original file after typing stops."""

    statusChanged = Signal(str)
    fontSizeChanged = Signal(float)
    documentSaved = Signal(str)
    instances = WeakSet()

    def __init__(self, parent=None, font_size=11.0, appearance="Dark",
                 settings=None, settings_callback=None, status_callback=None,
                 context_path_callback=None, notification_callback=None):
        super().__init__(parent)
        self.instances.add(self)
        self._font_size = float(font_size)
        self.appearance = appearance
        self.colors = editor_colors(appearance)
        settings = settings or AppSettings()
        self.tabs = QTabWidget()
        self.tabs.setObjectName("editorTabs")
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.tabBar().setDrawBase(False)
        self.tabs.tabBar().setExpanding(False)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.export_tab = None
        self.export_tab = TxtExportTab(
            settings, status_callback=status_callback,
            settings_callback=settings_callback, font_size=font_size,
            appearance=appearance, context_path_callback=context_path_callback,
            context_saved_callback=self.apply_external_update,
            notification_callback=notification_callback, parent=self,
        )
        self.tabs.addTab(self.export_tab, TXT_EXPORT_TAB)
        self.tabs.tabBar().setTabButton(0, self.tabs.tabBar().ButtonPosition.LeftSide, None)
        self.tabs.tabBar().setTabButton(0, self.tabs.tabBar().ButtonPosition.RightSide, None)
        self.tabs.tabBar().setTabData(0, "txt-export")
        self._active_editor = None
        self._status_text = "พร้อมใช้งาน  ·  0 คำ  ·  0 อักขระ"
        self.tabs.currentChanged.connect(self._handle_tab_change)
        if self.export_tab is not None:
            self.export_tab.stats_timer.timeout.connect(lambda: self._update_status(0))
            self.export_tab.editor.cursorPositionChanged.connect(lambda: self._update_status(0))
            self.export_tab.editor.textChanged.connect(
                lambda: self._queue_find_matches(self.export_tab.editor)
            )
        self._search_text = ""
        self._find_update_timer = QTimer(self)
        self._find_update_timer.setSingleShot(True)
        self._find_update_timer.setInterval(180)
        self._find_update_timer.timeout.connect(self._update_find_matches)

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
        if editor is None or isinstance(editor, TxtExportTab):
            return False
        return bool(editor.property("documentDirty"))

    def _current_editor(self):
        widget = self.tabs.currentWidget()
        return widget.editor if isinstance(widget, TxtExportTab) else widget

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
        stats_timer = getattr(editor, "stats_timer", None)
        if stats_timer is not None:
            stats_timer.start()

    def _recount_document_stats(self, editor):
        text = editor.toPlainText()
        editor._cached_character_count = len(text)
        editor._cached_word_count = len(text.split())
        if editor is self._current_editor():
            self._update_status(self.tabs.currentIndex())

    def _queue_find_matches(self, editor):
        if editor is self._current_editor() and self.find_input.text():
            self._find_update_timer.start()

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
                current = self._current_editor()
                if current is not None and current is not editor and self._dirty(current):
                    if not self.save_editor(current, quiet=True):
                        return None
                self.tabs.setCurrentIndex(index)
                return editor

        current = self._current_editor()
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
        editor._cached_character_count = len(text)
        editor._cached_word_count = len(text.split())

        editor.autosave_timer = QTimer(editor)
        editor.autosave_timer.setSingleShot(True)
        editor.autosave_timer.setInterval(AUTO_SAVE_DELAY_MS)
        editor.autosave_timer.timeout.connect(
            lambda e=editor: self._autosave_editor(e)
        )
        editor.stats_timer = QTimer(editor)
        editor.stats_timer.setSingleShot(True)
        editor.stats_timer.setInterval(300)
        editor.stats_timer.timeout.connect(
            lambda e=editor: self._recount_document_stats(e)
        )
        editor.textChanged.connect(lambda e=editor: self._on_text_changed(e))
        editor.cursorPositionChanged.connect(
            lambda e=editor: self._update_status(self.tabs.indexOf(e))
        )
        editor.textChanged.connect(lambda e=editor: self._queue_find_matches(e))

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

    def apply_external_update(self, path: str | Path, text: str):
        """Refresh an open file tab after an application action replaced its disk contents."""
        path = Path(path).expanduser().resolve()
        for index in range(self.tabs.count()):
            editor = self.tabs.widget(index)
            existing = self._path(editor)
            if existing is None or existing.resolve() != path:
                continue
            timer = getattr(editor, "autosave_timer", None)
            if timer is not None:
                timer.stop()
            editor.blockSignals(True)
            editor.setPlainText(text)
            editor.blockSignals(False)
            editor._cached_character_count = len(text)
            editor._cached_word_count = len(text.split())
            self._set_dirty(editor, False, "บันทึกแล้ว")
            self.documentSaved.emit(str(path))
            return True
        return False

    def set_font_size(self, size):
        self._font_size = max(8.0, min(28.0, float(size)))
        for index in range(self.tabs.count()):
            self.tabs.widget(index).set_font_size(self._font_size)
        self.fontSizeChanged.emit(self._font_size)

    def font_size(self):
        return self._font_size

    def save_current(self) -> bool:
        if isinstance(self.tabs.currentWidget(), TxtExportTab):
            return False
        editor = self._current_editor()
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
        if editor is self.export_tab:
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

    def _tab_key(self, index: int) -> str | None:
        widget = self.tabs.widget(index)
        if widget is self.export_tab:
            return "txt-export"
        path = self._path(widget)
        return str(path) if path else None

    def tab_order(self) -> list[str]:
        return [
            key for index in range(self.tabs.count())
            if (key := self._tab_key(index)) is not None
        ]

    def active_tab_key(self) -> str | None:
        return self._tab_key(self.tabs.currentIndex())

    def open_paths(self) -> list[str]:
        result = []
        for index in range(self.tabs.count()):
            path = self._path(self.tabs.widget(index))
            if path:
                result.append(str(path))
        return result

    def restore_paths(self, paths, current_index=0, tab_order=None, active_tab_key=None):
        for path in paths or []:
            candidate = Path(path).expanduser()
            if candidate.is_file() and self.supports(candidate):
                self.open_file(candidate)
        if tab_order:
            bar = self.tabs.tabBar()
            current_keys = self.tab_order()
            ordered_keys = [key for key in tab_order if key in current_keys]
            ordered_keys.extend(key for key in current_keys if key not in ordered_keys)
            for target_index, key in enumerate(ordered_keys):
                current_keys = self.tab_order()
                source_index = current_keys.index(key)
                if source_index != target_index:
                    bar.moveTab(source_index, target_index)
        if active_tab_key and active_tab_key in self.tab_order():
            self.tabs.setCurrentIndex(self.tab_order().index(active_tab_key))
        elif self.tabs.count():
            # Keep supporting settings saved before tab order was persisted.
            legacy_index = int(current_index or 0)
            if self.export_tab and self.tabs.indexOf(self.export_tab) == 0:
                legacy_index += 1
            self.tabs.setCurrentIndex(max(0, min(legacy_index, self.tabs.count() - 1)))

    def _update_status(self, index):
        if index < 0:
            self.status.setText("ยังไม่ได้เปิดไฟล์")
            self._status_text = "พร้อมใช้งาน  ·  0 คำ  ·  0 อักขระ"
            self.statusChanged.emit(self._status_text)
            return
        widget = self.tabs.widget(index)
        if isinstance(widget, TxtExportTab):
            words, characters = widget._cached_word_count, widget._cached_character_count
            cursor = widget.editor.textCursor()
            selected = cursor.selectionEnd() - cursor.selectionStart()
            suffix = f"  ·  เลือก {selected:,} อักขระ" if selected else ""
            self._status_text = f"พร้อมใช้งาน  ·  {words:,} คำ  ·  {characters:,} อักขระ{suffix}  ·  TXT Export"
            self.statusChanged.emit(self._status_text)
            return
        editor = widget
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
        words = getattr(editor, "_cached_word_count", 0)
        characters = getattr(editor, "_cached_character_count", 0)
        selection_size = cursor.selectionEnd() - cursor.selectionStart()
        selection_status = (
            f"  ·  เลือก {selection_size:,} อักขระ" if selection_size else ""
        )
        self._status_text = (
            f"{state}  ·  {words:,} คำ  ·  {characters:,} อักขระ{selection_status}  ·  "
            f"Ln {cursor.blockNumber()+1}, Col {cursor.positionInBlock()+1}  ·  UTF-8 {suffix}"
        )
        self.statusChanged.emit(self._status_text)
        self._update_find_counter(editor, cursor)

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
                border-radius: 0;
                padding: 10px 15px; min-width: 92px; min-height: 32px;
            }}
            QTabWidget#editorTabs QTabBar::tab:disabled {{
                color: {colors['disabled_text']}; background: {colors['tab']};
            }}
            QTabWidget#editorTabs QTabBar::tab:hover {{
                background: {colors['current_line']}; color: {colors['foreground']};
            }}
            QTabWidget#editorTabs QTabBar::tab:selected {{
                background: {colors['tab_selected']}; color: {colors['foreground']};
                border-top: 2px solid {colors['accent']}; font-weight: 600;
            }}
            QTabWidget#editorTabs QTabBar::tab:focus {{
                border-bottom: 3px solid {colors['focus']};
            }}
            QFrame#editorFindPanel {{
                background: {colors['background']}; color: {colors['foreground']};
                border: 0; border-radius: 0;
            }}
            QFrame#editorFindPanel QLineEdit {{
                background: {colors['background']}; color: {colors['foreground']};
                border: 1px solid {colors['border']}; border-radius: 0;
                padding: 5px 8px; min-height: 22px;
            }}
            QFrame#editorFindPanel QPushButton {{
                background: {colors['current_line']}; color: {colors['foreground']};
                border: 1px solid {colors['border']}; border-radius: 0;
                padding: 6px 10px; min-height: 30px;
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
        editor = self._current_editor()
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
            editor = self._current_editor()
            if editor:
                editor.setFocus(Qt.ShortcutFocusReason)
                editor.highlight_current_line()

    def _update_find_matches(self, *_args):
        editor = self._current_editor()
        query = self.find_input.text() if hasattr(self, "find_input") else ""
        if editor is None:
            if hasattr(self, "find_count"):
                self.find_count.setText("0/0")
            return
        editor._find_query = query
        matches = self._find_matches(editor, query)
        editor._find_matches_cache = matches
        editor.highlight_current_line()
        self._update_find_counter(editor, editor.textCursor())

    def _update_find_counter(self, editor, cursor):
        matches = getattr(editor, "_find_matches_cache", [])
        current = 0
        if cursor.hasSelection() and matches:
            selection = (cursor.selectionStart(), cursor.selectionEnd())
            index = bisect_left(matches, selection)
            if index < len(matches) and matches[index] == selection:
                current = index + 1
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
        if self.find_input.text():
            self._find_next()
        else:
            self._update_find_matches()

    def _find_next(self, backward=False):
        editor = self._current_editor()
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
        editor = self._current_editor()
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
        editor = self._current_editor()
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
