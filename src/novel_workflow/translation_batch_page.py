"""Compact, lazy translation batch page inside the existing novel workspace."""
from __future__ import annotations

import tempfile
import hashlib
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from .translation_batches import (
    chapters_for_group, find_translation_groups, load_translation_source, translation_groups,
    validate_translation_source,
)
from .translation_batch_clipboard import prepare_translation_batch
from .clipboard_files import copy_file_paths
from .translation_source_binding import (
    enabled_translation_attachments, source_candidates, translation_reference_files,
)
from .vocabulary_batches import split_missing_numbers
from .batch_copy_history import (
    group_copy_status, load_history, record_copy, source_identity, source_revision,
)
from .workflow_archive import file_digest



class TranslationSourceWorker(QThread):
    loaded = Signal(object)
    failed = Signal(str)

    def __init__(self, mode, path, text):
        super().__init__()
        self.mode, self.path, self.text = mode, path, text

    def run(self):
        try:
            self.loaded.emit(load_translation_source(self.mode, path=self.path, text=self.text))
        except (OSError, ValueError, UnicodeError) as exc:
            self.failed.emit(str(exc))


class TranslationCopyWorker(QThread):
    prepared = Signal(object)
    failed = Signal(str)

    def __init__(self, source, group, repo, assembler, profile, source_path,
                 source_id, cache_path, *, as_zip, pasted_text):
        super().__init__()
        self.source, self.group = source, group
        self.repo, self.assembler, self.profile = repo, assembler, profile
        self.source_path, self.source_id = source_path, source_id
        self.cache_path, self.as_zip, self.pasted_text = cache_path, as_zip, pasted_text

    def run(self):
        try:
            # Resolving reference folders can traverse thousands of files.
            # Both resolution and bundle preparation stay off the GUI thread.
            entries = enabled_translation_attachments(
                self.repo, self.assembler, self.profile)
            selected_path = self.source_path
            if self.source_id:
                chosen = next((item for item in entries if item.id == self.source_id), None)
                if chosen is None or chosen.path is None:
                    raise ValueError("ต้นฉบับจากขั้นตอนแปลไม่พร้อมใช้งาน")
                selected_path = chosen.path
            references = translation_reference_files(
                entries, selected_path, self.source_id)
            self.prepared.emit(prepare_translation_batch(
                self.source, self.group, references, self.cache_path,
                as_zip=self.as_zip, pasted_text=self.pasted_text))
        except (OSError, ValueError, UnicodeError) as exc:
            self.failed.emit(str(exc))


class TranslationBatchPage(QWidget):
    """No stage advancement, progress mutation, export or Polish History writes."""

    def __init__(self, repo, profile_reader, assembler, state, on_change, on_close, parent=None):
        super().__init__(parent)
        self.repo, self.profile_reader, self.assembler = repo, profile_reader, assembler
        self.state = dict(state or {})
        profile = profile_reader()
        self.profile_id = getattr(profile, "id", None)
        if self.profile_id:
            try:
                self.state["draft"] = repo.load_batch_draft(self.profile_id, "translation") or self.state.get("draft", "")
            except (OSError, ValueError, TypeError):
                pass
        self._history = load_history(repo, self.profile_id, "translation") if self.profile_id else []
        self._source_identity = ""
        self._source_revision = ""
        self._draft_timer = QTimer(self)
        self._draft_timer.setSingleShot(True)
        self._draft_timer.setInterval(350)
        self._draft_timer.timeout.connect(self._flush_draft)
        self.on_change, self.on_close = on_change, on_close
        self._source = None
        self._groups = ()
        self._rendered = 0
        self._visible = ()
        self._busy = False
        self._load_worker = None
        self._load_queued = False
        self._copy_worker = None
        self._copy_pending = None
        self._initialized = False
        self.setObjectName("translationBatchPage")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 8, 12, 8)
        heading = QHBoxLayout()
        title = QLabel("แปลหลายบท · เลือกชุดแล้วคัดลอก")
        title.setObjectName("sectionHeading")
        heading.addWidget(title, 1)
        # Both modes keep the existing batch services and source handling.
        vocabulary = QPushButton("จัดชุดคำศัพท์")
        vocabulary.setObjectName("vocabularyBatchMode")
        vocabulary.clicked.connect(
            lambda checked=False: (
                parent.owner.open_txt_vocabulary(parent.profile_id)
                if parent is not None and hasattr(parent, "owner") else None
            )
        )
        heading.addWidget(vocabulary)
        back = QPushButton("กลับไปแปลนิยาย")
        back.setObjectName("translationBatchBack")
        back.clicked.connect(on_close)
        heading.addWidget(back)
        outer.addLayout(heading)
        helper = QLabel("1  เลือกต้นฉบับ     →     2  กำหนดบทต่อชุด     →     3  กดคัดลอกชุดที่ต้องการ")
        helper.setObjectName("mutedLabel")
        outer.addWidget(helper)

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
        self.path_label.setTextFormat(Qt.PlainText)
        self.path_label.setWordWrap(True)
        self.path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
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
        self.search.setText(str(self.state.get("search", "")))
        self.search.textChanged.connect(self._refresh_rows)
        self.search.textChanged.connect(lambda value: self._state_changed(search=value))
        controls.addWidget(self.search, 1)
        refresh = QPushButton("ตรวจต้นฉบับ / รีเฟรช")
        refresh.setObjectName("translationBatchRefresh")
        refresh.clicked.connect(self.refresh)
        controls.addWidget(refresh)
        outer.addLayout(controls)

        self.summary = QLabel("กำลังเตรียมรายการบท…")
        self.summary.setObjectName("mutedLabel")
        self.summary.setTextFormat(Qt.PlainText)
        self.summary.setWordWrap(True)
        self.summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        outer.addWidget(self.summary)
        resume_row = QHBoxLayout()
        resume_row.addWidget(QLabel("แสดง"))
        self.history_filter = QComboBox()
        self.history_filter.setObjectName("translationBatchHistoryFilter")
        self.history_filter.addItem("ทั้งหมด", "all")
        self.history_filter.addItem("ยังไม่ได้คัดลอก", "new")
        self.history_filter.addItem("คัดลอกแล้ว", "copied")
        self.history_filter.addItem("ต้องตรวจใหม่", "review")
        filter_index = self.history_filter.findData(self.state.get("filter", "all"))
        self.history_filter.setCurrentIndex(max(0, filter_index))
        self.history_filter.currentIndexChanged.connect(self._filter_changed)
        resume_row.addWidget(self.history_filter)
        self.last_button = QPushButton("กลับไปชุดล่าสุด")
        self.last_button.setObjectName("translationBatchLastCopied")
        self.last_button.clicked.connect(self._go_to_last_copied)
        resume_row.addWidget(self.last_button)
        self.next_button = QPushButton("ไปชุดถัดไป")
        self.next_button.setObjectName("translationBatchNextUncopied")
        self.next_button.clicked.connect(self._go_to_next_uncopied)
        resume_row.addWidget(self.next_button)
        resume_row.addStretch(1)
        outer.addLayout(resume_row)
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
        self.scroll.verticalScrollBar().valueChanged.connect(lambda value: self._state_changed(scroll=int(value)))
        outer.addWidget(self.scroll, 4)
        self._mode_changed()
        self._initialized = True
        if current_mode in ("folder", "file") and self.state.get("path"):
            self.refresh()
        elif current_mode == "step" and self.state.get("attachment_id"):
            self.refresh()
        elif current_mode == "paste" and self.pasted_text.toPlainText().strip():
            self.refresh()

    def _persist(self):
        saved = dict(self.state)
        saved.pop("draft", None)
        self.on_change(saved)

    def _state_changed(self, **values):
        self.state.update(values)
        if getattr(self, "_initialized", False):
            self._persist()

    def _flush_draft(self):
        if self.profile_id:
            self.repo.save_batch_draft(self.profile_id, "translation", self.state.get("draft", ""))

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
        self.path_label.setText(
            "Draft เฉพาะนิยายเรื่องนี้" if is_paste
            else self.state.get("path", "") if mode in ("file", "folder") else ""
        )
        self._source = None
        self._groups = ()
        self._clear_rows()
        self._persist()
        if self._initialized and (mode == "step" or mode == "paste" and self.pasted_text.toPlainText().strip() or mode in ("file", "folder") and self.state.get("path")):
            self.refresh()

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
            if self.state["attachment_id"]:
                self.refresh()

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
        if self._load_worker is not None and self._load_worker.isRunning():
            self._load_queued = True
        self._draft_timer.start()
        self._persist()

    def _size_changed(self, *_):
        self.state["size"] = self.size.value()
        sel