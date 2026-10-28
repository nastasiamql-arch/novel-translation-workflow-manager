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
    QGridLayout, QSizePolicy,
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
        self._persist()
        if self._source:
            self._groups = translation_groups(self._source, self.size.value())
            self._refresh_rows()

    def _copy_mode_changed(self, *_):
        self.state["zip"] = bool(self.copy_mode.currentData())
        self._persist()
        if self._source:
            self._refresh_rows()

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
        missing = split_missing_numbers(tuple(
            type("Segment", (), {"number": chapter.number}) for chapter in source.chapters))
        counts = self._history_summary()
        self.summary.setText(
            f"พร้อมคัดลอก · {len(source.chapters)} บท · {len(self._groups)} ชุด · "
            f"คัดลอกแล้ว {counts['copied']} ชุด · ยังไม่ได้ {counts['remaining']} ชุด"
            + (f" · ต้องตรวจใหม่ {counts['review']} ชุด" if counts['review'] else "")
            + (f" · ขาดบท {', '.join(map(str, missing[:20]))}" if missing else ""))
        self._refresh_rows()
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

    def _append_rows(self, limit=35):
        if self._busy:
            return
        self._busy = True
        try:
            end = min(len(self._visible), self._rendered + limit)
            for group in self._visible[self._rendered:end]:
                row = QFrame()
                layout = QGridLayout(row)
                layout.setContentsMargins(7, 4, 7, 4)
                layout.setHorizontalSpacing(8)
                row.setObjectName("translationBatchRow")
                row.setMinimumHeight(48)
                layout.addWidget(QLabel(f"{group.index:02d}"), 0, 0)
                chapter_label = QLabel(f"{group.start:04d}–{group.end:04d}")
                layout.addWidget(chapter_label, 0, 1)
                layout.addWidget(QLabel(str(len(group.chapters))), 0, 2)
                status = self._group_status(group)
                status_text = {"copied": "✓ คัดลอกแล้ว", "review": "ต้องตรวจใหม่",
                               "new": "ยังไม่ได้คัดลอก"}[status]
                status_label = QLabel(status_text)
                status_label.setObjectName(f"translationBatchStatus{group.index}")
                layout.addWidget(status_label, 0, 3)
                details = QPushButton("รายละเอียด")
                details.setCheckable(True)
                layout.addWidget(details, 0, 4)
                button_label = ("คัดลอกอีกครั้ง" if status == "copied" else
                                "ต้องตรวจใหม่ · คัดลอก" if status == "review" else
                                "คัดลอก ZIP" if self.copy_mode.currentData() else "คัดลอก")
                button = QPushButton(button_label)
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
            self._rendered = end
        finally:
            self._busy = False

    def _on_scroll(self, position):
        bar = self.scroll.verticalScrollBar()
        if bar.maximum() and position >= bar.maximum() - max(70, bar.pageStep() // 2):
            self._append_rows()

    def copy_group(self, group, button=None):
        if not self._source or (self._copy_worker and self._copy_worker.isRunning()):
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
            profile = deepcopy(self._profile())
            mode = self.mode.currentData()
            chosen = self.state.get("path") if mode in ("file", "folder") else None
            selected_id = self.state.get("attachment_id") if mode == "step" else None
            worker = TranslationCopyWorker(
                self._source, group, self.repo, self.assembler, profile,
                chosen, selected_id,
                self.repo.root / "cache" / "clipboard" / "translation" / profile.id,
                as_zip=bool(self.copy_mode.currentData()),
                pasted_text=self.pasted_text.toPlainText() if self.mode.currentData() == "paste" else None)
            self._copy_worker = worker
            self._copy_pending = (group, button, self._source, mode)
            if button:
                button.setEnabled(False)
                button.setText("กำลังเตรียมไฟล์…")
            self.summary.setText(f"กำลังเตรียมชุดบท {group.start}–{group.end} · ยังไม่เปลี่ยน Clipboard")
            worker.prepared.connect(self._copy_ready)
            worker.failed.connect(self._copy_failed)
            worker.finished.connect(self._copy_finished)
            worker.start()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "คัดลอกไม่สำเร็จ", str(exc))

    def _copy_ready(self, files):
        if self._copy_pending is None:
            return
        group, button, source, mode = self._copy_pending
        if source is not self._source or mode != self.mode.currentData():
            self.summary.setText("ต้นฉบับเปลี่ยนแล้ว กรุณาคัดลอกชุดใหม่")
            return
        try:
            copied = copy_file_paths(files)  # Qt Clipboard must only change on the GUI thread.
            self.state["last_range"] = f"{group.start}-{group.end}"
            self.state["last_copied_start"] = group.start
            self.state["last_copied_end"] = group.end
            if self.profile_id:
                source_chapters = chapters_for_group(self._source, group)
                fingerprints = {
                    str(chapter.number): hashlib.sha256(
                        chapter.content if chapter.content is not None else file_digest(chapter.path)
                    ).hexdigest() for chapter in source_chapters
                }
                record_copy(
                    self.repo, self.profile_id, "translation",
                    identity=self._source_identity, revision=self._source_revision,
                    start=group.start, end=group.end,
                    chapter_numbers=[chapter.number for chapter in group.chapters],
                    batch_size=self.size.value(),
                    copy_mode="zip" if self.copy_mode.currentData() else "files",
                    copied_file_count=len(copied), chapter_fingerprints=fingerprints,
                )
                self._history = load_history(self.repo, self.profile_id, "translation")
            self._persist()
            self.summary.setText(
                f"✓ คัดลอกบท {group.start}–{group.end} สำเร็จ · {len(copied)} ไฟล์ · วางด้วย Ctrl+V")
            if button:
                button.setText("คัดลอกอีกครั้ง")
            # A successful copy only changes this row's status. Recreating the
            # lazy list drops its scroll range and jumps away from late batches.
            status_label = self.findChild(QLabel, f"translationBatchStatus{group.index}")
            if status_label is not None:
                status_label.setText("✓ คัดลอกแล้ว")
            self._update_history_summary()
        except (OSError, ValueError) as exc:
            self._copy_failed(str(exc))

    def _copy_failed(self, reason):
        self.summary.setText("คัดลอกไม่สำเร็จ: " + reason)
        QMessageBox.warning(self, "คัดลอกไม่สำเร็จ", reason)

    def _copy_finished(self):
        finished_group = None
        if self._copy_pending:
            finished_group, button, _, _ = self._copy_pending
            if button:
                button.setEnabled(True)
                if button.text() == "กำลังเตรียมไฟล์…":
                    button.setText("คัดลอก ZIP" if self.copy_mode.currentData() else "คัดลอก")
        self._copy_pending = None
        # In filtered lists a copied 'new' or 'review' row no longer belongs
        # in the result. Refilter after releasing the worker's button, not
        # while the worker still holds it as an in-flight control.
        if (finished_group is not None
                and self.history_filter.currentData() in ("new", "review")
                and self._group_status(finished_group) == "copied"):
            self._refresh_rows()
        worker = self._copy_worker
        self._copy_worker = None
        if worker:
            worker.deleteLater()

    def closeEvent(self, event):
        if ((self._load_worker and self._load_worker.isRunning()) or
                (self._copy_worker and self._copy_worker.isRunning())):
            event.ignore()
            self.summary.setText("กำลังอ่านหรือเตรียมไฟล์ กรุณารอสักครู่ก่อนปิดหน้าต่าง")
            return
        self.flush_draft()
        super().closeEvent(event)

    def flush_draft(self):
        self._draft_timer.stop()
        self._flush_draft()

    def _group_status(self, group):
        return group_copy_status(
            self._history, identity=self._source_identity, revision=self._source_revision,
            start=group.start, end=group.end,
            chapter_numbers=[chapter.number for chapter in group.chapters],
        )

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
        group = next((g for g in self._groups if self._group_status(g) == "new"), None)
        self._scroll_to_group(group)
