"""Compact, lazy translation batch page inside the existing novel workspace."""
from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from .translation_batches import (
    find_translation_groups, load_translation_source, translation_groups,
    validate_translation_source,
)
from .translation_batch_clipboard import copy_translation_batch
from .translation_source_binding import (
    enabled_translation_attachments, source_candidates, translation_reference_files,
)
from .vocabulary_batches import split_missing_numbers


class TranslationBatchPage(QWidget):
    """No stage advancement, progress mutation, export or Polish History writes."""

    def __init__(self, repo, profile_reader, assembler, state, on_change, on_close, parent=None):
        super().__init__(parent)
        self.repo, self.profile_reader, self.assembler = repo, profile_reader, assembler
        self.state = dict(state or {})
        self.on_change, self.on_close = on_change, on_close
        self._source = None
        self._groups = ()
        self._rendered = 0
        self._visible = ()
        self._busy = False
        self.setObjectName("translationBatchPage")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 8, 12, 8)
        heading = QHBoxLayout()
        heading.addWidget(QLabel("แปลหลายบท"), 1)
        back = QPushButton("กลับไป Workspace")
        back.setObjectName("translationBatchBack")
        back.clicked.connect(on_close)
        heading.addWidget(back)
        outer.addLayout(heading)

        sources = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.setObjectName("translationBatchSourceMode")
        self.mode.addItem("วางเนื้อหาเอง", "paste")
        self.mode.addItem("ไฟล์ต้นฉบับรวม", "file")
        self.mode.addItem("โฟลเดอร์ TXT", "folder")
        self.mode.addItem("ใช้ต้นฉบับจากขั้นตอนแปล", "step")
        current_mode = self.state.get("mode", "paste")
        self.mode.setCurrentIndex(max(0, self.mode.findData(current_mode)))
        self.mode.currentIndexChanged.connect(self._mode_changed)
        sources.addWidget(self.mode)
        self.source_picker = QComboBox()
        self.source_picker.setObjectName("translationBatchStepSource")
        self.source_picker.currentIndexChanged.connect(self._step_selected)
        sources.addWidget(self.source_picker, 1)
        browse = QPushButton("เลือกไฟล์ / โฟลเดอร์")
        browse.setObjectName("translationBatchBrowse")
        browse.clicked.connect(self._browse)
        sources.addWidget(browse)
        self.browse = browse
        outer.addLayout(sources)

        self.path_label = QLabel("")
        self.path_label.setObjectName("mutedLabel")
        outer.addWidget(self.path_label)
        self.pasted_text = QPlainTextEdit()
        self.pasted_text.setObjectName("translationBatchDraft")
        self.pasted_text.setPlaceholderText("วางต้นฉบับจีนหลายบท เช่น 第一章 ...")
        self.pasted_text.setPlainText(self.state.get("draft", ""))
        self.pasted_text.textChanged.connect(self._draft_changed)
        outer.addWidget(self.pasted_text, 1)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("บทต่อชุด"))
        self.size = QSpinBox()
        self.size.setObjectName("translationBatchSize")
        self.size.setRange(1, 100)
        self.size.setValue(max(1, min(100, int(self.state.get("size", 5)))))
        self.size.valueChanged.connect(self._size_changed)
        controls.addWidget(self.size)
        controls.addWidget(QLabel("คัดลอก"))
        self.copy_mode = QComboBox()
        self.copy_mode.setObjectName("translationBatchCopyMode")
        self.copy_mode.addItem("ไฟล์ปกติ", False)
        self.copy_mode.addItem("ZIP", True)
        self.copy_mode.setCurrentIndex(1 if self.state.get("zip", False) else 0)
        self.copy_mode.currentIndexChanged.connect(self._copy_mode_changed)
        controls.addWidget(self.copy_mode)
        controls.addWidget(QLabel("ค้นหาช่วงบท"))
        self.search = QLineEdit()
        self.search.setObjectName("translationBatchSearch")
        self.search.setPlaceholderText("6-10 หรือ 603")
        self.search.textChanged.connect(self._refresh_rows)
        controls.addWidget(self.search, 1)
        refresh = QPushButton("ตรวจต้นฉบับ / รีเฟรช")
        refresh.setObjectName("translationBatchRefresh")
        refresh.clicked.connect(self.refresh)
        controls.addWidget(refresh)
        outer.addLayout(controls)

        self.summary = QLabel("เลือกต้นฉบับแล้วกดตรวจต้นฉบับ")
        self.summary.setObjectName("mutedLabel")
        outer.addWidget(self.summary)
        self.scroll = QScrollArea()
        self.scroll.setObjectName("translationBatchScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.rows_host = QWidget()
        self.rows = QVBoxLayout(self.rows_host)
        self.rows.setContentsMargins(0, 0, 4, 0)
        self.rows.setSpacing(2)
        self.scroll.setWidget(self.rows_host)
        self.scroll.verticalScrollBar().valueChanged.connect(self._on_scroll)
        outer.addWidget(self.scroll, 4)
        self._mode_changed()
        if current_mode != "paste" and self.state.get("path"):
            self.refresh()
        elif current_mode == "paste" and self.pasted_text.toPlainText().strip():
            self.refresh()

    def _persist(self):
        self.on_change(dict(self.state))

    def _profile(self):
        profile = self.profile_reader()
        if profile is None:
            raise ValueError("ไม่พบนิยายปัจจุบัน")
        return profile

    def _mode_changed(self, *_):
        mode = self.mode.currentData()
        self.state["mode"] = mode
        is_paste = mode == "paste"
        self.pasted_text.setVisible(is_paste)
        self.source_picker.setVisible(mode == "step")
        self.browse.setVisible(mode in ("file", "folder"))
        self._populate_sources() if mode == "step" else None
        self.path_label.setText(self.state.get("path", "") if not is_paste else "Draft เฉพาะนิยายเรื่องนี้")
        self._source = None
        self._groups = ()
        self._clear_rows()
        self._persist()

    def _populate_sources(self):
        current = self.state.get("attachment_id", "")
        self.source_picker.blockSignals(True)
        self.source_picker.clear()
        self.source_picker.addItem("เลือกต้นฉบับจากขั้นตอนแปล…", "")
        try:
            entries = source_candidates(enabled_translation_attachments(
                self.repo, self.assembler, self._profile()))
            for entry in entries:
                self.source_picker.addItem(entry.label, entry.id)
        except ValueError as exc:
            self.summary.setText(str(exc))
        index = self.source_picker.findData(current)
        self.source_picker.setCurrentIndex(index if index >= 0 else 0)
        self.source_picker.blockSignals(False)

    def _step_selected(self, *_):
        if self.mode.currentData() == "step":
            self.state["attachment_id"] = self.source_picker.currentData() or ""
            self._source = None
            self._groups = ()
            self._clear_rows()
            self._persist()

    def _browse(self):
        mode = self.mode.currentData()
        if mode == "folder":
            path = QFileDialog.getExistingDirectory(self, "เลือกโฟลเดอร์ต้นฉบับ", self.state.get("path", ""))
        else:
            path, _ = QFileDialog.getOpenFileName(
                self, "เลือกต้นฉบับ TXT", self.state.get("path", ""), "Text files (*.txt)")
        if path:
            self.state["path"] = path
            self.path_label.setText(path)
            self._persist()
            self.refresh()

    def _draft_changed(self):
        self.state["draft"] = self.pasted_text.toPlainText()
        self._source = None
        self._groups = ()
        self._clear_rows()
        self._persist()

    def _size_changed(self, *_):
        self.state["size"] = self.size.value()
        self._persist()
        if self._source:
            self._groups = translation_groups(self._source, self.size.value())
            self._refresh_rows()

    def _copy_mode_changed(self, *_):
        self.state["zip"] = bool(self.copy_mode.currentData())
        self._persist()

    def _step_path(self):
        entries = enabled_translation_attachments(self.repo, self.assembler, self._profile())
        chosen = next((entry for entry in entries if entry.id == self.state.get("attachment_id")), None)
        if chosen is None or chosen.path is None:
            raise ValueError("ต้นฉบับที่เลือกไม่พร้อมใช้งาน กรุณาเลือกไฟล์ในขั้นตอนแปลอีกครั้ง")
        return chosen.path

    def refresh(self):
        try:
            mode = self.mode.currentData()
            path = self._step_path() if mode == "step" else self.state.get("path")
            source = load_translation_source(mode, path=path, text=self.pasted_text.toPlainText())
            self._source = source
            self._groups = translation_groups(source, self.size.value())
            missing = split_missing_numbers(tuple(
                type("Segment", (), {"number": chapter.number}) for chapter in source.chapters))
            self.summary.setText(
                f"พบ {len(source.chapters)} บท · {len(self._groups)} ชุด"
                + (f" · ขาดบท {', '.join(map(str, missing[:20]))}" if missing else "")
            )
            self._refresh_rows()
        except (OSError, ValueError, UnicodeError) as exc:
            self._source = None
            self._groups = ()
            self._clear_rows()
            self.summary.setText(str(exc))

    def _clear_rows(self):
        while self.rows.count():
            item = self.rows.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._rendered = 0

    def _refresh_rows(self, *_):
        old = self.scroll.verticalScrollBar().value()
        self._visible = find_translation_groups(self._groups, self.search.text())
        self._clear_rows()
        self._append_rows()
        self.scroll.verticalScrollBar().setValue(old)

    def _append_rows(self, limit=35):
        if self._busy:
            return
        self._busy = True
        try:
            end = min(len(self._visible), self._rendered + limit)
            for group in self._visible[self._rendered:end]:
                row = QFrame()
                layout = QHBoxLayout(row)
                layout.setContentsMargins(5, 4, 5, 4)
                layout.addWidget(QLabel(str(group.index)))
                layout.addWidget(QLabel(f"บท {group.start}–{group.end}"), 1)
                description = f"{len(group.chapters)} บท · {len(group.chapters)} ไฟล์"
                if group.missing:
                    description += " · ขาด " + ", ".join(map(str, group.missing[:8]))
                layout.addWidget(QLabel(description))
                details = QPushButton("รายละเอียด")
                details.setCheckable(True)
                layout.addWidget(details)
                button = QPushButton("คัดลอก ZIP" if self.copy_mode.currentData() else "คัดลอก")
                button.setObjectName(f"translationBatchCopy{group.index}")
                button.clicked.connect(lambda _checked=False, g=group: self.copy_group(g))
                layout.addWidget(button)
                self.rows.addWidget(row)
                filenames = QLabel(", ".join(c.path.name for c in group.chapters))
                filenames.setWordWrap(True)
                filenames.setVisible(False)
                details.toggled.connect(filenames.setVisible)
                self.rows.addWidget(filenames)
            self._rendered = end
        finally:
            self._busy = False

    def _on_scroll(self, position):
        bar = self.scroll.verticalScrollBar()
        if bar.maximum() and position >= bar.maximum() - max(70, bar.pageStep() // 2):
            self._append_rows()

    def copy_group(self, group):
        if not self._source:
            return
        if group.missing:
            result = QMessageBox.question(
                self, "บทไม่ครบ",
                "ขาดบท " + ", ".join(map(str, group.missing))
                + "\nคัดลอกเฉพาะบทที่มีอยู่หรือไม่?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if result != QMessageBox.Yes:
                return
        try:
            profile = self._profile()
            entries = enabled_translation_attachments(self.repo, self.assembler, profile)
            chosen = self._step_path() if self.mode.currentData() == "step" else (
                self.state.get("path") if self.mode.currentData() != "paste" else None)
            references = translation_reference_files(
                entries, chosen, self.state.get("attachment_id") if self.mode.currentData() == "step" else None)
            copied = copy_translation_batch(
                self._source, group, references,
                self.repo.root / "cache" / "clipboard" / "translation" / profile.id,
                as_zip=bool(self.copy_mode.currentData()),
                pasted_text=self.pasted_text.toPlainText() if self.mode.currentData() == "paste" else None)
            self.state["last_range"] = f"{group.start}-{group.end}"
            self._persist()
            self.summary.setText(f"คัดลอกบท {group.start}–{group.end} สำเร็จ · {len(copied)} ไฟล์ใน Clipboard")
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "คัดลอกไม่สำเร็จ", str(exc))
