"""Two simple TXT-based vocabulary tools inside the existing novel workspace.

Reading, previewing, and selecting sources never mutate source files, export
records, translation steps, or the clipboard. Clipboard copy is user initiated.
"""
from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QMessageBox,
    QLineEdit, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QTabWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from .clipboard_files import copy_file_paths
from .vocabulary_zip import create_txt_batch_zip
from .vocabulary_source_binding import (
    batch_stage_files, chapter_source_directory, source_by_id, suggest_source_id,
)
from .vocabulary_batches import (
    existing_chapter_targets, make_chapter_batches, parse_pasted_chapters,
    read_utf8_text, scan_chapter_files, split_missing_numbers, write_split_chapters,
)


class TxtVocabularyPage(QWidget):
    """Read-only TXT batch copying and explicit preview-then-save splitting."""

    def __init__(self, state: dict, changed, default_folder: Path, parent=None, *,
                 stage_reader=None, archive_cache_dir=None):
        super().__init__(parent)
        self.changed = changed
        self.default_folder = Path(default_folder)
        self.archive_cache_dir = Path(archive_cache_dir) if archive_cache_dir is not None else (
            Path(tempfile.gettempdir()) / "NovelWorkflow" / "txt-vocabulary"
        )
        self.stage_reader = stage_reader
        self.bound_mode = stage_reader is not None
        self._stage_entries = ()
        self._selected_source_id = None
        self._loaded_file_path = None
        self._loaded_file_signature = None
        self._split_source_folder = None
        self.state = dict(state) if isinstance(state, dict) else {}
        self.state.setdefault("folder", str(self.default_folder))
        self.state.setdefault("batch_size", 5)
        self.state.setdefault("start", 0)
        self.state.setdefault("end", 0)
        self.state.setdefault("glossary_1", "")
        self.state.setdefault("glossary_2", "")
        self.state.setdefault("copy_as_zip", False)
        self._copy_buttons = []
        self._segments = ()
        self._preview_input = None
        self._groups = ()
        self._rendered_count = 0
        self._batch_widgets = []
        self._loading = False
        self.setObjectName("txtVocabularyPage")

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 6, 12, 8)
        title = QLabel("หาคำศัพท์จาก TXT")
        title.setObjectName("sectionHeading")
        root.addWidget(title)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("txtVocabularyTabs")
        root.addWidget(self.tabs, 1)

        batch_page = QWidget()
        batch_layout = QVBoxLayout(batch_page)
        batch_layout.setSpacing(9)
        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("โฟลเดอร์ต้นฉบับ"))
        self.folder_label = QLabel()
        self.folder_label.setObjectName("mutedLabel")
        self.folder_label.setMinimumWidth(0)
        self.folder_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        folder_row.addWidget(self.folder_label, 1)
        self.source_picker = QComboBox()
        self.source_picker.setObjectName("txtVocabularyStageSource")
        self.source_picker.setMinimumWidth(220)
        self.source_picker.setToolTip("ต้นฉบับจากไฟล์ที่เปิดใช้งานในขั้นตอนหาศัพท์เดิมเท่านั้น")
        self.source_picker.currentIndexChanged.connect(self._source_changed)
        folder_row.addWidget(self.source_picker, 1)
        self.source_picker.setVisible(self.bound_mode)
        select_folder = QPushButton("เลือกโฟลเดอร์")
        select_folder.setObjectName("txtVocabularyChooseFolder")
        select_folder.clicked.connect(self.choose_folder)
        select_folder.setVisible(not self.bound_mode)
        folder_row.addWidget(select_folder)
        batch_layout.addLayout(folder_row)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("บทต่อชุด"))
        self.batch_size = QSpinBox()
        self.batch_size.setObjectName("txtVocabularyBatchSize")
        self.batch_size.setRange(1, 100)
        self.batch_size.setValue(max(1, min(100, int(self.state.get("batch_size") or 5))))
        controls.addWidget(self.batch_size)
        controls.addWidget(QLabel("เริ่ม"))
        self.start = QSpinBox()
        self.start.setObjectName("txtVocabularyStart")
        self.start.setRange(0, 999999)
        self.start.setSpecialValueText("อัตโนมัติ")
        self.start.setValue(max(0, int(self.state.get("start") or 0)))
        controls.addWidget(self.start)
        controls.addWidget(QLabel("ถึง"))
        self.end = QSpinBox()
        self.end.setObjectName("txtVocabularyEnd")
        self.end.setRange(0, 999999)
        self.end.setSpecialValueText("อัตโนมัติ")
        self.end.setValue(max(0, int(self.state.get("end") or 0)))
        controls.addWidget(self.end)
        reload_button = QPushButton("รีเฟรช")
        reload_button.setObjectName("txtVocabularyRefresh")
        reload_button.clicked.connect(self.refresh)
        controls.addWidget(reload_button)
        self.zip_toggle = QCheckBox("คัดลอกเป็น ZIP")
        self.zip_toggle.setObjectName("txtVocabularyCopyAsZip")
        self.zip_toggle.setToolTip("เฉพาะหาศัพท์จาก TXT · ZIP หนึ่งไฟล์ต่อชุด · ไม่กระทบ ZIP ของ Workflow เดิม")
        self.zip_toggle.setChecked(bool(self.state.get("copy_as_zip", False)))
        self.zip_toggle.toggled.connect(self._copy_mode_changed)
        controls.addWidget(self.zip_toggle)
        controls.addStretch(1)
        batch_layout.addLayout(controls)

        self.glossary_labels = []
        for n in (1, 2):
            glossary_row = QWidget()
            row = QHBoxLayout(glossary_row)
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(QLabel(f"คำศัพท์อ้างอิง {n}"))
            label = QLabel()
            label.setObjectName("mutedLabel")
            label.setMinimumWidth(0)
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.glossary_labels.append(label)
            row.addWidget(label, 1)
            choose = QPushButton("เลือกไฟล์")
            choose.setObjectName(f"txtVocabularyChooseGlossary{n}")
            choose.clicked.connect(lambda checked=False, i=n: self.choose_glossary(i))
            row.addWidget(choose)
            batch_layout.addWidget(glossary_row)
            glossary_row.setVisible(not self.bound_mode)
        self.summary = QLabel()
        self.summary.setObjectName("mutedLabel")
        self.summary.setWordWrap(True)
        batch_layout.addWidget(self.summary)
        jump = QHBoxLayout()
        self.chapter_search = QLineEdit()
        self.chapter_search.setObjectName("txtVocabularyChapterSearch")
        self.chapter_search.setPlaceholderText("ไปยังเลขบท เช่น 0500")
        self.chapter_search.setClearButtonEnabled(True)
        self.chapter_search.returnPressed.connect(self.jump_to_chapter)
        jump.addWidget(self.chapter_search, 1)
        jump_button = QPushButton("ไปยังบท")
        jump_button.setObjectName("txtVocabularyJump")
        jump_button.clicked.connect(self.jump_to_chapter)
        jump.addWidget(jump_button)
        batch_layout.addLayout(jump)
        self.scroll = QScrollArea()
        self.scroll.setObjectName("txtVocabularyBatchScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.verticalScrollBar().setSingleStep(38)
        self.cards = QWidget()
        self.cards_layout = QVBoxLayout(self.cards)
        self.cards_layout.setContentsMargins(0, 0, 8, 0)
        self.cards_layout.setSpacing(0)
        self.scroll.setWidget(self.cards)
        self.scroll.verticalScrollBar().valueChanged.connect(self._load_on_scroll)
        batch_layout.addWidget(self.scroll, 1)
        self.tabs.addTab(batch_page, "คัดลอกเป็นชุด")

        paste_page = QWidget()
        paste_layout = QVBoxLayout(paste_page)
        paste_layout.setSpacing(9)
        hint = QLabel("วางต้นฉบับหลายบทครั้งเดียว แล้วตรวจหัวบทก่อนสร้างไฟล์ TXT · ไม่เขียนทับอัตโนมัติ")
        hint.setWordWrap(True)
        hint.setObjectName("mutedLabel")
        paste_layout.addWidget(hint)
        self.pasted_text = QPlainTextEdit()
        self.pasted_text.setObjectName("txtVocabularyPastedText")
        self.pasted_text.setPlaceholderText(
            "第一章 开始\nเนื้อหาบทที่หนึ่ง...\n\n第二章 觉醒\nเนื้อหาบทที่สอง...\n\n"
            "รองรับ 第100章, บทที่ 1, ตอนที่ 1, Chapter 1"
        )
        self.pasted_text.setMinimumHeight(140)
        paste_layout.addWidget(self.pasted_text, 2)
        preview_row = QHBoxLayout()
        self.preview_button = QPushButton("ตรวจหัวบทและแสดงตัวอย่าง")
        self.preview_button.setObjectName("txtVocabularyPreview")
        self.preview_button.clicked.connect(self.preview_paste)
        preview_row.addWidget(self.preview_button)
        self.paste_summary = QLabel("ยังไม่ได้ตรวจข้อความ")
        self.paste_summary.setObjectName("mutedLabel")
        self.paste_summary.setWordWrap(True)
        preview_row.addWidget(self.paste_summary, 1)
        paste_layout.addLayout(preview_row)
        self.preview_table = QTableWidget(0, 3)
        self.preview_table.setObjectName("txtVocabularyPreviewTable")
        self.preview_table.setHorizontalHeaderLabels(["บท", "ชื่อไฟล์ที่จะสร้าง", "บรรทัดต้นฉบับ"])
        self.preview_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.preview_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.preview_table.setAlternatingRowColors(True)
        self.preview_table.horizontalHeader().setStretchLastSection(True)
        self.preview_table.itemSelectionChanged.connect(self.show_preview_chapter)
        paste_layout.addWidget(self.preview_table, 2)
        self.chapter_preview = QPlainTextEdit()
        self.chapter_preview.setObjectName("txtVocabularyChapterPreview")
        self.chapter_preview.setReadOnly(True)
        self.chapter_preview.setPlaceholderText("เลือกบทด้านบนเพื่อดูเนื้อหาตั้งแต่หัวบทจนถึงก่อนบทถัดไป")
        self.chapter_preview.setMinimumHeight(90)
        paste_layout.addWidget(self.chapter_preview, 1)
        dest_row = QHBoxLayout()
        dest_row.addWidget(QLabel("บันทึกไปยัง"))
        self.destination_label = QLabel()
        self.destination_label.setMinimumWidth(0)
        self.destination_label.setObjectName("mutedLabel")
        dest_row.addWidget(self.destination_label, 1)
        choose_destination = QPushButton("เลือกปลายทาง")
        choose_destination.setObjectName("txtVocabularyChooseDestination")
        choose_destination.clicked.connect(self.choose_destination)
        dest_row.addWidget(choose_destination)
        paste_layout.addLayout(dest_row)
        self.save_button = QPushButton("ยืนยันและแยกเป็นไฟล์ TXT")
        self.save_button.setObjectName("txtVocabularySaveSplit")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self.save_paste)
        paste_layout.addWidget(self.save_button)
        self.tabs.addTab(paste_page, "แยกบทจากไฟล์")
        source_row = QHBoxLayout()
        self.read_stage_button = QPushButton("อ่านต้นฉบับจากขั้นตอนหาศัพท์")
        self.read_stage_button.setObjectName("txtVocabularyLoadStageSource")
        self.read_stage_button.clicked.connect(self.load_from_stage)
        self.read_stage_button.setVisible(self.bound_mode)
        source_row.addWidget(self.read_stage_button)
        source_row.addStretch(1)
        paste_layout.insertLayout(1, source_row)
        self.tabs.currentChanged.connect(self._tab_changed)

        self.batch_size.valueChanged.connect(self._configuration_changed)
        self.start.valueChanged.connect(self._configuration_changed)
        self.end.valueChanged.connect(self._configuration_changed)
        self.pasted_text.textChanged.connect(self.invalidate_preview)
        self._update_labels()
        self.refresh()

    def _save(self):
        self.state["batch_size"] = self.batch_size.value()
        self.state["start"] = self.start.value()
        self.state["end"] = self.end.value()
        self.changed(dict(self.state))

    def _configuration_changed(self, _value):
        self._save()
        self.refresh()

    def _copy_mode_changed(self, enabled):
        self.state["copy_as_zip"] = bool(enabled)
        self._save()
        for button, count in self._copy_buttons:
            button.setText("คัดลอก ZIP" if enabled else f"คัดลอก {count} ไฟล์")
        # No refresh, no scroll movement and no clipboard replacement.

    def _update_labels(self):
        if self.bound_mode:
            selected = source_by_id(self._stage_entries, self._selected_source_id)
            path = selected.path if selected else None
            folder = str(chapter_source_directory(selected) or "ยังไม่เลือกต้นฉบับจากขั้นตอนหาศัพท์")
            self.read_stage_button.setEnabled(bool(path and path.is_file()))
        else:
            folder = str(self.state.get("folder") or self.default_folder)
        self.folder_label.setText(folder)
        self.folder_label.setToolTip(folder)
        destination = str(self.state.get("destination") or folder)
        self.destination_label.setText(destination)
        self.destination_label.setToolTip(destination)
        for n, label in enumerate(self.glossary_labels, 1):
            file = str(self.state.get(f"glossary_{n}") or "")
            label.setText(Path(file).name if file else "ยังไม่เลือก")
            label.setToolTip(file)

    def choose_folder(self):
        if self.bound_mode:
            return
        folder = QFileDialog.getExistingDirectory(
            self, "เลือกโฟลเดอร์ TXT", str(self.state.get("folder") or self.default_folder)
        )
        if folder:
            self.state["folder"] = folder
            self.state["destination"] = folder
            self._update_labels()
            self._save()
            self.refresh()

    def choose_destination(self):
        folder = QFileDialog.getExistingDirectory(
            self, "เลือกโฟลเดอร์บันทึกไฟล์ที่แยก",
            str(self.state.get("destination") or self.state.get("folder") or self.default_folder),
        )
        if folder:
            self.state["destination"] = folder
            self._update_labels()
            self._save()

    def choose_glossary(self, index: int):
        if self.bound_mode:
            return
        current = str(self.state.get(f"glossary_{index}") or self.state.get("folder") or "")
        path, _ = QFileDialog.getOpenFileName(
            self, f"เลือกไฟล์คำศัพท์อ้างอิง {index}", current,
            "Text files (*.txt *.md *.markdown);;All files (*)",
        )
        if path:
            self.state[f"glossary_{index}"] = path
            self._update_labels()
            self._save()
            self.refresh()

    def _refresh_stage_sources(self):
        try:
            entries = tuple(self.stage_reader())
        except (OSError, ValueError, KeyError, TypeError) as exc:
            entries = ()
            self.summary.setText("อ่านไฟล์หาศัพท์ไม่สำเร็จ: " + str(exc))
        previous = self._selected_source_id or self.state.get("source_id")
        self._stage_entries = entries
        available = {entry.id for entry in entries}
        if previous in available:
            selected_id = previous
        elif self.state.get("source_id"):
            selected_id = None  # Missing/disabled: never silently switch novels or sources.
        else:
            selected_id = suggest_source_id(entries)
        self._selected_source_id = selected_id
        self.source_picker.blockSignals(True)
        self.source_picker.clear()
        self.source_picker.addItem("เลือกต้นฉบับจากขั้นตอนหาศัพท์", None)
        for entry in entries:
            name = entry.path.name if entry.path else ("หาไฟล์ไม่พบ: " + entry.label)
            self.source_picker.addItem(name, entry.id)
            self.source_picker.setItemData(
                self.source_picker.count() - 1,
                str(entry.path) if entry.path else entry.error,
                Qt.ToolTipRole,
            )
        index = self.source_picker.findData(selected_id)
        self.source_picker.setCurrentIndex(max(0, index))
        self.source_picker.blockSignals(False)
        self._update_labels()

    def _source_changed(self, _index):
        if not self.bound_mode:
            return
        self._selected_source_id = self.source_picker.currentData()
        self._split_source_folder = None
        self.state["source_id"] = self._selected_source_id or ""
        self._save()
        self._update_labels()
        self.refresh()
        # Do not overwrite a user's manual pasted content when changing sources.

    def _tab_changed(self, tab):
        if tab == 1 and self.bound_mode and not self.pasted_text.toPlainText().strip():
            QTimer.singleShot(0, self.load_from_stage)

    def load_from_stage(self):
        if not self.bound_mode:
            return
        self._refresh_stage_sources()
        source = source_by_id(self._stage_entries, self._selected_source_id)
        if source is None or source.path is None:
            self.paste_summary.setText("ไม่พบต้นฉบับที่เปิดใช้งานในขั้นตอนหาศัพท์")
            return
        if source.path.is_dir():
            self.tabs.setCurrentIndex(0)
            self.summary.setText("ต้นฉบับเป็นโฟลเดอร์ไฟล์แยกบทแล้ว ใช้แท็บคัดลอกเป็นชุดได้ทันที")
            return
        try:
            chapters = scan_chapter_files(source.path.parent)
            if any(chapter.path == source.path for chapter in chapters):
                self.tabs.setCurrentIndex(0)
                self.summary.setText("ต้นฉบับเป็นไฟล์แยกบทแล้ว ใช้แท็บคัดลอกเป็นชุดได้ทันที")
                return
            contents = read_utf8_text(source.path)
        except (OSError, ValueError) as exc:
            self.paste_summary.setText("ไม่สามารถอ่านต้นฉบับจากขั้นตอนหาศัพท์: " + str(exc))
            return
        if self.pasted_text.toPlainText().strip() and self.pasted_text.toPlainText() != contents:
            answer = QMessageBox.question(
                self, "มีข้อความที่วางไว้",
                "แทนที่ข้อความปัจจุบันด้วยไฟล์ต้นฉบับจากขั้นตอนหาศัพท์หรือไม่?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        self._loaded_file_path = source.path
        self._split_source_folder = None
        self._loaded_file_signature = (source.path.stat().st_mtime_ns, source.path.stat().st_size)
        self.pasted_text.setPlainText(contents)
        self.preview_paste()

    def _clear_cards(self):
        self._groups = ()
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # Prevent findChild from resolving a stale card while Qt is
                # waiting for deferred deletion after a refresh.
                widget.setParent(None)
                widget.hide()
                widget.deleteLater()
        self._batch_widgets = []
        self._copy_buttons = []
        self._rendered_count = 0

    def refresh(self):
        """Rebuild only the first visible page; preserve the scroll offset on refresh."""
        old_scroll = self.scroll.verticalScrollBar().value()
        self._clear_cards()
        self._groups = ()
        if self.bound_mode:
            self._refresh_stage_sources()
        try:
            if self.bound_mode:
                source = source_by_id(self._stage_entries, self._selected_source_id)
                if source is None or source.path is None:
                    self.summary.setText(
                        "กรุณาเลือกไฟล์ต้นฉบับที่เปิดใช้งานในขั้นตอนหาศัพท์ "
                        "หากไม่พบไฟล์ ให้เพิ่มหรือเปิดใช้งานไฟล์ในขั้นตอนหาศัพท์เดิม"
                    )
                    return
                folder = self._split_source_folder or chapter_source_directory(source)
            else:
                folder = self.state.get("folder") or self.default_folder
            chapters = scan_chapter_files(folder)
            if not chapters:
                self.summary.setText(
                    "ยังไม่พบไฟล์ TXT แยกบท · ไปที่แท็บ 'แยกบทจากไฟล์' "
                    "เพื่ออ่านต้นฉบับที่ผูกไว้และตรวจหัวบทก่อนสร้างไฟล์"
                    if self.bound_mode else "ไม่พบไฟล์ TXT ที่ขึ้นต้นด้วยเลขบท เช่น 0001.txt"
                )
                return
            groups = make_chapter_batches(
                chapters, self.batch_size.value(),
                self.start.value() or None, self.end.value() or None,
            )
        except (OSError, ValueError) as exc:
            self.summary.setText(str(exc))
            return
        self._groups = groups
        missing_count = sum(len(group.missing) for group in groups)
        self.summary.setText(
            f"พบ {len(chapters)} ไฟล์บท · {len(groups)} ชุด · บท {groups[0].start:04d}–{groups[-1].end:04d}"
            + (f" · ขาด {missing_count} บท (แจ้งก่อนคัดลอก)" if missing_count else "")
        )
        self._append_next()
        if old_scroll:
            QTimer.singleShot(0, lambda: self.scroll.verticalScrollBar().setValue(old_scroll))

    def _append_next(self, limit=36):
        """Incremental cards: only create more as the user scrolls or searches."""
        if self._loading or self._rendered_count >= len(self._groups):
            return
        self._loading = True
        try:
            until = min(len(self._groups), self._rendered_count + limit)
            while self._rendered_count < until:
                batch = self._groups[self._rendered_count]
                self._batch_widgets.append(self._make_card(batch))
                self._rendered_count += 1
        finally:
            self._loading = False

    def _load_on_scroll(self, position):
        bar = self.scroll.verticalScrollBar()
        if bar.maximum() and position >= bar.maximum() - max(80, bar.pageStep() // 2):
            self._append_next()

    def _make_card(self, group):
        """One compact, single-column Explorer-like row; details start collapsed."""
        row = QFrame()
        row.setObjectName("txtVocabularyRow")
        row.setFrameShape(QFrame.NoFrame)
        row.setMaximumHeight(68)  # A single row must never fill the entire scroll viewport.
        layout = QVBoxLayout(row)
        layout.setContentsMargins(8, 3, 8, 3)
        layout.setSpacing(0)
        top = QHBoxLayout()
        top.setSpacing(9)

        number = QLabel(f"{group.index:02d}")
        number.setObjectName("txtVocabularyBatchNumber")
        number.setFixedWidth(30)
        number.setAlignment(Qt.AlignCenter)
        top.addWidget(number)
        heading = QLabel(f"บท {group.start:04d}–{group.end:04d}")
        heading.setObjectName("txtVocabularyBatchRange")
        heading.setMinimumWidth(105)
        top.addWidget(heading)

        if self.bound_mode:
            references = [
                entry for entry in self._stage_entries
                if entry.id != self._selected_source_id
                and entry.dynamic_reference != "CURRENT_SOURCE_CHAPTER"
            ]
            try:
                paths = batch_stage_files(
                    group, self._stage_entries, self._selected_source_id,
                    chapter_folder=self._split_source_folder,
                )
                unique_count = len(paths)
                missing_references = []
            except (OSError, ValueError) as exc:
                unique_count = len(group.chapters)
                missing_references = [str(exc)]
        else:
            references = [self.state.get(f"glossary_{n}") for n in (1, 2)]
            paths = [ch.path for ch in group.chapters] + [
                Path(p) for p in references if p
            ]
            unique_count = len({str(p.expanduser().resolve()).casefold() for p in paths})
            missing_references = [
                str(p) for p in references if p and not Path(p).expanduser().is_file()
            ]
        status = f"{unique_count} ไฟล์"
        if missing_references:
            status += " · ⚠ ไฟล์หาศัพท์หาย"
        if group.missing:
            status += f" · ⚠ ขาด {len(group.missing)} บท"
        count = QLabel(status)
        count.setObjectName("txtVocabularyBatchCount")
        count.setMinimumWidth(75)
        count.setToolTip("จำนวนไฟล์ต้นฉบับและไฟล์ที่เปิดใช้งานในขั้นตอนหาศัพท์เดิม")
        top.addWidget(count, 1)

        detail_button = QPushButton("ดูรายชื่อไฟล์ ▾")
        detail_button.setObjectName(f"txtVocabularyDetails{group.index}")
        detail_button.setProperty("batchDetails", True)
        detail_button.setFlat(True)
        detail_button.setCursor(Qt.PointingHandCursor)
        detail_button.setToolTip("ขยายหรือซ่อนรายชื่อไฟล์")
        top.addWidget(detail_button)

        copy = QPushButton(
            "คัดลอก ZIP" if self.zip_toggle.isChecked()
            else f"คัดลอก {unique_count} ไฟล์"
        )
        copy.setObjectName(f"txtVocabularyCopyBatch{group.index}")
        copy.setProperty("batchCopyPrimary", True)
        copy.setMinimumHeight(34)
        copy.setMinimumWidth(115)
        copy.setCursor(Qt.PointingHandCursor)
        copy.setToolTip("คัดลอกเป็น ZIP หนึ่งไฟล์" if self.zip_toggle.isChecked()
                        else "คัดลอกไฟล์จริงทั้งหมด · Ctrl+V")
        copy.setEnabled(bool(group.chapters) and (not self.bound_mode or not missing_references))
        copy.clicked.connect(lambda checked=False, batch=group, button=copy: self.copy_batch(batch, button))
        self._copy_buttons.append((copy, unique_count))
        top.addWidget(copy)
        layout.addLayout(top)

        detail = QWidget()
        detail.setObjectName("txtVocabularyDetail")
        details = QVBoxLayout(detail)
        details.setContentsMargins(38, 4, 4, 8)
        details.setSpacing(4)
        for chapter in group.chapters:
            label = QLabel(f"{chapter.number:04d}  {chapter.path.name}")
            label.setObjectName("mutedLabel")
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            details.addWidget(label)
        if self.bound_mode:
            reference_labels = [
                f"{entry.label} · {entry.path.name if entry.path else 'ไฟล์หาย'}"
                for entry in references
            ]
        else:
            reference_labels = [
                f"คำศัพท์ {n} · {Path(path).name if path else 'ยังไม่ได้เลือก'}"
                for n, path in enumerate(references, 1)
            ]
        for text in reference_labels:
            label = QLabel(text)
            label.setObjectName("mutedLabel")
            label.setWordWrap(True)
            details.addWidget(label)
        if group.missing:
            warning = QLabel("บทที่ขาด: " + ", ".join(f"{n:04d}" for n in group.missing[:30]))
            warning.setObjectName("mutedLabel")
            warning.setWordWrap(True)
            details.addWidget(warning)
        detail.setVisible(False)

        def toggle_details():
            before = self.scroll.verticalScrollBar().value()
            showing = not detail.isVisible()
            row.setMaximumHeight(16777215 if showing else 68)
            detail.setVisible(showing)
            detail_button.setText("ซ่อนรายชื่อไฟล์ ▴" if showing else "ดูรายชื่อไฟล์ ▾")
            QTimer.singleShot(0, lambda: self.scroll.verticalScrollBar().setValue(before))
        detail_button.clicked.connect(toggle_details)
        layout.addWidget(detail)

        self.cards_layout.addWidget(row)
        return row

    def jump_to_chapter(self):
        value = self.chapter_search.text().strip()
        if not value.isdecimal() or not self._groups:
            self.summary.setText("กรุณากรอกเลขบทที่ต้องการค้นหา เช่น 0500")
            return
        number = int(value)
        index = next((i for i, group in enumerate(self._groups)
                      if group.start <= number <= group.end), -1)
        if index < 0:
            QMessageBox.information(self, "ไม่พบเลขบท", f"ไม่มีบท {number:04d} ในช่วงที่เลือก")
            return
        while self._rendered_count <= index:
            self._append_next()
        card = self._batch_widgets[index]
        QTimer.singleShot(0, lambda: self.scroll.ensureWidgetVisible(card, 4, 12))

    def copy_batch(self, group, button: QPushButton):
        """Same file-URL clipboard semantics as the existing workflow copy."""
        if group.missing:
            response = QMessageBox.question(
                self, "มีเลขบทขาด",
                "บทที่ขาด: " + ", ".join(f"{n:04d}" for n in group.missing[:30])
                + "\nคัดลอกเฉพาะบทที่มีอยู่หรือไม่?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if response != QMessageBox.Yes:
                return
        try:
            if self.bound_mode:
                entries = tuple(self.stage_reader())
                paths = batch_stage_files(
                    group, entries, self._selected_source_id,
                    chapter_folder=self._split_source_folder,
                )
            else:
                references = [self.state.get(f"glossary_{n}") for n in (1, 2)]
                paths = [chapter.path for chapter in group.chapters]
                paths.extend(Path(reference).expanduser() for reference in references if reference)
            if self.zip_toggle.isChecked():
                archive = create_txt_batch_zip(
                    paths, len(group.chapters), group.start, group.end,
                    self.archive_cache_dir,
                )
                try:
                    copied = copy_file_paths((archive,))
                except BaseException:
                    archive.unlink(missing_ok=True)
                    raise
                label = f"ZIP 1 ไฟล์ · ภายใน {len(paths)} ไฟล์"
                button_text = "✓ คัดลอก ZIP แล้ว"
            else:
                copied = copy_file_paths(paths)
                label = f"{len(copied)} ไฟล์"
                button_text = f"✓ คัดลอกแล้ว {len(copied)} ไฟล์"
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            QMessageBox.warning(self, "คัดลอกไฟล์ไม่สำเร็จ", str(exc))
            return
        preserved_scroll = self.scroll.verticalScrollBar().value()
        button.setText(button_text)
        self.summary.setText(
            f"คัดลอกชุดที่ {group.index} ({group.start:04d}–{group.end:04d}) "
            f"จำนวน {label} · วางไฟล์ด้วย Ctrl+V"
        )
        QTimer.singleShot(
            0, lambda: self.scroll.verticalScrollBar().setValue(preserved_scroll)
        )

    def invalidate_preview(self):
        self._segments = ()
        self._preview_input = None
        self.save_button.setEnabled(False)
        self.paste_summary.setText("เนื้อหาเปลี่ยนแล้ว กรุณาตรวจหัวบทอีกครั้ง")
        self.preview_table.setRowCount(0)
        self.chapter_preview.clear()

    def preview_paste(self):
        contents = self.pasted_text.toPlainText()
        try:
            segments = parse_pasted_chapters(contents)
        except ValueError as exc:
            self.invalidate_preview()
            self.paste_summary.setText(str(exc))
            return
        self._segments = segments
        self._preview_input = contents
        self.preview_table.setRowCount(len(segments))
        for row, segment in enumerate(segments):
            for col, value in enumerate((
                f"{segment.number:04d}", segment.filename, str(segment.first_line),
            )):
                self.preview_table.setItem(row, col, QTableWidgetItem(value))
        self.preview_table.resizeColumnsToContents()
        missing = split_missing_numbers(segments)
        self.paste_summary.setText(
            f"ตรวจพบ {len(segments)} บท"
            + (f" · เลขบทขาด {len(missing)} บท เช่น {', '.join(str(i) for i in missing[:10])}"
               if missing else " · เลขบทต่อเนื่อง")
            + " · เลือกบทเพื่อตรวจเนื้อหาแล้วกดยืนยันบันทึก"
        )
        self.save_button.setEnabled(True)
        if segments:
            self.preview_table.selectRow(0)

    def show_preview_chapter(self):
        row = self.preview_table.currentRow()
        if 0 <= row < len(self._segments):
            self.chapter_preview.setPlainText(self._segments[row].text)
        else:
            self.chapter_preview.clear()

    def save_paste(self):
        if self.bound_mode and self._loaded_file_path is not None:
            try:
                current = self._loaded_file_path.stat()
                signature = (current.st_mtime_ns, current.st_size)
                if signature != self._loaded_file_signature:
                    QMessageBox.warning(self, "ต้นฉบับเปลี่ยนแปลง",
                                        "ไฟล์ต้นฉบับถูกแก้ไขหลังตรวจตัวอย่าง กรุณาอ่านไฟล์ใหม่ก่อนบันทึก")
                    self.save_button.setEnabled(False)
                    return
            except OSError as exc:
                QMessageBox.warning(self, "ไม่พบต้นฉบับ", str(exc))
                return
        if not self._segments or self._preview_input != self.pasted_text.toPlainText():
            self.invalidate_preview()
            return
        folder = Path(self.state.get("destination") or self.state.get("folder") or self.default_folder)
        if not folder.is_dir():
            QMessageBox.warning(self, "บันทึกไม่ได้", f"ไม่พบโฟลเดอร์ปลายทาง: {folder}")
            return
        try:
            conflicts = existing_chapter_targets(folder, self._segments)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "ตรวจไฟล์เดิมไม่สำเร็จ", str(exc))
            return
        mode = "skip"
        if conflicts:
            dialog = QMessageBox(self)
            dialog.setIcon(QMessageBox.Warning)
            dialog.setWindowTitle("พบเลขบทที่มีไฟล์แล้ว")
            dialog.setText(
                f"พบ {len(conflicts)} บทที่มีไฟล์อยู่แล้ว\n"
                "เลือกข้าม (ปลอดภัยที่สุด) หรือแทนที่โดยสำรองไฟล์เดิมก่อน"
            )
            skip = dialog.addButton("ข้ามบทที่มีอยู่", QMessageBox.AcceptRole)
            replace = dialog.addButton("สำรองแล้วแทนที่", QMessageBox.DestructiveRole)
            dialog.addButton("ยกเลิก", QMessageBox.RejectRole)
            dialog.setDefaultButton(skip)
            dialog.exec()
            if dialog.clickedButton() is replace:
                mode = "replace"
            elif dialog.clickedButton() is not skip:
                return
        else:
            if QMessageBox.question(
                self, "ยืนยันแยกไฟล์",
                f"สร้างไฟล์ TXT จำนวน {len(self._segments)} บทในโฟลเดอร์\n{folder}\n"
                "เนื้อหาต้นฉบับในช่องวางจะไม่ถูกลบ",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            ) != QMessageBox.Yes:
                return
        try:
            result = write_split_chapters(folder, self._segments, on_existing=mode)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "แยกไฟล์ไม่สำเร็จ", str(exc))
            return
        if not self.bound_mode:
            self.state["folder"] = str(folder)
        else:
            self._split_source_folder = folder
        self._update_labels()
        self._save()
        self.refresh()
        self.tabs.setCurrentIndex(0)
        message = f"สร้าง {result.written} ไฟล์ · ข้าม {result.skipped} บท"
        if result.backup_directory:
            message += f"\nสำรองไฟล์ที่แทนที่ไว้ใน {result.backup_directory}"
        QMessageBox.information(self, "แยกไฟล์เสร็จแล้ว", message)
