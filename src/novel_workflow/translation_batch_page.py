"""Compact, lazy translation batch page inside the existing novel workspace."""
from __future__ import annotations

import tempfile
import hashlib
import os
import time
from threading import Lock
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget,
    QGridLayout, QSizePolicy, QApplication,
)

from .translation_batches import (
    chapters_for_group, find_translation_groups, load_translation_source, translation_groups,
    validate_translation_source,
)
from .translation_clipboard_cache import (
    prepare_cached_bundle, pin_clipboard_bundle, cleanup_translation_cache,
)
from .clipboard_files import copy_file_paths
from .translation_source_binding import (
    enabled_translation_attachments, source_candidates, translation_reference_files,
)
from .vocabulary_batches import split_missing_numbers
from .batch_copy_history import (
    index_group_copy_status, load_history, record_copy, source_identity, source_revision,
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


class TranslationPrewarmWorker(QThread):
    """One bounded prioritized background producer; Qt Clipboard stays on GUI."""
    prepared = Signal(object, object)
    failed = Signal(object, str)

    def __init__(self, source, repo, assembler, profile, source_path, source_id,
                 cache_path, *, identity, revision, batch_size, as_zip, pasted_text):
        super().__init__()
        self.source, self.repo, self.assembler, self.profile = source, repo, assembler, profile
        self.source_path, self.source_id = source_path, source_id
        self.cache_path, self.identity, self.revision = cache_path, identity, revision
        self.batch_size, self.as_zip, self.pasted_text = batch_size, as_zip, pasted_text
        self._lock = Lock()
        self._queue = []
        self._active = None
        self._cancelled = False

    def request(self, group, *, priority=False):
        with self._lock:
            if self._cancelled:
                return
            if self._active is not None and self._active.index == group.index:
                return
            self._queue = [g for g in self._queue if g.index != group.index]
            self._queue.insert(0, group) if priority else self._queue.append(group)
            del self._queue[4:]

    def cancel(self):
        with self._lock:
            self._cancelled = True
            self._queue.clear()

    def pending_indices(self):
        with self._lock:
            return {g.index for g in self._queue} | (
                {self._active.index} if self._active is not None else set())

    def run(self):
        try:
            entries = enabled_translation_attachments(self.repo, self.assembler, self.profile)
            selected_path = self.source_path
            if self.source_id:
                chosen = next((e for e in entries if e.id == self.source_id), None)
                if chosen is None or chosen.path is None:
                    raise ValueError("ต้นฉบับจากขั้นตอนแปลไม่พร้อมใช้งาน")
                selected_path = chosen.path
            references = translation_reference_files(entries, selected_path, self.source_id)
        except (OSError, ValueError, UnicodeError, TypeError) as exc:
            with self._lock:
                tasks = tuple(self._queue)
                self._queue.clear()
            for group in tasks:
                self.failed.emit(group, str(exc))
            return
        processed = 0
        while True:
            with self._lock:
                if self._cancelled or not self._queue:
                    self._active = None
                    break
                group = self._queue.pop(0)
                self._active = group
            try:
                bundle = prepare_cached_bundle(
                    self.source, group, references, self.cache_path,
                    identity=self.identity, revision=self.revision,
                    batch_size=self.batch_size, as_zip=self.as_zip,
                    pasted_text=self.pasted_text,
                )
                self.prepared.emit(group, bundle)
            except (OSError, ValueError, UnicodeError, TypeError, KeyError) as exc:
                self.failed.emit(group, str(exc))
            processed += 1
        if processed >= 4:
            try:
                cleanup_translation_cache(self.cache_path)
            except (OSError, ValueError):
                pass


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
        self._row_widgets = {}
        self._busy = False
        self._load_worker = None
        self._load_queued = False
        self._copy_worker = None
        self._copy_pending = None
        self._retired_workers = []
        self._ready_bundles = {}
        self._cache_errors = {}
        self._history_statuses = {}
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
        self.configuration_toggle = QPushButton("ตั้งค่าต้นฉบับ ▾")
        self.configuration_toggle.setObjectName("translationBatchConfigurationToggle")
        self.configuration_toggle.setCheckable(True)
        self.configuration_toggle.setChecked(bool(self.state.get("configuration_expanded", False)))
        outer.addWidget(self.configuration_toggle)
        self.configuration_panel = QWidget()
        configuration_layout = QVBoxLayout(self.configuration_panel)
        configuration_layout.setContentsMargins(0, 0, 0, 0)
        configuration_layout.setSpacing(5)

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
        configuration_layout.addLayout(sources)

        self.path_label = QLabel("")
        self.path_label.setObjectName("mutedLabel")
        self.path_label.setTextFormat(Qt.PlainText)
        self.path_label.setWordWrap(True)
        self.path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        configuration_layout.addWidget(self.path_label)
        self.pasted_text = QPlainTextEdit()
        self.pasted_text.setObjectName("translationBatchDraft")
        self.pasted_text.setPlaceholderText("วางต้นฉบับจีนหลายบท เช่น 第一章 ...")
        self.pasted_text.setPlainText(self.state.get("draft", ""))
        self.pasted_text.textChanged.connect(self._draft_changed)
        configuration_layout.addWidget(self.pasted_text)
        self.pasted_text.setMinimumHeight(160)
        self.pasted_text.setMaximumHeight(260)

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
        configuration_layout.addLayout(controls)
        self.configuration_toggle.toggled.connect(self._toggle_configuration)
        outer.addWidget(self.configuration_panel)
        self.configuration_panel.setVisible(self.configuration_toggle.isChecked())

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("ค้นหาช่วงบท"))
        self.search = QLineEdit()
        self.search.setObjectName("translationBatchSearch")
        self.search.setPlaceholderText("6-10 หรือ 603")
        self.search.setText(str(self.state.get("search", "")))
        self.search.textChanged.connect(self._refresh_rows)
        self.search.textChanged.connect(lambda value: self._state_changed(search=value))
        toolbar.addWidget(self.search, 1)
        refresh = QPushButton("ตรวจต้นฉบับ / รีเฟรช")
        refresh.setObjectName("translationBatchRefresh")
        refresh.clicked.connect(self.refresh)
        toolbar.addWidget(refresh)

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
        toolbar.addLayout(resume_row)
        outer.addLayout(toolbar)
        self.columns = QWidget()
        column_layout = QGridLayout(self.columns)
        column_layout.setContentsMargins(7, 3, 7, 3)
        column_layout.setHorizontalSpacing(8)
        for col, label in enumerate(("ชุด", "ช่วงบท", "จำนวนบท", "สถานะ", "รายละเอียด", "การทำงาน")):
            column_layout.addWidget(QLabel(label), 0, col)
        column_layout.setColumnStretch(1, 2)
        column_layout.setColumnStretch(3, 2)
        outer.addWidget(self.columns)
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

    def _toggle_configuration(self, expanded):
        self.configuration_panel.setVisible(bool(expanded))
        self.configuration_toggle.setText("ซ่อนตั้งค่าต้นฉบับ ▴" if expanded else "ตั้งค่าต้นฉบับ ▾")
        self._state_changed(configuration_expanded=bool(expanded))

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
        self._invalidate_prepared()
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
            self._invalidate_prepared()
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
        self._invalidate_prepared()
        self._source = None
        self._groups = ()
        self._clear_rows()
        if self._load_worker is not None and self._load_worker.isRunning():
            self._load_queued = True
        self._draft_timer.start()
        self._persist()

    def _size_changed(self, *_):
        self.state["size"] = self.size.value()
        self._persist()
        if self._source:
            self._invalidate_prepared()
            self._groups = translation_groups(self._source, self.size.value())
            self._reindex_history()
            self._refresh_rows()
            self._schedule_prewarm()

    def _copy_mode_changed(self, *_):
        self.state["zip"] = bool(self.copy_mode.currentData())
        self._persist()
        if self._source:
            self._invalidate_prepared()
            self._refresh_rows()
            self._schedule_prewarm()

    def _step_path(self):
        entries = enabled_translation_attachments(self.repo, self.assembler, self._profile())
        chosen = next((entry for entry in entries if entry.id == self.state.get("attachment_id")), None)
        if chosen is None or chosen.path is None:
            raise ValueError("ต้นฉบับที่เลือกไม่พร้อมใช้งาน กรุณาเลือกไฟล์ในขั้นตอนแปลอีกครั้ง")
        return chosen.path

    def refresh(self):
        """Keep disk scanning and source fingerprints off the Qt GUI thread."""
        if self._load_worker is not None and self._load_worker.isRunning():
            self._load_queued = True
            self.summary.setText("กำลังรอการตรวจต้นฉบับรอบใหม่…")
            return
        mode = self.mode.currentData()
        try:
            path = self._step_path() if mode == "step" else self.state.get("path")
        except (OSError, ValueError) as exc:
            self.summary.setText(str(exc))
            return
        text = self.pasted_text.toPlainText() if mode == "paste" else None
        if mode != "paste" and path:
            self.path_label.setText(f"ต้นฉบับที่ตรวจ: {path}")
            self.path_label.setToolTip(str(path))
        else:
            self.path_label.setToolTip("")
        self.summary.setText("กำลังตรวจต้นฉบับ…")
        self._invalidate_prepared()
        self._source = None
        self._groups = ()
        self._clear_rows()
        worker = TranslationSourceWorker(mode, path, text)
        self._load_worker = worker
        worker.loaded.connect(self._loaded_source)
        worker.failed.connect(self._source_failed)
        worker.finished.connect(self._load_finished)
        worker.start()

    def _loaded_source(self, source):
        worker = self._load_worker
        if worker is None or self._load_queued or self.mode.currentData() != worker.mode:
            return
        if worker.mode == "paste" and self.pasted_text.toPlainText() != worker.text:
            return
        if worker.mode in ("folder", "file") and self.state.get("path") != worker.path:
            return
        self._source = source
        self._groups = translation_groups(source, self.size.value())
        path = self._step_path() if worker.mode == "step" else self.state.get("path")
        self._source_identity = source_identity(
            worker.mode, path,
            self.state.get("attachment_id") if worker.mode == "step" else self.profile_id if worker.mode == "paste" else None,
        )
        manifest = [(str(path.resolve()), digest.hex()) for path, digest in source.signatures]
        manifest.extend((chapter.number, chapter.filename,
                         hashlib.sha256(chapter.content).hexdigest()
                         if chapter.content is not None else "") for chapter in source.chapters)
        self._source_revision = source_revision(manifest)
        if self.profile_id:
            self._history = load_history(self.repo, self.profile_id, "translation")
        self._reindex_history()
        missing = split_missing_numbers(tuple(
            type("Segment", (), {"number": chapter.number}) for chapter in source.chapters))
        counts = self._history_summary()
        self.summary.setText(
            f"พร้อมคัดลอก · {len(source.chapters)} บท · {len(self._groups)} ชุด · "
            f"คัดลอกแล้ว {counts['copied']} ชุด · ยังไม่ได้ {counts['remaining']} ชุด"
            + (f" · ต้องตรวจใหม่ {counts['review']} ชุด" if counts['review'] else "")
            + (f" · ขาดบท {', '.join(map(str, missing[:20]))}" if missing else ""))
        self._refresh_rows()
        self._schedule_prewarm()
        saved_scroll = int(self.state.get("scroll", 0) or 0)
        if saved_scroll:
            QTimer.singleShot(0, lambda value=saved_scroll: self._restore_scroll(value))

    def _source_failed(self, reason):
        if not self._load_queued:
            self._source = None
            self._groups = ()
            self._clear_rows()
            self.summary.setText("ตรวจต้นฉบับไม่สำเร็จ:\n" + reason)

    def _load_finished(self):
        worker = self._load_worker
        self._load_worker = None
        if worker is not None:
            worker.deleteLater()
        if self._load_queued:
            self._load_queued = False
            self.refresh()

    def _clear_rows(self):
        self._row_widgets.clear()
        while self.rows.count():
            item = self.rows.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._rendered = 0

    def _refresh_rows(self, *_):
        old = self.scroll.verticalScrollBar().value()
        previous_count = self._rendered
        candidates = find_translation_groups(self._groups, self.search.text())
        selected_filter = self.history_filter.currentData() if hasattr(self, "history_filter") else "all"
        self._visible = tuple(group for group in candidates if selected_filter == "all"
                              or self._group_status(group) == selected_filter)
        self._clear_rows()
        # Recreate enough rows to represent the previous offset before restoring.
        self._append_rows(limit=max(35, previous_count))
        self._restore_scroll(old)

    def _next_actionable_group(self):
        """First not-yet-copied or stale group in chapter order."""
        return next((g for g in self._groups if self._group_status(g) != "copied"), None)

    def _reindex_history(self):
        self._history_statuses = index_group_copy_status(
            self._history, identity=self._source_identity,
            revision=self._source_revision, groups=self._groups)

    def _invalidate_prepared(self):
        self._ready_bundles.clear()
        self._cache_errors.clear()
        worker = self._copy_worker
        if worker is not None:
            worker.cancel()
            if worker.isRunning():
                self._retired_workers.append(worker)
            else:
                worker.deleteLater()
            self._copy_worker = None
        self._copy_pending = None

    def _schedule_prewarm(self, focus=None):
        if not self._source or not self._groups:
            return
        worker = self._copy_worker
        if worker is None or not worker.isRunning():
            profile = deepcopy(self._profile())
            mode = self.mode.currentData()
            worker = TranslationPrewarmWorker(
                self._source, self.repo, self.assembler, profile,
                self.state.get("path") if mode in ("folder", "file") else None,
                self.state.get("attachment_id") if mode == "step" else None,
                self.repo.root / "cache" / "clipboard" / "translation" / profile.id,
                identity=self._source_identity, revision=self._source_revision,
                batch_size=self.size.value(), as_zip=bool(self.copy_mode.currentData()),
                pasted_text=self.state.get("draft") if mode == "paste" else None,
            )
            worker.prepared.connect(self._prewarm_ready)
            worker.failed.connect(self._prewarm_failed)
            worker.finished.connect(lambda w=worker: self._prewarm_finished(w))
            self._copy_worker = worker
            start_worker = True
        else:
            start_worker = False
        if focus is not None and focus.index not in self._ready_bundles:
            worker.request(focus, priority=True)
        first = self._next_actionable_group()
        if first is not None:
            start = next((i for i, g in enumerate(self._groups)
                          if g.index == first.index), 0)
            for group in self._groups[start:start + 4]:
                if group.index not in self._ready_bundles:
                    worker.request(group)
        if start_worker:
            worker.start()
        self._update_row_states()

    def _prewarm_ready(self, group, bundle):
        worker = self.sender()
        if (worker is not self._copy_worker or self._source is not worker.source
                or self._source_revision != worker.revision
                or bool(self.copy_mode.currentData()) != worker.as_zip):
            return
        self._ready_bundles[group.index] = bundle
        self._cache_errors.pop(group.index, None)
        if self._copy_pending is not None and self._copy_pending[0].index == group.index:
            self._publish_ready(group, bundle)
        else:
            self._update_row_states()

    def _prewarm_failed(self, group, reason):
        if self.sender() is not self._copy_worker:
            return
        self._cache_errors[group.index] = reason
        if self._copy_pending is not None and self._copy_pending[0].index == group.index:
            self._copy_failed(reason)
            self._finish_copy()
        else:
            self._update_row_states()

    def _prewarm_finished(self, worker):
        if worker in self._retired_workers:
            self._retired_workers.remove(worker)
        if worker is self._copy_worker:
            self._copy_worker = None
        worker.deleteLater()
        if self._copy_pending is not None and self._source is not None:
            self._schedule_prewarm(self._copy_pending[0])

    def _finish_copy(self):
        if self._copy_pending is None:
            return
        _, button, _, _, _ = self._copy_pending
        if button is not None:
            button.setEnabled(True)
        self._copy_pending = None
        self._update_row_states()

    def _style_row(self, group, row, status_label, button, next_group):
        """Update existing widgets in place to preserve late-batch scroll position."""
        status = self._group_status(group)
        is_next = next_group is not None and group.index == next_group.index
        visual = "next" if is_next else status
        status_label.setText(
            "● ชุดถัดไป · " + ("ต้องตรวจใหม่" if status == "review" else "ยังไม่ได้คัดลอก")
            if is_next else {
                "copied": "✓ คัดลอกแล้ว",
                "review": "⚠ ต้องตรวจใหม่",
                "new": "○ ยังไม่ได้คัดลอก",
            }[status]
        )
        bundle = self._ready_bundles.get(group.index)
        if bundle is not None and bundle.is_current():
            status_label.setText(status_label.text() + " · พร้อมคัดลอก")
        elif group.index in self._cache_errors:
            status_label.setText(status_label.text() + " · เตรียมไม่สำเร็จ")
        elif self._copy_worker is not None and group.index in self._copy_worker.pending_indices():
            status_label.setText(status_label.text() + " · กำลังเตรียม")
        row.setProperty("batchVisual", visual)
        status_label.setProperty("batchCopyStatus", visual)
        button.setProperty("batchCopyAction", "repeat" if status == "copied" else "primary")
        button.setText(
            "คัดลอกอีกครั้ง" if status == "copied" else
            "คัดลอกใหม่" if status == "review" else
            "คัดลอก ZIP" if self.copy_mode.currentData() else "คัดลอก"
        )
        for widget in (row, status_label, button):
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()

    def _update_row_states(self):
        """Repaint rendered rows only; never rebuild the lazy list after a copy."""
        next_group = self._next_actionable_group()
        for group, row, status_label, button in self._row_widgets.values():
            self._style_row(group, row, status_label, button, next_group)

    def _append_rows(self, limit=35):
        if self._busy:
            return
        self._busy = True
        try:
            end = min(len(self._visible), self._rendered + limit)
            next_group = self._next_actionable_group()
            for group in self._visible[self._rendered:end]:
                row = QFrame()
                layout = QGridLayout(row)
                layout.setContentsMargins(10, 5, 8, 5)
                layout.setHorizontalSpacing(9)
                row.setObjectName("translationBatchRow")
                row.setMinimumHeight(52)
                number_label = QLabel(f"{group.index:02d}")
                number_label.setObjectName("translationBatchNumber")
                layout.addWidget(number_label, 0, 0)
                chapter_label = QLabel(f"{group.start:04d}–{group.end:04d}")
                chapter_label.setObjectName("translationBatchRange")
                layout.addWidget(chapter_label, 0, 1)
                count_label = QLabel(str(len(group.chapters)))
                count_label.setObjectName("translationBatchCount")
                layout.addWidget(count_label, 0, 2)
                status_label = QLabel()
                status_label.setObjectName(f"translationBatchStatus{group.index}")
                layout.addWidget(status_label, 0, 3)
                details = QPushButton("รายละเอียด")
                details.setProperty("batchDetails", True)
                details.setCheckable(True)
                layout.addWidget(details, 0, 4)
                button = QPushButton()
                button.setObjectName(f"translationBatchCopy{group.index}")
                button.setMinimumHeight(36)
                button.clicked.connect(lambda _checked=False, g=group, b=button: self.copy_group(g, b))
                layout.addWidget(button, 0, 5)
                layout.setColumnStretch(1, 2)
                layout.setColumnStretch(3, 2)
                self.rows.addWidget(row)
                filenames = QLabel(", ".join(c.path.name for c in group.chapters))
                filenames.setWordWrap(True)
                filenames.setVisible(False)
                details.toggled.connect(filenames.setVisible)
                self.rows.addWidget(filenames)
                self._row_widgets[group.index] = (group, row, status_label, button)
                self._style_row(group, row, status_label, button, next_group)
            self._rendered = end
        finally:
            self._busy = False

    def _on_scroll(self, position):
        bar = self.scroll.verticalScrollBar()
        if bar.maximum() and position >= bar.maximum() - max(70, bar.pageStep() // 2):
            self._append_rows()

    def _confirm_skipped_group(self, skipped, target):
        """Let intentional skips proceed, or navigate back without modifying progress."""
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Warning)
        dialog.setWindowTitle("ตรวจสอบก่อนข้ามชุด")
        dialog.setText(
            f"ชุด {skipped.index} (บท {skipped.start:04d}–{skipped.end:04d}) "
            "ยังไม่ได้คัดลอกหรือจำเป็นต้องตรวจใหม่"
        )
        dialog.setInformativeText(
            f"คุณเลือกคัดลอกชุด {target.index} (บท {target.start:04d}–{target.end:04d})\n"
            "หากตั้งใจข้าม สามารถกลับมาคัดลอกชุดเก่าหรือคัดลอกซ้ำได้ทุกเมื่อ"
        )
        go_back = dialog.addButton(f"กลับไปชุด {skipped.index}", QMessageBox.AcceptRole)
        proceed = dialog.addButton(f"คัดลอกชุด {target.index} ต่อ", QMessageBox.ActionRole)
        dialog.addButton("ยกเลิก", QMessageBox.RejectRole)
        dialog.setDefaultButton(go_back)
        dialog.exec()
        if dialog.clickedButton() is go_back:
            self._scroll_to_group(skipped)
        return dialog.clickedButton() is proceed

    def copy_group(self, group, button=None):
        if not self._source or self._copy_pending is not None:
            return
        # Re-copying an old group never warns about skipped new groups.
        if self._group_status(group) == "new":
            skipped = next((
                candidate for candidate in self._groups
                if candidate.index < group.index and self._group_status(candidate) != "copied"
            ), None)
            if skipped is not None and not self._confirm_skipped_group(skipped, group):
                return
        if group.missing:
            result = QMessageBox.question(
                self, "บทไม่ครบ",
                "ขาดบท " + ", ".join(map(str, group.missing))
                + "\nคัดลอกเฉพาะบทที่มีอยู่หรือไม่?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if result != QMessageBox.Yes:
                return
        self._copy_pending = (group, button, self._source, self.mode.currentData(),
                              time.perf_counter())
        bundle = self._ready_bundles.get(group.index)
        if bundle is not None:
            # _publish_ready checks the cheap bundle guard and the full source
            # snapshot exactly once before publishing to Qt Clipboard.
            self._publish_ready(group, bundle)
            return
        self._ready_bundles.pop(group.index, None)
        if button is not None:
            button.setEnabled(False)
            button.setText("กำลังเตรียมไฟล์…")
        self.summary.setText(
            f"กำลังเตรียมชุดบท {group.start}–{group.end} · ยังไม่เปลี่ยน Clipboard")
        try:
            self._schedule_prewarm(group)
        except (OSError, ValueError) as exc:
            self._copy_failed(str(exc))
            self._finish_copy()

    def _publish_ready(self, group, bundle):
        if self._copy_pending is None:
            return
        pending_group, button, source, mode, clicked_at = self._copy_pending
        if (source is not self._source or mode != self.mode.currentData()
                or pending_group.index != group.index):
            self._finish_copy()
            return
        try:
            if not bundle.is_current():
                raise ValueError("ชุดไฟล์ที่เตรียมไว้เปลี่ยนแล้ว")
            selected_paths = tuple(
                chapter.path for chapter in chapters_for_group(source, group)
                if chapter.path is not None)
            validate_translation_source(
                source, text=self.state.get("draft") if mode == "paste" else None,
                selected_paths=selected_paths)
        except (OSError, ValueError):
            self._ready_bundles.pop(group.index, None)
            if button is not None:
                button.setEnabled(False)
                button.setText("ต้องตรวจใหม่…")
            self._schedule_prewarm(group)
            return
        t = time.perf_counter()
        try:
            copied = copy_file_paths(bundle.files)
            actual = tuple(Path(url.toLocalFile()).resolve()
                           for url in QApplication.clipboard().mimeData().urls())
            if actual != copied:
                raise OSError("Clipboard ไม่ได้เก็บชุดไฟล์ตามที่ร้องขอ")
        except (OSError, ValueError, AttributeError) as exc:
            self._copy_failed(str(exc))
            self._finish_copy()
            return
        publish_ms = (time.perf_counter() - t) * 1000
        click_ms = (time.perf_counter() - clicked_at) * 1000
        pin_error = None
        try:
            pin_clipboard_bundle(
                self.repo.root / "cache" / "clipboard" / "translation" / self.profile_id,
                bundle)
        except (OSError, ValueError) as exc:
            pin_error = str(exc)
        self.state["last_range"] = f"{group.start}-{group.end}"
        self.state["last_copied_start"] = group.start
        self.state["last_copied_end"] = group.end
        history_error = None
        t = time.perf_counter()
        if self.profile_id:
            try:
                source_chapters = chapters_for_group(self._source, group)
                verified_hashes = {path: digest.hex() for path, digest in self._source.signatures}
                fingerprints = {
                    str(chapter.number): (
                        hashlib.sha256(chapter.content).hexdigest()
                        if chapter.content is not None else verified_hashes[chapter.path]
                    ) for chapter in source_chapters
                }
                event = record_copy(
                    self.repo, self.profile_id, "translation",
                    identity=self._source_identity, revision=self._source_revision,
                    start=group.start, end=group.end,
                    chapter_numbers=[chapter.number for chapter in group.chapters],
                    batch_size=self.size.value(),
                    copy_mode="zip" if self.copy_mode.currentData() else "files",
                    copied_file_count=len(copied), chapter_fingerprints=fingerprints,
                )
                self._history.append(event)
                self._reindex_history()
            except (OSError, ValueError, TypeError) as exc:
                history_error = str(exc)
        history_ms = (time.perf_counter() - t) * 1000
        self._persist()
        if history_error or pin_error:
            self.summary.setText(
                f"✓ Clipboard พร้อมวาง · {len(copied)} ไฟล์"
                + (" · บันทึกประวัติไม่สำเร็จ: " + history_error if history_error else "")
                + (" · ป้องกัน Cache ไม่สำเร็จ: " + pin_error if pin_error else ""))
        else:
            self.summary.setText(
                f"✓ คัดลอกบท {group.start}–{group.end} สำเร็จ · {len(copied)} ไฟล์ · วางด้วย Ctrl+V")
        if os.getenv("NOVELWORKFLOW_COPY_PERF"):
            print("translation_copy_perf", {
                "cache_hit": bundle.timings.get("cache_hit"),
                "clipboard_ms": round(publish_ms, 2),
                "click_to_clipboard_ms": round(click_ms, 2),
                "history_ms": round(history_ms, 2),
            })
        self._finish_copy()
        if not history_error:
            self._update_history_summary()
        # No scroll position is changed; only rendered row widgets are repainted.
        QTimer.singleShot(0, self._schedule_prewarm)

    def _copy_failed(self, reason):
        self.summary.setText("คัดลอกไม่สำเร็จ: " + reason)
        QMessageBox.warning(self, "คัดลอกไม่สำเร็จ", reason)

    def _copy_finished(self):
        # Retained for compatibility with other page integrations.
        self._finish_copy()

    def closeEvent(self, event):
        if ((self._load_worker and self._load_worker.isRunning()) or
                (self._copy_worker and self._copy_worker.isRunning()) or
                any(worker.isRunning() for worker in self._retired_workers)):
            if self._copy_worker is not None:
                self._copy_worker.cancel()
            event.ignore()
            self.summary.setText("กำลังอ่านหรือเตรียมไฟล์ กรุณารอสักครู่ก่อนปิดหน้าต่าง")
            return
        self.flush_draft()
        super().closeEvent(event)

    def flush_draft(self):
        self._draft_timer.stop()
        self._flush_draft()

    def _group_status(self, group):
        return self._history_statuses.get(group.index, "new")

    def _history_summary(self):
        statuses = [self._group_status(group) for group in self._groups]
        return {"copied": statuses.count("copied"), "remaining": statuses.count("new"),
                "review": statuses.count("review")}

    def _update_history_summary(self):
        counts = self._history_summary()
        self.summary.setText(
            f"พร้อมคัดลอก · {sum(len(g.chapters) for g in self._groups)} บท · {len(self._groups)} ชุด · "
            f"คัดลอกแล้ว {counts['copied']} ชุด · ยังไม่ได้ {counts['remaining']} ชุด"
            + (f" · ต้องตรวจใหม่ {counts['review']} ชุด" if counts['review'] else "")
            + (f" · ล่าสุดบท {self.state['last_copied_start']}–{self.state['last_copied_end']} คัดลอกสำเร็จ"
               if self.state.get("last_copied_start") is not None else "")
        )

    def _restore_scroll(self, value):
        while self._rendered < len(self._visible) and self.scroll.verticalScrollBar().maximum() < value:
            self._append_rows()
        self.scroll.verticalScrollBar().setValue(value)

    def _filter_changed(self, *_):
        self.state["filter"] = self.history_filter.currentData() or "all"
        self._persist()
        self._refresh_rows()

    def _scroll_to_group(self, group):
        if group is None:
            return
        if self.search.text():
            self.search.clear()
        if self.history_filter.currentData() != "all":
            self.history_filter.setCurrentIndex(self.history_filter.findData("all"))
        try:
            index = self._visible.index(group)
        except ValueError:
            return
        while self._rendered <= index:
            self._append_rows()
        row = self.rows.itemAt(index * 2).widget()
        if row:
            self.scroll.ensureWidgetVisible(row, 4, 12)

    def _go_to_last_copied(self):
        groups = { (g.start, g.end, tuple(c.number for c in g.chapters)): g for g in self._groups }
        for event in reversed(self._history):
            if event.get("source_identity") != self._source_identity or event.get("source_revision") != self._source_revision:
                continue
            key = (event.get("start"), event.get("end"), tuple(event.get("chapter_numbers") or ()))
            group = groups.get(key)
            if group is not None:
                self._scroll_to_group(group)
                return

    def _go_to_next_uncopied(self):
        self._scroll_to_group(self._next_actionable_group())
