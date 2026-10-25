"""Two simple TXT-based vocabulary tools inside the existing novel workspace.

Reading, previewing, and selecting sources never mutate source files, export
records, translation steps, or the clipboard. Clipboard copy is user initiated.
"""
from __future__ import annotations

from datetime import datetime
import tempfile
import zipfile
from hashlib import sha256
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
    batch_folder_files, batch_stage_files, chapter_source_directory,
    source_by_id, source_score, suggest_source_id,
)
from .vocabulary_batches import (
    existing_chapter_targets, make_chapter_batches, parse_pasted_chapters,
    read_utf8_text, scan_chapter_files, split_missing_numbers, write_split_chapters,
)
from .batch_copy_history import (
    group_copy_status, load_history, record_copy, source_identity, source_revision,
)


class TxtVocabularyPage(QWidget):
    """Read-only TXT batch copying and explicit preview-then-save splitting."""

    def __init__(self, state: dict, changed, default_folder: Path, parent=None, *,
                 stage_reader=None, archive_cache_dir=None, repo=None, profile_id=None,
                 draft_reader=None, draft_writer=None):
        super().__init__(parent)
        self.changed = changed
        self.default_folder = Path(default_folder)
        self.archive_cache_dir = Path(archive_cache_dir) if archive_cache_dir is not None else (
            Path(tempfile.gettempdir()) / "NovelWorkflow" / "txt-vocabulary"
        )
        self.stage_reader = stage_reader
        self.repo, self.profile_id = repo, profile_id
        self.draft_writer = draft_writer
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
        self.state.setdefault("source_mode", "stage")
        self.state.setdefault("source_folder", "")
        if not self.state.get("draft") and draft_reader:
            try:
                self.state["draft"] = draft_reader() or ""
            except (OSError, ValueError, TypeError):
                self.state["draft"] = ""
        self._history = load_history(repo, profile_id, "vocabulary") if repo and profile_id else []
        self._source_identity = ""
        self._source_revision = ""
        self._draft_timer = QTimer(self)
        self._draft_timer.setSingleShot(True)
        self._draft_timer.setInterval(350)
        self._draft_timer.timeout.connect(self._flush_draft)
        self._restore_scroll_value = int(self.state.get("scroll", 0) or 0)
        self._copy_buttons = []
        self._display_references = None
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
        guide = QLabel("1  เลือกต้นฉบับ     →     2  กำหนดจำนวนบท     →     3  คัดลอกชุดที่ต้องการ")
        guide.setObjectName("mutedLabel")
        root.addWidget(guide)
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
        select_folder = QPushButton("เลือกโฟลเดอร์ TXT")
        select_folder.setObjectName("txtVocabularyChooseFolder")
        select_folder.clicked.connect(self.choose_folder)
        select_folder.setToolTip("เลือกโฟลเดอร์ที่มีไฟล์รายบท เช่น 0601.txt – 0629.txt")
        select_folder.setVisible(True)
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
        self.chapter_search.setText(str(self.state.get("chapter_search", "")))
        self.chapter_search.setClearButtonEnabled(True)
        self.chapter_search.returnPressed.connect(self.jump_to_chapter)
        self.chapter_search.textChanged.connect(lambda value: self._state_changed(chapter_search=value))
        jump.addWidget(self.chapter_search, 1)
        jump_button = QPushButton("ไปยังบท")
        jump_button.setObjectName("txtVocabularyJump")
        jump_button.clicked.connect(self.jump_to_chapter)
        jump.addWidget(jump_button)
        batch_layout.addLayout(jump)
        history_row = QHBoxLayout()
        history_row.addWidget(QLabel("แสดง"))
        self.history_filter = QComboBox()
        self.history_filter.setObjectName("txtVocabularyHistoryFilter")
        self.history_filter.addItem("ทั้งหมด", "all")
        self.history_filter.addItem("ยังไม่ได้คัดลอก", "new")
        self.history_filter.addItem("คัดลอกแล้ว", "copied")
        self.history_filter.addItem("ต้องตรวจใหม่", "review")
        filter_index = self.history_filter.findData(self.state.get("filter", "all"))
        self.history_filter.setCurrentIndex(max(0, filter_index))
        self.history_filter.currentIndexChanged.connect(self._filter_changed)
        history_row.addWidget(self.history_filter)
        self.last_button = QPushButton("กลับไปชุดล่าสุด")
        self.last_button.setObjectName("txtVocabularyLastCopied")
        self.last_button.clicked.connect(self._go_to_last_copied)
        history_row.addWidget(self.last_button)
        self.next_button = QPushButton("ไปชุดถัดไป")
        self.next_button.setObjectName("txtVocabularyNextUncopied")
        self.next_button.clicked.connect(self._go_to_next_uncopied)
        history_row.addStretch(1)
        batch_layout.addLayout(history_row)
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
        self.scroll.verticalScrollBar().valueChanged.connect(lambda value: self._state_changed(scroll=int(value)))
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
        self.pasted_text.setPlainText(self.state.get("draft", ""))
        self.pasted_text.textChanged.connect(self._draft_changed)
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
        source_r