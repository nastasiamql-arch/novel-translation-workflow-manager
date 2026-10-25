Warning: truncated output (original token count: 60637)
Total output lines: 4651

from __future__ import annotations

import shutil
import tempfile
import hashlib
import os
from datetime import date, datetime
from pathlib import Path
import subprocess

from PySide6.QtCore import QDir, QFileSystemWatcher, QEventLoop, QSize, Qt, QTimer, Signal, QThread
from PySide6.QtGui import QAction, QFontMetrics, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QDialog, QFileDialog, QFileSystemModel, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QProgressBar, QPushButton, QSizePolicy, QSplitter, QStackedWidget,
    QTabBar, QToolButton, QTreeView, QVBoxLayout, QWidget, QInputDialog, QComboBox, QTextEdit,
    QCheckBox, QProgressDialog, QScrollArea, QSpinBox, QMenu, QMainWindow,
)

from .models import LaunchTarget, StepFile, migrate_legacy_basic_workflow, migrate_legacy_vocabulary_step
from .auto_chapter_review import (
    is_original_source_document, is_auxiliary_document, scan_original_chapter_issues,
)
from .translation_progress import (
    daily_chapter_count, goal_progress, latest_context_chapter, completion_label, completion_tooltip, completed_chapter_count,
    sync_profile_context, read_context_chapter, reset_goal_progress,
    retranslation_preview, confirm_retranslation, undo_retranslation, retranslation_context_candidate, completed_chapters,
)
from .ui import ManagementActionsMixin
from .shell_components import NovelHeader, NavigationSidebar, ElidingLabel, EditorToolbar, MainPageStack
from .library_page import LibraryPage
from .profile_list import ReorderableProfileList
from .settings_page import SettingsPage
from .export_service import ExportService, daily_export_count, verified_goal_text
from .workspace_editor import EditorTabs, _stage_text_file, _cleanup_staged_text_file
from .recovery import commit_staged
from .storage import read_json, write_json
from .theme import theme_colors, editor_colors
from . import __version__
from .update_bootstrap import launch_update, read_update_result
from .updater import UpdateError, UpdateInfo, check_for_update, download_update
from .file_import import import_files_into_directory
from .vocabulary_batch_page import TxtVocabularyPage
from .translation_batch_page import TranslationBatchPage
from .vocabulary_source_binding import enabled_vocabulary_attachments
from .polish_history import PolishHistory, RangeRequired
from .polish_history_page import PolishHistoryPage, HistoryWorker


PROFILE_STATUSES = (
    ("translating", "กำลังแปล"),
    ("paused", "พักแปล"),
    ("caught_up", "ชนต้นฉบับแล้ว"),
    ("checking_web", "กำลังเช็กกับเว็บ"),
)


def _stage_bytes_file(destination: Path, data: bytes) -> Path:
    """Stage exact document bytes beside their destination for atomic replacement."""
    staged = None
    try:
        fd, name = tempfile.mkstemp(
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".part",
        )
        staged = Path(name)
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        return staged
    except OSError:
        _cleanup_staged_text_file(staged)
        raise


def _profile_status(profile):
    status = str(getattr(profile, "status", "") or "").strip()
    return status if status in {value for value, _label in PROFILE_STATUSES} else "translating"


def _profile_status_label(status):
    return dict(PROFILE_STATUSES).get(status, dict(PROFILE_STATUSES)["translating"])


class _UpdateCheckWorker(QThread):
    finished_check = Signal(object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.result = None
        self.error = None

    def run(self):
        try:
            self.result = check_for_update(__version__)
        except UpdateError as exc:
            self.error = str(exc)
        self.finished_check.emit(self.result, self.error)


class _UpdateDownloadWorker(QThread):
    progress = Signal(int)
    finished_download = Signal(object, object)

    def __init__(self, update: UpdateInfo, destination: Path, parent=None):
        super().__init__(parent)
        self.update = update
        self.destination = destination
        self.result = None
        self.error = None

    def run(self):
        try:
            self.result = download_update(
                self.update,
                self.destination,
                progress=self.progress.emit,
                cancelled=self.isInterruptionRequested,
                timeout=8,
            )
        except UpdateError as exc:
            self.error = str(exc)
        self.finished_download.emit(self.result, self.error)


class WorkflowStageButton(QPushButton):
    """Workflow action button; active state is styled without overpainting text."""

    def setWorkflowActive(self, active):
        self.setProperty("workflowActive", bool(active))
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()


class ElidingStatusLabel(QLabel):
    """Keep status text compact while making its full value available on hover."""

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._full_text = ""
        self.setFullText(text)

    def setFullText(self, text):
        self._full_text = str(text)
        self.setToolTip(self._full_text)
        self._update_elided_text()

    def fullText(self):
        return self._full_text

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_elided_text()

    def _update_elided_text(self):
        available = max(0, self.width() - 12)
        self.setText(QFontMetrics(self.font()).elidedText(
            self._full_text, Qt.ElideRight, available
        ))


class SubmitToast(QFrame):
    """Brief in-window notification shown after Submit completes successfully."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("submitToast")
        self.setFrameShape(QFrame.StyledPanel)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.message = QLabel(self)
        self.message.setWordWrap(True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 11, 16, 11)
        layout.addWidget(self.message, 1)
        self.undo_button = QPushButton("ย้อนกลับ")
        self.undo_button.clicked.connect(self._undo)
        layout.addWidget(self.undo_button)
        self.undo_callback = None
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.setInterval(5000)
        self.hide_timer.timeout.connect(self.hide)
        self.hide()

    def _undo(self):
        callback = self.undo_callback
        self.undo_callback = None
        if callback: callback()
        self.hide()

    def show_message(self, text, undo_callback=None):
        self.undo_callback = undo_callback
        self.undo_button.setVisible(undo_callback is not None)
        self.message.setText(str(text))
        appearance = getattr(getattr(self.parent(), "settings", None), "appearance", "Dark")
        colors = theme_colors(appearance)
        self.setStyleSheet(
            f"QFrame#submitToast {{ background:{colors['elevated']}; color:{colors['text']}; "
            f"border:0; border-bottom:2px solid {colors['accent']}; border-radius:0; }}"
            f"QLabel {{ color:{colors['text']}; background:transparent; }}"
        )
        self.setMaximumWidth(max(320, min(560, self.parent().width() - 40)))
        self.adjustSize()
        self.move(
            max(12, self.parent().width() - self.width() - 24),
            max(12, self.parent().height() - self.height() - 52),
        )
        self.show()
        self.raise_()
        self.hide_timer.start()


class WorkspacePage(QWidget):
    """One independent workspace for one novel profile."""

    def __init__(self, owner: "MainWindow", profile):
        super().__init__(owner)
        self.owner = owner
        self.profile_id = profile.id
        self.step_index = 0
        self._export_status_editor = None
        self._export_status_path = None
        self._export_binding_editor = None
        self._export_binding_path = None
        self._export_binding_allowed = False
        self._export_digest_editor = None
        self._export_digest_timer = QTimer(self)
        self._export_digest_timer.setSingleShot(True)
        self._export_digest_timer.setInterval(500)
        self._export_digest_timer.timeout.connect(self._confirm_export_digest)

        self.file_model = QFileSystemModel(self)
        self.file_model.setReadOnly(False)
        self.file_model.setFilter(QDir.AllEntries | QDir.NoDotAndDotDot)

        self.file_tree = QTreeView()
        self.file_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.file_tree.setObjectName("fileTree")
        self.file_tree.setModel(self.file_model)
        self.file_tree.setHeaderHidden(True)
        self.file_tree.setAnimated(True)
        self.file_tree.setIndentation(16)
        for column in (1, 2, 3):
            self.file_tree.hideColumn(column)
        self.file_tree.doubleClicked.connect(self._open_tree_index)

        self.editor = EditorTabs(
            font_size=owner.settings.editor_font_size,
            appearance=owner.settings.appearance,
            settings=profile.txt_export_settings,
            settings_callback=self._save_txt_export_settings,
            status_callback=lambda message: owner.statusBar().showMessage(message, 5000),
            context_path_callback=self._context_path_for_export,
            notification_callback=owner.show_submit_toast,
            export_service=ExportService(owner.repo, profile.id),
            export_success_callback=lambda chapter_range=None, pid=profile.id:
                owner.snapshot_export_for_review(pid, chapter_range),
        )
        self.editor.destructive_paste_callback = (
            lambda editor: owner._guard_destructive_paste(profile.id, editor)
        )
        self.steps = QListWidget()
        self.steps.setObjectName("workflowSteps")
        # Stage state is changed by the stage buttons' clicked handlers only.
        # The list's current row is presentation state and must not activate a
        # workflow stage when Qt updates it from pointer/focus navigation.
        self.steps.setSelectionMode(QAbstractItemView.NoSelection)
        self.steps.setSpacing(2)
        self.stage_buttons = []
        self.vocabulary_mode = False
        self.vocabulary_button = WorkflowStageButton("หาศัพท์")
        self.vocabulary_button.setObjectName("vocabularyButton")
        self.vocabulary_button.setWorkflowActive(False)
        self.vocabulary_button.setToolTip("คลิกเพื่อเลือกและคัดลอกไฟล์ขั้นตอนหาศัพท์ทันที · หรือใช้ COPY STEP / Ctrl+Shift+C")
        self.vocabulary_button.clicked.connect(
            lambda checked=False: self.owner.copy_named_stage(self.profile_id, "vocabulary")
        )
        self.files = QListWidget()
        self.files.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.files.setSpacing(1)
        self.files.setAccessibleName("ไฟล์ของขั้นตอนปัจจุบัน")
        self.files.itemDoubleClicked.connect(
            lambda item: self.owner.open_workflow_file(self.profile_id, item)
        )
        self.file_search = QLineEdit()
        self.file_search.setPlaceholderText("ค้นหาบทหรือไฟล์…")
        self.file_search.textChanged.connect(self.filter_files)

        self.sidebar = QFrame()
        self.sidebar.setObjectName("workflowSidebar")
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(10, 10, 10, 10)
        sidebar_layout.setSpacing(8)
        step_header = QHBoxLayout()
        sidebar_heading = QLabel("ขั้นตอนการแปล")
        sidebar_heading.setObjectName("sectionHeading")
        step_header.addWidget(sidebar_heading, 1)
        self.copy_step_button = QPushButton("COPY ZIP" if self.owner.settings.copy_files_as_zip else "COPY STEP")
        self.copy_step_button.setObjectName("copyStepButton")
        self.copy_step_button.setToolTip("รวมไฟล์ทั้งหมดของขั้นตอนที่เลือกเป็น ZIP เดียว · Ctrl+Shift+C"
                                     if self.owner.settings.copy_files_as_zip else
                                     "คัดลอกไฟล์ของขั้นตอนที่เลือก · Ctrl+Shift+C")
        self.copy_step_button.clicked.connect(
            lambda checked=False: self.owner.copy_step()
        )
        step_header.addWidget(self.copy_step_button)
        sidebar_layout.addLayout(step_header)
        history_row = QHBoxLayout()
        self.history_button = QPushButton('ประวัติ')
        self.history_button.clicked.connect(lambda: self.owner.open_polish_history())
        history_row.addWidget(self.history_button)
        self.save_for_review_button = QPushButton('บันทึกไว้รอตรวจ')
        self.save_for_review_button.clicked.connect(lambda: self.owner.save_for_review())
        history_row.addWidget(self.save_for_review_button)
        self.history_range = QLineEdit()
        self.history_range.setPlaceholderText('ช่วงบท เช่น 6-10')
        self.history_range.setAccessibleName('ช่วงบทสำหรับประวัติใหม่')
        self.history_range.setToolTip('กรอกเมื่อไม่สามารถยืนยันช่วงบทจากไฟล์เนื้อหาได้ · ไม่อ่านช่วงบทจาก Context')
        self.history_range.setMinimumWidth(0)
        history_row.addWidget(self.history_range, 1)
        sidebar_layout.addLayout(history_row)
        sidebar_layout.addWidget(self.vocabulary_button)
        self.txt_vocabulary_shortcut = QPushButton("จากไฟล์ TXT · แบ่งชุด / แยกบท")
        self.txt_vocabulary_shortcut.setObjectName("txtVocabularyShortcut")
        self.txt_vocabulary_shortcut.clicked.connect(
            lambda checked=False: self.owner.open_txt_vocabulary(self.profile_id)
        )
        sidebar_layout.addWidget(self.txt_vocabulary_shortcut)
        self.translation_batch_shortcut = QPushButton("แปลหลายบท")
        self.translation_batch_shortcut.setObjectName("translationBatchShortcut")
        self.translation_batch_shortcut.clicked.connect(
            lambda checked=False: self.owner.open_translation_batches(self.profile_id)
        )
        sidebar_layout.addWidget(self.translation_batch_shortcut)
        sidebar_layout.addWidget(self.steps, 2)
        files_heading = QLabel("ไฟล์ของขั้นตอนปัจจุบัน")
        files_heading.setObjectName("sectionHeading")
        sidebar_layout.addWidget(files_heading)
        sidebar_layout.addWidget(self.file_search)
        sidebar_layout.addWidget(self.files, 3)
        self.explorer_toggle = QToolButton()
        self.explorer_toggle.setText("ไฟล์ทั้งหมด  ▾")
        self.explorer_toggle.setCheckable(True)
        self.explorer_toggle.setChecked(False)
        self.explorer_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.explorer_toggle.toggled.connect(self.file_tree.setVisible)
        sidebar_layout.addWidget(self.explorer_toggle)
        self.file_tree.setVisible(False)
        sidebar_layout.addWidget(self.file_tree, 2)
        file_actions = QGridLayout()
        for index, (label, callback) in enumerate((
            ("ไฟล์ใหม่", self.new_file), ("โฟลเดอร์ใหม่", self.new_folder),
            ("เปลี่ยนชื่อ", self.rename_selected), ("ลบ", self.delete_selected),
        )):
            button = QPushButton(label)
            button.clicked.connect(callback)
            file_actions.addWidget(button, index // 2, index % 2)
        sidebar_layout.addLayout(file_actions)

        self.sidebar_toggle = QToolButton()
        self.sidebar_toggle.setText("☰")
        self.sidebar_toggle.setAccessibleName("ซ่อนหรือแสดงแถบด้านข้าง")
        self.sidebar_toggle.setToolTip("ซ่อน/แสดงแถบด้านข้าง")
        self.sidebar_toggle.clicked.connect(self.toggle_sidebar)
        self.editor_header = EditorToolbar()
        self.editor_header.setObjectName("editorHeader")
        header_layout = QHBoxLayout(self.editor_header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        self.breadcrumb = ElidingLabel()
        self.breadcrumb.setText("เลือกไฟล์จากแถบด้านข้าง")
        self.breadcrumb.setMinimumWidth(0)
        self.breadcrumb.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.breadcrumb.setObjectName("mutedLabel")
        header_layout.addWidget(self.sidebar_toggle)
        header_layout.addWidget(self.breadcrumb, 1)
        self.pause_profile_button = QToolButton(self.editor_header)
        self.pause_profile_button.setText("พักแปล")
        self.pause_profile_button.setToolTip("ย้ายเรื่องนี้ไปชั้นพักแปล")
        self.pause_profile_button.clicked.connect(
            lambda checked=False: self.owner.set_profile_status(self.profile_id, "paused")
        )
        self.pause_profile_button.hide()
        self.caught_up_profile_button = QToolButton(self.editor_header)
        self.caught_up_profile_button.setText("ชนต้นฉบับแล้ว")
        self.caught_up_profile_button.setToolTip("ย้ายเรื่องนี้ไปชั้นชนต้นฉบับแล้ว")
        self.caught_up_profile_button.clicked.connect(
            lambda checked=False: self.owner.set_profile_status(self.profile_id, "caught_up")
        )
        self.caught_up_profile_button.hide()
        self.checking_web_profile_button = QToolButton(self.editor_header)
        self.checking_web_profile_button.setText("เช็กกับเว็บ")
        self.checking_web_profile_button.setToolTip("ย้ายเรื่องนี้ไปหมวดกำลังเช็กกับเว็บ")
        self.checking_web_profile_button.clicked.connect(
            lambda checked=False: self.owner.set_profile_status(self.profile_id, "checking_web")
        )
        self.checking_web_profile_button.hide()
        self.resume_profile_button = QToolButton(self.editor_header)
        self.resume_profile_button.setText("กลับไปแปล")
        self.resume_profile_button.setToolTip("ย้ายเรื่องนี้กลับไปชั้นกำลังแปล")
        self.resume_profile_button.clicked.connect(
            lambda checked=False: self.owner.set_profile_status(self.profile_id, "translating")
        )
        self.resume_profile_button.hide()
        self.context_button = QToolButton(self.editor_header)
        self.context_button.setText("Context")
        self.context_button.setToolTip("เลือกไฟล์ Context ที่ติดตามความคืบหน้า")
        self.context_button.clicked.connect(self._choose_context)
        self.context_button.hide()
        self.update_context_button = QToolButton(self.editor_header)
        self.update_context_button.setText("Export")
        self.update_context_button.setToolTip("ส่งออก Translator เป็น TXT และอัปเดต Context")
        self.update_context_button.setAccessibleName("ส่งออก Translator เป็น TXT และอัปเดต Context")
        self.update_context_button.clicked.connect(
            lambda: self.owner.update_context_from_translator(self)
        )
        self.update_context_button.hide()
        self.chapter_number_button = QToolButton(self.editor_header)
        self.chapter_number_button.setText("ตรวจเลขบท")
        self.chapter_number_button.setObjectName("chapterNumberButton")
        self.chapter_number_button.setToolTip("ตรวจและแก้เลขหัวบทในไฟล์ต้นฉบับที่เปิดอยู่ · ไม่มี Export")
        self.chapter_number_button.setAccessibleName("ตรวจเลขบทต้นฉบับ")
        self.chapter_number_button.clicked.connect(self.inspect_chapter_numbers)
        self.chapter_number_button.hide()
        header_layout.addWidget(self.chapter_number_button)
        header_layout.addWidget(self.update_context_button)
        self.export_status_label = QLabel("ยังไม่ทราบสถานะการส่งออก", self.editor_header)
        self.export_status_label.setObjectName("exportStatusLabel")
        self.export_status_label.setMinimumWidth(132)
        self.export_status_label.hide()
        header_layout.addWidget(self.export_status_label)
        find_button = QToolButton()
        find_button.setText("ค้นหา")
        find_button.setAccessibleName("ค้นหาในไฟล์ปัจจุบัน")
        find_button.setToolTip("ค้นหาในไฟล์ปัจจุบัน  ·  Ctrl+H")
        find_button.clicked.connect(self.editor.show_find)
        header_layout.addWidget(find_button)
        decrease_font = QToolButton()
        decrease_font.setText("A−")
        decrease_font.setAccessibleName("ลดขนาดตัวอักษร")
        decrease_font.setToolTip("ลดขนาดตัวอักษร  ·  Ctrl+-")
        decrease_font.clicked.connect(lambda: self.owner.adjust_editor_font_size(-1))
        header_layout.addWidget(decrease_font)
        self.font_size_label = QLabel(f"{self.editor.font_size():g}")
        self.font_size_label.setObjectName("mutedLabel")
        self.font_size_label.setMinimumWidth(24)
        self.font_size_label.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(self.font_size_label)
        increase_font = QToolButton()
        increase_font.setText("A+")
        increase_font.setAccessibleName("เพิ่มขนาดตัวอักษร")
        increase_font.setToolTip("เพิ่มขนาดตัวอักษร  ·  Ctrl++")
        increase_font.clicked.connect(lambda: self.owner.adjust_editor_font_size(1))
        header_layout.addWidget(increase_font)
        reset_font = QToolButton()
        reset_font.setText("A")
        reset_font.setAccessibleName("คืนขนาดตัวอักษรเริ่มต้น")
        reset_font.setToolTip("คืนขนาดตัวอักษรเริ่มต้น")
        reset_font.clicked.connect(lambda: self.owner.set_editor_font_size(11.0))
        reset_font.hide()
        self.more_menu = QMenu(self)
        for button in (self.pause_profile_button, self.caught_up_profile_button, self.checking_web_profile_button, self.resume_profile_button, self.context_button, reset_font):
            self.more_menu.addAction(button.text(), button.click)
        # These commands have no on-screen toolbar widgets: creating orphan
        # QToolButtons without adding them to a layout makes Qt paint both at
        # (0, 0), overlapping Thai labels and the sidebar toggle.
        self.more_menu.addAction(
            "ตรวจ Context และเริ่มแปลใหม่",
            lambda: self.owner.review_context_retranslation(self.profile_id),
        )
        self.more_menu.addAction(
            "คืนสถานะย้อนแปล",
            lambda: self.owner.undo_context_retranslation(self.profile_id),
        )
        self.more_menu.addAction("แผนการแปล", lambda: self.owner.open_story_planner(self.profile_id))
        self.more_menu.addAction("เปิดรายการของเรื่อง", self.owner.launch_profile)
        self.more_menu.addAction("ประวัติและกู้คืนไฟล์", self.show_recovery)
        more = QToolButton(); more.setText("..."); more.setAccessibleName("คำสั่งเพิ่มเติม")
        more.setMenu(self.more_menu); more.setPopupMode(QToolButton.InstantPopup)
        header_layout.addWidget(more)
        self.undo_button = QToolButton(); self.undo_button.setText("เลิกทำ"); self.undo_button.setToolTip("เลิกทำ · Ctrl+Z"); self.undo_button.setAccessibleName("เลิกทำ")
        self.redo_button = QToolButton(); self.redo_button.setText("ทำซ้ำ"); self.redo_button.setToolTip("ทำซ้ำ · Ctrl+Y / Ctrl+Shift+Z"); self.redo_button.setAccessibleName("ทำซ้ำ")
        self.undo_button.clicked.connect(lambda: self.editor._current_editor().undo())
        self.redo_button.clicked.connect(lambda: self.editor._current_editor().redo())
        header_layout.insertWidget(1, self.undo_button); header_layout.insertWidget(2, self.redo_button)
        self.editor.tabs.currentChanged.connect(self.bind_history)
        self.editor.tabs.currentChanged.connect(lambda _index: self.refresh_context_update_button())
        self.refresh_context_update_button()
        self.bind_history()
        self.more_menu.addAction("ค้นหา · Ctrl+H", self.editor.show_find)
        self.more_menu.addAction("ลดขนาดตัวอักษร", lambda: self.owner.adjust_editor_font_size(-1))
        self.more_menu.addAction("เพิ่มขนาดตัวอักษร", lambda: self.owner.adjust_editor_font_size(1))
        self.editor_header.overflow_controls = [(self.font_size_label, 500), (find_button, 420), (decrease_font, 340), (increase_font, 340)]
        self.update_profile_status(_profile_status(profile))
        editor_layout = QVBoxLayout()
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(3)
        self.novel_header = NovelHeader(owner.repo)
        self.novel_header.refresh(profile)
        self.novel_header.goal_edit.clicked.connect(
            lambda checked=False: owner.edit_workspace_goal(self.profile_id)
        )
        self.novel_header.goal_reset.clicked.connect(
            lambda checked=False: owner.reset_workspace_goal(self.profile_id)
        )
        self.novel_header.close_button.clicked.connect(
            lambda: self.owner._close_novel_tab(self.profile_id))
        editor_layout.addWidget(self.novel_header)
        editor_layout.addWidget(self.editor_header)
        self.vocabulary_source_bar = QWidget()
        source_row = QHBoxLayout(self.vocabulary_source_bar)
        source_row.setContentsMargins(12, 3, 12, 3)
        source_row.addWidget(QLabel("หาคำศัพท์ · เลือกวิธีเตรียมเนื้อหา"))
        self.manual_source_button = QPushButton("วางเนื้อหาเอง")
        self.manual_source_button.setObjectName("manualVocabularySource")
        self.manual_source_button.setCheckable(True)
        self.manual_source_button.clicked.connect(
            lambda checked=False: self.set_vocabulary_source("manual")
        )
        source_row.addWidget(self.manual_source_button)
        self.txt_source_button = QPushButton("จากไฟล์ TXT")
        self.txt_source_button.setObjectName("txtVocabularySource")
        self.txt_source_button.setCheckable(True)
        self.txt_source_button.clicked.connect(
            lambda checked=False: self.set_vocabulary_source("files")
        )
        source_row.addWidget(self.txt_source_button)
        source_row.addStretch(1)
        editor_layout.addWidget(self.vocabulary_source_bar)
        self.vocabulary_source_mode = str(
            owner.settings.vocabulary_txt_profiles.get(profile.id, {}).get("mode", "manual")
        )
        default_source = (
            Path(profile.main_folder).expanduser() / "source"
            if profile.main_folder.strip() else owner.repo.profile_dir(profile.id) / "source"
        )
        self.txt_vocabulary_page = None
        self.translation_batch_page = None
        self.editor_content_stack = QStackedWidget()
        self.editor_content_stack.addWidget(self.editor)
        editor_layout.addWidget(self.editor_content_stack, 1)
        self.sync_vocabulary_source()
        editor_host = QWidget()
        editor_host.setLayout(editor_layout)

        self.workspace_splitter = QSplitter(Qt.Horizontal)
        self.workspace_splitter.setChildrenCollapsible(True)
        self.workspace_splitter.addWidget(self.sidebar)
        self.workspace_splitter.addWidget(editor_host)
        self.workspace_splitter.setStretchFactor(0, 0)
        self.workspace_splitter.setStretchFactor(1, 1)
        self.workspace_splitter.setSizes([290, 900])
        self.workspace_splitter.splitterMoved.connect(self._remember_sidebar_width)

        self.goal_panel = QFrame()
        self.goal_panel.setObjectName("goalPanel")
        goal_layout = QVBoxLayout(self.goal_panel)
        self.goal_label = QLabel("เป้าหมายวันนี้")
        self.goal_label.setWordWrap(True)
        self.goal_bar = QProgressBar()
        self.goal_bar.setMinimumHeight(15)
        self.goal_bar.setTextVisible(False)
        self.latest_chapter_label = QLabel("บทล่าสุดจาก Context")
        self.latest_chapter_label.setObjectName("mutedLabel")
        goal_layout.addWidget(self.goal_label)
        goal_layout.addWidget(self.goal_bar)
        goal_layout.addWidget(self.latest_chapter_label)
        goal_layout.addStretch(1)

        self.workflow_page = QWidget()
        workflow_layout = QVBoxLayout(self.workflow_page)
        workflow_layout.setContentsMargins(0, 0, 0, 0)
        workflow_layout.addWidget(self.workspace_splitter)
        self.files_page = self.workflow_page

        self.content_stack = QStackedWidget()
        self.content_stack.addWidget(self.workflow_page)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.workspace_sections = QTabBar(self)
        self.workspace_sections.setObjectName("workspaceSections")
        self.workspace_sections.setAccessibleName("ส่วนต่าง ๆ ของนิยายปัจจุบัน")
        self.workspace_sections.setExpanding(False)
        self.workspace_sections.setUsesScrollButtons(True)
        for title in ("แปลนิยาย", "แผนการแปล", "ไฟล์และคำศัพท์",
                      "แปลหลายบท", "ส่งออกไฟล์", "ความคืบหน้า", "ประวัติการเกลา"):
            self.workspace_sections.addTab(title)
        layout.addWidget(self.workspace_sections)
        layout.addWidget(self.content_stack, 1)
        self.workspace_sections.currentChanged.connect(self._open_section)

        self.configure(profile)
        self.set_mode(0)

    def _open_section(self, index):
        """Keep the editor in place and route novel-specific tools by ID."""
        if index < 0:
            return
        if index == 0:
            self.editor_content_stack.setCurrentWidget(self.editor)
        elif index == 1:
            self.owner.open_story_planner(self.profile_id)
        elif index == 2:
            self.owner.open_novel_resources(self.profile_id)
        elif index == 3:
            self.owner.open_translation_batches(self.profile_id)
        elif index == 4:
            self.editor_content_stack.setCurrentWidget(self.editor)
            self.editor.tabs.setCurrentWidget(self.editor.export_tab)
        elif index == 5:
            self.owner.open_novel_progress(self.profile_id)
        elif index == 6:
            self.owner.open_polish_history()
        if index not in (0, 3, 4):
            self.workspace_sections.blockSignals(True)
            self.workspace_sections.setCurrentIndex(0)
            self.workspace_sections.blockSignals(False)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        sizes = self.workspace_splitter.sizes()
        if self.width() < 900 and sizes[0] > 220:
            self.workspace_splitter.setSizes([220, max(210, self.width() - 220)])

    def bind_history(self, *_args):
        editor = self.editor._current_editor()
        if editor is None: return
        if not getattr(editor, "_history_bound", False):
            editor.undoAvailable.connect(lambda _value: self.refresh_history())
            editor.redoAvailable.connect(lambda _value: self.refresh_history())
            editor._history_bound = True
        self.refresh_history()

    def _source_file_eligible(self, path):
        """Do not expose Chinese-source renumbering for Translator or Context."""
        if path is None:
            return False
        try:
            path = Path(path).expanduser().resolve()
            if not path.is_file() or path.suffix.casefold() not in {".txt", ".md", ".markdown"}:
                return False
            if is_auxiliary_document(path):
                return False
            profile = next(
                (item for item in self.owner.repo.list_profiles() if item.id == self.profile_id),
                None,
            )
            if profile is None:
                return False
            if profile.context_path and path == Path(profile.context_path).expanduser().resolve():
                return False
            if path.name.casefold().startswith(("context.", "glossary.", "vocabulary.")):
                return False
            return True
        except (OSError, ValueError, TypeError):
            return False

    def inspect_chapter_numbers(self):
        editor = self.editor._current_editor()
        path = self.editor._path(editor) if editor else None
        if not self._source_file_eligible(path):
            QMessageBox.warning(self, "ตรวจเลขบทไม่ได้", "เปิดไฟล์ต้นฉบับ TXT/MD ก่อน")
            return
        from .chapter_numbering_dialog import ChapterNumberDialog
        dialog = ChapterNumberDialog(self, editor, Path(path))
        if not dialog.headings:
            QMessageBox.information(
                self, "ไม่พบหัวบท",
                "ไฟล์นี้ไม่มีหัวบทที่รองรับ เช่น 第430章, 第四百三十章, Chapter 430"
            )
            return
        if dialog.exec() == QDialog.Accepted and self.owner.profile and self.owner.profile.id == self.profile_id:
            self.owner._set_chapter_pending(self.owner.profile, self, Path(path), False)

    def refresh_context_update_button(self):
        editor = self.editor._current_editor()
        path = self.editor._path(editor) if editor else None
        allowed = bool(
            path is not None
            and self.owner.profile is not None
            and self.owner.profile.id == self.profile_id
            and self.owner._translator_profile_for_path(self.profile_id, path)
        )
        if allowed and not getattr(editor, "_export_status_changed_bound", False):
            editor.textChanged.connect(lambda e=editor: self.refresh_export_status(e, verified=True))
            editor._export_status_changed_bound = True
        chapter_allowed = bool(
            path and self.owner.profile and self.owner.profile.id == self.profile_id
            and self.owner._auto_original_source_eligible(self.owner.profile, self, path)
        )
        self.chapter_number_button.setVisible(chapter_allowed)
        pending = bool(
            chapter_allowed and
            str(Path(path).resolve()) in self.owner.profile.chapter_number_pending_files
        )
        self.chapter_number_button.setText(
            "ตรวจเลขบท • รอตรวจ" if pending else "ตรวจเลขบท"
        )
        self.chapter_number_button.setToolTip(
            "มีบทใหม่รอตรวจ · กดเพื่อตรวจเลขบทเอง" if pending
            else "ตรวจและแก้เลขหัวบทในต้นฉบับ · ไม่มี Export"
        )
        self.update_context_button.setVisible(allowed)
        self.export_status_label.setVisible(allowed)
        self._export_binding_editor = editor
        self._export_binding_path = self.owner._export_path_key(path) if path else None
        self._export_binding_allowed = allowed
        self._export_status_editor = editor if allowed else None
        self._export_status_path = self.owner._export_path_key(path) if allowed else None
        self.refresh_export_status(editor if allowed else None, verified=allowed)

    def refresh_export_status(self, editor=None, *, verified=False):
        if editor is None:
            editor = self.editor._current_editor()
        path = self.editor._path(editor) if editor else None
        key = self.owner._export_path_key(path) if path else None
        cached = editor is self._export_binding_editor and key == self._export_binding_path
        if not verified and not cached:
            allowed = bool(path and self.owner._translator_profile_for_path(self.profile_id, path))
            self._export_binding_editor = editor
            self._export_binding_path = key
            self._export_binding_allowed = allowed
        allowed = verified or (cached and self._export_binding_allowed)
        if not allowed or path is None:
            self._export_status_editor = None
            self._export_status_path = None
            self.export_status_label.hide()
            return
        self._export_status_editor = editor
        self._export_status_path = key
        status = self.owner._translator_export_status(self.profile_id, path, editor)
        self.export_status_label.setText({
            "exported": "Exported",
            "not_exported": "Not Exported",
            "unknown": "Export Status Unknown",
        }[status])
        colors = theme_colors(self.owner.settings.appearance)
        if status == "not_exported":
            foreground, background = colors["warning"], colors["surface2"]
        elif status == "exported":
            foreground, background = colors["success"], colors["surface"]
        else:
            foreground, background = colors["muted"], colors["surface"]
        self.export_status_label.setStyleSheet(
            f"QLabel#exportStatusLabel {{ color:{foreground}; background:{background}; "
            "border:1px solid " + colors["border"] + "; border-radius:3px; padding:2px 6px; }}"
        )
        self.export_status_label.show()
        if (self.editor._dirty(editor) and status != "exported"
                and editor.toPlainText() != editor.property('documentSavedText')):
            self.owner._mark_export_pending(self.profile_id, path)
            self._export_digest_editor = editor
            self._export_digest_timer.start()
        else:
            self._export_digest_timer.stop()
            if self._export_digest_editor is editor:
                self._export_digest_editor = None

    def _confirm_export_digest(self):
        editor = self._export_digest_editor
        self._export_digest_editor = None
        if editor is None:
            return
        path = self.editor._path(editor)
        if path is not None:
            self.owner._confirm_exported_content(self.profile_id, path, editor)
        self.refresh_export_status()

    def refresh_history(self):
        editor = self.editor._current_editor()
        self.undo_button.setEnabled(bool(editor and editor.document().isUndoAvailable()))
        self.redo_button.setEnabled(bool(editor and editor.document().isRedoAvailable()))

    def show_recovery(self):
        from .recovery import list_backups, restore_backup
        editor = self.editor._current_editor()
        path = self.editor._path(editor)
        if path is None:
            path = self._context_path_for_export()
        if path is None: return
        path = Path(path).expanduser().resolve()
        context = self._context_path_for_export()
        profile_for_context = None
        documents = [(path, None)]
        if context is not None and Path(context).expanduser().resolve() == path:
            profile_for_context = self.profile_id
            documents = [(path, profile_for_context)]
        if self.owner._translator_profile_for_path(self.profile_id, path):
            if context is not None:
                context = Path(context).expanduser().resolve()
                if context != path:
                    documents.append((context, self.profile_id))
        entries = [
            (document, backup)
            for document, profile_id in documents
            for backup in list_backups(document, profile_id=profile_id)
        ]
        if not entries:
            QMessageBox.information(self, "History", "ยังไม่มีไฟล์สำรองสำหรับเอกสารนี้")
            return
        labels = [f"{backup.name} — {document}" for document, backup in entries]
        selected, ok = QInputDialog.getItem(self, "กู้ไฟล์", str(path), labels, 0, False)
        if ok:
            if QMessageBox.question(self, "กู้ไฟล์", "แทนที่เอกสารด้วยไฟล์สำรองที่เลือก? เอกสารปัจจุบันจะถูกสำรองไว้", QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes: return
            try:
                destination, backup = next(
                    (document, backup)
                    for document, backup in entries
                    if f"{backup.name} — {document}" == selected
                )
                selected_profile = next(
                    profile_id for document, profile_id in documents
                    if document == destination
                )
                restore_backup(destination, backup, profile_id=selected_profile)
                self.editor.apply_external_update(destination, destination.read_text(encoding="utf-8-sig"))
                self.owner.refresh_translation_progress()
            except OSError as exc: QMessageBox.warning(self, "กู้ไฟล์ไม่ได้", str(exc))

    def _save_txt_export_settings(self):
        profile = next(
            (item for item in self.owner.repo.list_profiles() if item.id == self.profile_id),
            None,
        )
        if profile is None:
            return
        profile.txt_export_settings = self.editor.export_tab.settings
        self.owner.repo.save_profile(profile)

    def _context_path_for_export(self):
        profile = next(
            (item for item in self.owner.repo.list_profiles() if item.id == self.profile_id),
            None,
        )
        if profile is None or not profile.context_path:
            return None
        return Path(profile.context_path).expanduser()

    def update_profile_status(self, status):
        self.pause_profile_button.setEnabled(status != "paused")
        self.caught_up_profile_button.setEnabled(status != "caught_up")
        self.checking_web_profile_button.setEnabled(status != "checking_web")
        self.resume_profile_button.setEnabled(status != "translating")
        self.resume_profile_button.hide()

    def configure(self, profile):
        root = (
            Path(profile.main_folder).expanduser()
            if profile.main_folder.strip()
            else self.owner.repo.profile_dir(profile.id)
        )
        if not root.is_dir():
            root = self.owner.repo.profile_dir(profile.id)
        self.root_path = root.resolve()
        root_index = self.file_model.setRootPath(str(self.root_path))
        self.file_tree.setRootIndex(root_index)
        self.file_tree.setToolTip(str(self.root_path))

    def _choose_context(self):
        self.owner.set_context_file()
        self.owner._update_context_button(self)

    def set_mode(self, index):
        self.content_stack.setCurrentIndex(0)

    def _ensure_txt_vocabulary_page(self):
        """Create expensive batch controls only when requested."""
        if self.txt_vocabulary_page is None:
            profile = next((p for p in self.owner.ps_list if p.id == self.profile_id), None)
            if profile is None:
                return None
            default_source = (
                Path(profile.main_folder).expanduser() / "source"
                if profile.main_folder.strip() else self.owner.repo.profile_dir(profile.id) / "source"
            )
            page = TxtVocabularyPage(
                self.owner.settings.vocabulary_txt_profiles.get(profile.id, {}),
                lambda state: self.owner.save_txt_vocabulary_state(profile.id, state),
                default_source,
                stage_reader=lambda pid=profile.id, fallback=profile: enabled_vocabulary_attachments(
                    self.owner.repo, self.owner.assembler,
                    self.owner.profile if self.owner.profile and self.owner.profile.id == pid else fallback,
                ),
                archive_cache_dir=self.owner.repo.root / "cache" / "clipboard" / "txt-vocabulary" / profile.id,
            )
            self.txt_vocabulary_page = page
            self.editor_content_stack.addWidget(page)
        return self.txt_vocabulary_page

    def open_translation_batches(self):
        """Open the independent view; stage buttons and COPY STEP stay unchanged."""
        if self.translation_batch_page is None:
            pid = self.profile_id
            self.translation_batch_page = TranslationBatchPage(
                self.owner.repo,
                lambda: next((p for p in self.owner.ps_list if p.id == pid), None),
                self.owner.assembler,
                self.owner.settings.translation_batch_profiles.get(pid, {}),
                lambda state: self.owner.save_translation_batch_state(pid, state),
                lambda: self.sync_vocabulary_source(),
                self,
            )
            self.editor_content_stack.addWidget(self.translation_batch_page)
        self.editor_content_stack.setCurrentWidget(self.translation_batch_page)
        return self.translation_batch_page

    def set_vocabulary_source(self, mode):
        if mode not in ("manual", "files"):
            return
        previous_mode = self.vocabulary_source_mode
        had_page = self.txt_vocabulary_page is not None
        self.vocabulary_source_mode = mode
        page = self._ensure_txt_vocabulary_page() if mode == "files" else self.txt_vocabulary_page
        if page is not None:
            page.state["mode"] = mode
        if page is not None:
            self.owner.save_txt_vocabulary_state(self.profile_id, page.state)
        self.sync_vocabulary_source()
        # The TXT page already scans while being created. Reopening an existing
        # page should reuse its rows; explicit Refresh remains available.
        if mode == "files" and page is not None and had_page and previous_mode != mode:
            page.refresh()

    def sync_vocabulary_source(self):
        self.vocabulary_source_bar.setVisible(self.vocabulary_mode)
        self.manual_source_button.setChecked(self.vocabulary_source_mode != "files")
        self.txt_source_button.setChecked(self.vocabulary_source_mode == "files")
        show_files = self.vocabulary_mode and self.vocabulary_source_mode == "files"
        if show_files:
            self._ensure_txt_vocabulary_page()
        self.editor_content_stack.setCurrentWidget(self.txt_vocabulary_page if show_files else self.editor)

    def filter_files(self, query):
        query = query.strip().casefold()
        for index in range(self.files.count()):
            item = self.files.item(index)
            item.setHidden(bool(query) and query not in item.text().casefold())

    def toggle_sidebar(self):
        sizes = self.workspace_splitter.sizes()
        sidebar_width = sizes[0] if sizes else 0
        if sidebar_width > 0:
            self.owner.settings.sidebar_width = sidebar_width
            self.owner.settings.sidebar_visible = False
            self.workspace_splitter.setSizes([
                0, max(1, sum(sizes))
            ])
        else:
            self.owner.settings.sidebar_visible = True
            self.workspace_splitter.setSizes([
                max(220, int(self.owner.settings.sidebar_width or 290)),
                1000,
            ])
        self.owner.repo.save_settings(self.owner.settings)

    def _remember_sidebar_width(self, _position, index):
        sizes = self.workspace_splitter.sizes()
        if index == 1 and len(sizes) == 2 and sizes[0] > 0:
            self.owner.settings.sidebar_width = sizes[0]

    def selected_path(self):
        index = self.file_tree.currentIndex()
        if not index.isValid():
            return self.root_path
        return Path(self.file_model.filePath(index))

    def selected_directory(self):
        path = self.selected_path()
        return path if path.is_dir() else path.parent

    def _open_tree_index(self, index):
        path = Path(self.file_model.filePath(index))
        if path.is_file():
            if self.editor.open_file(path):
                profile = next((item for item in self.owner.ps_list if item.id == self.profile_id), None)
                step_name = (
                    profile.vocabulary_step.name if profile and self.vocabulary_mode
                    else profile.workflow.steps[self.step_index].name
                    if profile and self.step_index < len(profile.workflow.steps) else ""
                )
                self.breadcrumb.setText(
                    f"{profile.name}  ›  {step_name}  ›  {path.name}" if profile else path.name
                )

    def new_file(self):
        folder = self.selected_directory()
        name, ok = QInputDialog.getText(
            self, "ไฟล์ใหม่", "ชื่อไฟล์ (เช่น note.md):"
        )
        if not ok or not name.strip():
            return
        path = folder / name.strip()
        if path.exists():
            QMessageBox.warning(self, "มีไฟล์นี้แล้ว", str(path))
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")
            self.editor.open_file(path)
        except OSError as exc:
            QMessageBox.warning(self, "สร้างไฟล์ไม่ได้", str(exc))

    def new_folder(self):
        folder = self.selected_directory()
        name, ok = QInputDialog.getText(self, "โฟลเดอร์ใหม่", "ชื่อโฟลเดอร์:")
        if not ok or not name.strip():
            return
        try:
            (folder / name.strip()).mkdir()
        except OSError as exc:
            QMessageBox.warning(self, "สร้างโฟลเดอร์ไม่ได้", str(exc))

    def rename_selected(self):
        path = self.selected_path()
        if path == self.root_path:
            return
        name, ok = QInputDialog.getText(
            self, "เปลี่ยนชื่อ", "ชื่อใหม่:", text=path.name
        )
        if not ok or not name.strip() or name.strip() == path.name:
            return
        destination = path.with_name(name.strip())
        if destination.exists():
            QMessageBox.warning(self, "มีชื่อนี้แล้ว", str(destination))
            return
        try:
            was_file = path.is_file()
            path.rename(destination)
            if was_file:
                self.editor.rename_path(path, destination)
        except OSError as exc:
            QMessageBox.warning(self, "เปลี่ยนชื่อไม่ได้", str(exc))

    def delete_selected(self):
        path = self.selected_path()
        if path == self.root_path:
            return
        if QMessageBox.question(
            self, "ลบ", f"ลบ {path.name} ถาวรหรือไม่?"
        ) != QMessageBox.Yes:
            return
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                self.editor.close_path(path)
                path.unlink()
        except OSError as exc:
            QMessageBox.warning(self, "ลบไม่ได้", str(exc))


class NovelGroupsPage(QWidget):
    """Manage novel groups inside the main application page stack."""

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.groups = owner.repo.load_groups()
        self.profiles = owner.repo.list_profiles()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        controls = QHBoxLayout()
        self.selector = QComboBox()
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("ชื่อกลุ่ม")
        controls.addWidget(self.selector, 1)
        controls.addWidget(self.name_input, 2)
        layout.addLayout(controls)
        layout.addWidget(QLabel("เลือกนิยายในกลุ่ม"))
        self.members = QListWidget()
        layout.addWidget(self.members, 1)

        actions = QHBoxLayout()
        self.new_name = QLineEdit()
        self.new_name.setPlaceholderText("ชื่อกลุ่มใหม่")
        actions.addWidget(self.new_name, 1)
        create = QPushButton("＋ สร้างกลุ่ม")
        create.clicked.connect(self.create_group)
        actions.addWidget(create)
        delete = QPushButton("ลบกลุ่ม")
        delete.clicked.connect(self.delete_group)
        actions.addWidget(delete)
        save = QPushButton("บันทึก")
        save.clicked.connect(self.store_group)
        actions.addWidget(save)
        open_group = QPushButton("เปิดรายการ")
        open_group.clicked.connect(self.open_group)
        actions.addWidget(open_group)
        layout.addLayout(actions)

        self.selector.currentIndexChanged.connect(self.show_group)
        for group in self.groups:
            self.selector.addItem(group.name, group.id)
        if self.groups:
            self.show_group(0)
        else:
            self.name_input.clear()

    def current_group(self):
        group_id = self.selector.currentData()
        return next((group for group in self.groups if group.id == group_id), None)

    def show_group(self, index):
        self.members.clear()
        group = self.current_group()
        self.name_input.setText(group.name if group else "")
        member_ids = set(group.profile_ids) if group else set()
        for profile in self.profiles:
            row = QListWidgetItem(profile.name)
            row.setData(Qt.UserRole, profile.id)
            row.setFlags(row.flags() | Qt.ItemIsUserCheckable)
            row.setCheckState(Qt.Checked if profile.id in member_ids else Qt.Unchecked)
            self.members.addItem(row)

    def store_group(self):
        group = self.current_group()
        if group is None:
            return
        group.name = self.name_input.text().strip() or group.name
        group.profile_ids = [
            self.members.item(index).data(Qt.UserRole)
            for index in range(self.members.count())
            if self.members.item(index).checkState() == Qt.Checked
        ]
        self.owner.repo.save_groups(self.groups)
        self.owner._refresh_library_groups()
        selected = self.selector.currentIndex()
        self.selector.setItemText(selected, group.name)
        self.owner.statusBar().showMessage(f"บันทึกกลุ่ม {group.name} แล้ว", 3000)

    def create_group(self):
        name = self.new_name.text().strip()
        if not name:
            self.new_name.setFocus()
            return
        from .models import NovelGroup
        group = NovelGroup(name=name, order=len(self.groups))
        self.groups.append(group)
        self.owner.repo.save_groups(self.groups)
        self.owner._refresh_library_groups()
        self.selector.addItem(group.name, group.id)
        self.selector.setCurrentIndex(self.selector.count() - 1)
        self.new_name.clear()

    def delete_group(self):
        group = self.current_group()
        if group is None:
            return
        if QMessageBox.question(self, "ลบกลุ่ม", f"ลบกลุ่ม {group.name} ใช่ไหม?") != QMessageBox.Yes:
            return
        self.groups.remove(group)
        self.owner.repo.save_groups(self.groups)
        self.owner._refresh_library_groups()
        index = self.selector.currentIndex()
        self.selector.removeItem(index)
        self.show_group(self.selector.currentIndex())

    def open_group(self):
        group = self.current_group()
        if group is None:
            return
        self.store_group()
        results = self.owner.launcher.launch_group(group, self.profiles)
        failures = [message for success, message in results if not success]
        succeeded = sum(1 for success, _ in results if success)
        if failures:
            QMessageBox.warning(
                self, "เปิดรายการของกลุ่ม",
                f"เปิดสำเร็จ {succeeded} รายการ\n\n" + "\n".join(failures),
            )
        else:
            self.owner.statusBar().showMessage(f"เปิดกลุ่ม {group.name} แล้ว", 4000)


class MainShell(ManagementActionsMixin, QMainWindow):
    """Novel Library with a focused workflow sidebar and full-size editor."""

    def __init__(self, repo=None):
        self._export_status_cache = {}
        self._startup_export_reminder_shown = False
        self._startup_pending_export_ids = set()
        self._close_export_reminder_accepted = False
        super().__init__(repo)
        self.polish_history = PolishHistory(self.repo, self.assembler)
        self._history_workers = []
        self._history_pending = False
        self._translator_export_in_progress = False
        self._pending_export_snapshots = []
        self._startup_pending_export_ids = {
            profile.id for profile, _path in self._pending_export_profiles()
        }
        self.setWindowTitle("Valhalla")
        self.submit_toast = SubmitToast(self)
        result = read_update_result(self.repo.root)
        if result:
            if result.get("success") and result.get("version") == __version__:
                QTimer.singleShot(100, lambda: self.show_submit_toast(f"อัปเดตเป็น v{__version__} สำเร็จ ✓"))
            else:
                message = result.get("error") or f"เปิดโปรแกรม v{__version__} แต่คาดว่าจะเป็น v{result.get('version', 'unknown')}"
                QTimer.singleShot(100, lambda: QMessageBox.warning(self, "อัปเดตไม่สำเร็จ", f"{message}\nLog: {result.get('log', '')}"))
        logo = Path(__file__).resolve().parent / "resources" / "valhalla-icon.png"
        if logo.is_file():
            self.setWindowIcon(QIcon(str(logo)))
        # Mark historical cosmetic migrations without changing saved preferences.
        changed = not all((self.settings.appearance_migrated, self.settings.flat_vsco…30637 tokens truncated…ile.id)
        if workspace is not None:
            workspace.refresh_export_status()
        if self.profile.context_path:
            try:
                if Path(self.profile.context_path).expanduser().resolve() == Path(saved_path).resolve():
                    self.refresh_translation_progress()
                    workspace = self.workspaces.get(self.profile.id)
                    if workspace:
                        self._update_context_button(workspace)
            except OSError:
                pass
        self._schedule_auto_chapter_review(saved_path)
        # Resume source checks when its paired Translator has finished Auto Save.
        workspace = self.workspaces.get(self.profile.id)
        waiting = getattr(workspace, "auto_chapter_review_waiting_for", None) if workspace else None
        if waiting is not None and waiting[1] == Path(saved_path).expanduser().resolve():
            workspace.auto_chapter_review_waiting_for = None
            self._schedule_auto_chapter_review(str(waiting[0]))

    def _auto_original_source_eligible(self, profile, workspace, path):
        """Allow only a same-codename novel source, never other TXT tabs."""
        if not workspace._source_file_eligible(path):
            return False
        from .chapter_number_reference import matched_translator_path
        translator, _ = matched_translator_path(self.repo, profile.id, path)
        return translator is not None

    def _set_chapter_pending(self, profile, workspace, path, pending: bool):
        """Persist manual-review reminders per source file and novel."""
        key = str(Path(path).expanduser().resolve())
        # Dialogs also persist profile preferences; use a fresh persisted
        # profile to avoid a stale in-memory object reintroducing the marker.
        stored = next(
            (p for p in self.repo.list_profiles() if p.id == profile.id), None
        )
        if stored is None:
            return
        existing = dict(stored.chapter_number_pending_files)
        if pending:
            existing[key] = "needs-review"
        else:
            existing.pop(key, None)
        if existing != stored.chapter_number_pending_files:
            stored.chapter_number_pending_files = existing
            self.repo.save_profile(stored)
        profile.chapter_number_pending_files = existing
        workspace.refresh_context_update_button()

    def _schedule_auto_chapter_review(self, saved_path):
        """Queue every saved source; do not impose a second 2.5-second delay."""
        profile = self.profile
        if not profile or not profile.auto_review_enabled or getattr(self, "_settings_open", False):
            return
        workspace = self.workspaces.get(profile.id)
        if not workspace or getattr(workspace, "auto_chapter_review_busy", False):
            return
        path = Path(saved_path).expanduser().resolve()
        if not self._auto_original_source_eligible(profile, workspace, path):
            return
        if profile.auto_chapter_number_mode != "fix":
            self._set_chapter_pending(profile, workspace, path, True)
            return
        timer = getattr(workspace, "auto_chapter_review_timer", None)
        if timer is None:
            timer = QTimer(workspace)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda pid=profile.id: self._drain_auto_chapter_reviews(pid))
            workspace.auto_chapter_review_timer = timer
        workspace.auto_chapter_review_path = path
        pending = getattr(workspace, "auto_chapter_review_paths", None)
        if pending is None:
            pending = set()
            workspace.auto_chapter_review_paths = pending
        pending.add(path)
        timer.start(0)

    def _drain_auto_chapter_reviews(self, profile_id):
        workspace = self.workspaces.get(profile_id)
        if workspace is None:
            return
        pending = getattr(workspace, "auto_chapter_review_paths", set())
        while pending:
            path = sorted(pending)[0]
            pending.discard(path)
            if self._run_auto_chapter_review(profile_id, path=path):
                getattr(workspace, "auto_chapter_review_failed_paths", set()).discard(path)
            else:
                failed = getattr(workspace, "auto_chapter_review_failed_paths", None)
                if failed is None:
                    failed = set()
                    workspace.auto_chapter_review_failed_paths = failed
                failed.add(path)

    def _run_auto_chapter_review(self, profile_id, path=None, *, for_copy=False):
        profile = self.profile
        workspace = self.workspaces.get(profile_id)
        if (not profile or profile.id != profile_id or not profile.auto_review_enabled
                or not workspace
                or getattr(self, "_settings_open", False)):
            return False
        path = path if path is not None else getattr(workspace, "auto_chapter_review_path", None)
        if path is None:
            return False
        path = Path(path).expanduser().resolve()
        editor = next(
            (tab for i in range(workspace.editor.tabs.count())
             if (tab := workspace.editor.tabs.widget(i)) is not None
             and workspace.editor._path(tab) == path),
            None,
        )
        if editor is None or workspace.editor._dirty(editor):
            return False
        if not self._auto_original_source_eligible(profile, workspace, path):
            return False
        try:
            if not path.is_file() or path.stat().st_size == 0:
                return False
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != editor.disk_digest.hex():
                return False  # File changed externally since our successful save.
        except OSError:
            return False
        fingerprint = (str(path), digest)
        verified = getattr(workspace, "auto_chapter_review_verified", None)
        if verified is None:
            verified = {}
            workspace.auto_chapter_review_verified = verified
        if verified.get(str(path)) == digest:
            return True
        if getattr(workspace, "auto_chapter_review_seen", None) == fingerprint and not for_copy:
            return False
        if True:
            from .chapter_number_reference import resolve_translator_reference
            from .incremental_chapter_numbering import (
                automatic_append_plan, verified_prefix_from_history,
            )
            text = editor.toPlainText()
            headings, issues = scan_original_chapter_issues(text)
            attention = [issue for issue in issues if issue != "ปกติ"]
            if not headings:
                self.show_submit_toast(
                    "ตรวจต้นฉบับแล้ว · ไม่พบหัวบทที่รองรับ กรุณาตรวจรูปแบบหัวบท"
                )
                return False
            number_mode = getattr(profile, "auto_chapter_number_mode", "check")
            if number_mode == "off" and profile.auto_review_enabled:
                number_mode = "check"  # Keep old opt-in programs checking only.
            if number_mode == "fix":
                from .chapter_number_reference import matched_translator_path
                translator_path, _ = matched_translator_path(self.repo, profile_id, path)
                if translator_path is not None:
                    for i in range(workspace.editor.tabs.count()):
                        other = workspace.editor.tabs.widget(i)
                        if (workspace.editor._path(other) == translator_path
                                and workspace.editor._dirty(other)):
                            if for_copy:
                                if not workspace.editor.save_editor(other, quiet=True, normalize=False):
                                    self.show_submit_toast(
                                        f"ไม่ได้แก้เลขบท · บันทึก {translator_path.name} ไม่สำเร็จ"
                                    )
                                    return False
                                continue
                            workspace.auto_chapter_review_waiting_for = (path, translator_path)
                            self.statusBar().showMessage(
                                f"รอ Auto Save {translator_path.name} แล้วจะตรวจเลขบท {path.name}", 18000
                            )
                            return False
                reference = resolve_translator_reference(self.repo, profile_id, path)
                if reference.start is None:
                    workspace.auto_chapter_review_seen = fingerprint
                    self.show_submit_toast("ไม่ได้แก้เลขบท · " + reference.message)
                    self.statusBar().showMessage("ไม่ได้แก้เลขบท · " + reference.message, 16000)
                    return False
                checkpoint = verified_prefix_from_history(
                    self.repo.profile_dir(profile_id), profile_id, path, text, reference.start
                )
                verified_prefix, last_original = checkpoint if checkpoint else (None, None)
                try:
                    _expected, changes = automatic_append_plan(
                        text, reference.start, verified_prefix, last_original
                    )
                except ValueError as exc:
                    workspace.auto_chapter_review_seen = fingerprint
                    self.show_submit_toast(f"ไม่ได้แก้เลขบท · {exc}")
                    self.statusBar().showMessage(f"ไม่ได้แก้เลขบท · {exc}", 16000)
                    return False
                if not changes:
                    workspace.auto_chapter_review_seen = fingerprint
                    verified[str(path)] = digest
                    self.show_submit_toast(
                        f"ตรวจแล้ว · {len(headings)} บท เรียงต่อจาก Translator ถูกต้อง ✓"
                    )
                    return True
                from .chapter_numbering_dialog import apply_automatic_without_dialog
                workspace.auto_chapter_review_busy = True
                try:
                    # Recheck the same-novel Translator immediately before writing.
                    current_reference = resolve_translator_reference(self.repo, profile_id, path)
                    if (current_reference.start != reference.start
                            or current_reference.path != reference.path):
                        self.show_submit_toast(
                            "ไม่ได้แก้เลขบท · ข้อมูล Translator เปลี่ยนระหว่างตรวจ"
                        )
                        return False
                    apply_automatic_without_dialog(workspace, editor, path, _expected, changes)
                    # Saving emits documentSaved; suppress a recursive auto-check,
                    # and remember the final content digest to avoid renumber loops.
                    corrected_digest = hashlib.sha256(path.read_bytes()).hexdigest()
                    workspace.auto_chapter_review_seen = (str(path), corrected_digest)
                    verified[str(path)] = corrected_digest
                    self._set_chapter_pending(profile, workspace, path, False)
                except (OSError, ValueError) as exc:
                    self.show_submit_toast(f"แก้เลขบทอัตโนมัติไม่สำเร็จ · {exc}")
                    return False
                finally:
                    workspace.auto_chapter_review_busy = False
                message = (
                    f"แก้เลขบทจาก {reference.path.name} สำเร็จ {len(changes)} บท "
                    f"· เริ่มที่บท {reference.start} · ย้อนคืนได้ที่ ตรวจเลขบท"
                )
                self.show_submit_toast(message)
                self.statusBar().showMessage(message, 15000)
                return True
            if number_mode == "check":
                workspace.auto_chapter_review_seen = fingerprint
                self._set_chapter_pending(profile, workspace, path, True)
                self.statusBar().showMessage(
                    f"{path.name}: มีบทใหม่รอตรวจ · กดปุ่ม 'ตรวจเลขบท' ในแท็บต้นฉบับ",
                    12000,
                )
            return False

    def _update_context_button(self, workspace):
        path = Path(self.profile.context_path).expanduser() if self.profile and self.profile.context_path else None
        if path and path.is_file():
            workspace.context_button.setText(path.name)
            workspace.context_button.setToolTip(str(path))
        else:
            workspace.context_button.setText("Context")
            workspace.context_button.setToolTip("ยังไม่ได้เลือกไฟล์ Context · คลิกเพื่อเลือก")

    def _profile_file_paths(self, profile):
        files = list(profile.working_files)
        for step in profile.workflow.steps:
            files.extend(step.files)
        if profile.vocabulary_step:
            files.extend(profile.vocabulary_step.files)
        paths = set()
        for item in files:
            if not item.path or item.reference_type == "dynamic":
                continue
            try:
                path = (Path(item.path).expanduser().resolve()
                        if item.reference_type == "external_file"
                        else self.repo.resolve_project_path(profile.id, item.path).resolve())
                paths.add(path)
            except (OSError, ValueError, TypeError):
                continue
        return paths

    def _export_status_path(self, profile_id):
        return self.repo.profile_dir(profile_id) / "export_status.json"

    @staticmethod
    def _export_path_key(path):
        return os.path.normcase(str(Path(path).expanduser().resolve()))

    def _export_records(self, profile_id):
        if profile_id not in self._export_status_cache:
            try:
                value = read_json(self._export_status_path(profile_id), {})
                self._export_status_cache[profile_id] = value if isinstance(value, dict) else {}
            except (OSError, ValueError, TypeError):
                self._export_status_cache[profile_id] = {}
        return self._export_status_cache[profile_id]

    def _save_export_records(self, profile_id):
        records = self._export_records(profile_id)
        write_json(self._export_status_path(profile_id), records)

    def _record_successful_export(self, profile_id, path, digest, exported_txt):
        key = self._export_path_key(path)
        records = self._export_records(profile_id)
        previous = records.get(key)
        records[key] = {
            "profile_id": profile_id,
            "translator_path": key,
            "digest": digest.hex(),
            "exported_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "exported_txt_path": str(Path(exported_txt).resolve()),
            "pending": False,
        }
        try:
            self._save_export_records(profile_id)
        except (OSError, ValueError):
            if previous is None:
                records.pop(key, None)
            else:
                records[key] = previous
            raise

    def _mark_export_pending(self, profile_id, path):
        if profile_id in self.repo.export_recovery_errors: return
        key = self._export_path_key(path)
        records = self._export_records(profile_id)
        record = records.get(key)
        if record and record.get("pending"):
            return
        record = dict(record or {})
        record.update({
            "profile_id": profile_id,
            "translator_path": key,
            "pending": True,
        })
        records[key] = record
        try:
            self._save_export_records(profile_id)
        except (OSError, ValueError) as exc:
            self.statusBar().showMessage(f"บันทึกสถานะ Export ไม่สำเร็จ: {exc}", 6000)

    def _translator_export_status(self, profile_id, path, editor=None):
        if profile_id in self.repo.export_recovery_errors: return 'not_exported'
        key = self._export_path_key(path)
        record = self._export_records(profile_id).get(key)
        if not record:
            if editor is not None and EditorTabs._dirty(editor) and not editor.property('normalizationPending'):
                self._mark_export_pending(profile_id, path)
                return "not_exported"
            return "unknown"
        try:
            from .workflow_archive import file_digest
            digest = file_digest(path)
        except OSError:
            return "not_exported" if record.get('pending') else "unknown"
        matches = digest.hex() == record.get('digest')
        if editor is not None:
            text = editor.toPlainText()
            # Opening/restore may normalize the display without changing disk.
            # Undo to that baseline is also unchanged content, regardless of dirty flags.
            baseline = editor.property('documentSavedText')
            changed = text != baseline
            if changed:
                encoded = text.replace("\n", getattr(editor, 'disk_newline', "\n"))
                if getattr(editor, 'disk_bom', False): encoded = "\ufeff" + encoded
                matches = hashlib.sha256(encoded.encode('utf-8')).hexdigest() == record.get('digest')
            editor.setProperty('exportDigestMatches', matches)
        if matches:
            if record.get('pending'):
                record['pending'] = False
                try:
                    self._save_export_records(profile_id)
                except (OSError, ValueError) as exc:
                    record['pending'] = True
                    self.statusBar().showMessage(f'บันทึกสถานะ Export ไม่สำเร็จ: {exc}', 6000)
            return 'exported'
        self._mark_export_pending(profile_id, path)
        return 'not_exported'

    def _confirm_exported_content(self, profile_id, path, editor):
        self._translator_export_status(profile_id, path, editor)

    def _pending_export_profiles(self):
        pending = []
        for profile in self.repo.list_profiles():
            path = self._pending_export_for_profile(profile.id)
            if path is not None: pending.append((profile, path))
        return pending

    def _pending_export_for_profile(self, profile_id):
        workspace = self.workspaces.get(profile_id)
        for key, record in list(self._export_records(profile_id).items()):
            path = Path(record.get('translator_path') or key)
            editor = None
            if workspace:
                for i in range(workspace.editor.tabs.count()):
                    candidate = workspace.editor.tabs.widget(i)
                    if EditorTabs._path(candidate) == path.resolve():
                        editor = candidate
                        break
            if self._translator_export_status(profile_id, path, editor) == 'not_exported':
                return path
        return None

    def _export_profile_translator(self, profile_id):
        workspace = self.workspaces.get(profile_id)
        profile = next((item for item in self.repo.list_profiles() if item.id == profile_id), None)
        if workspace is None or profile is None:
            return False
        records = self._export_records(profile_id)
        path = next((Path(record.get("translator_path") or key)
                     for key, record in records.items()
                     if record.get("pending") and "translator.txt" in Path(key).name.casefold()), None)
        if path is None:
            path = next((item for item in self._profile_file_paths(profile)
                         if "translator.txt" in item.name.casefold()), None)
        if path is None or not path.is_file():
            return False
        editor = workspace.editor.open_file(path)
        if editor is None:
            return False
        workspace.editor.tabs.setCurrentWidget(editor)
        if workspace.editor._dirty(editor) and not workspace.editor.save_editor(editor, quiet=True):
            return False
        return bool(self.update_context_from_translator(workspace))

    def _export_reminder_choice(self, title, details):
        dialog = QMessageBox(self)
        dialog.setWindowTitle(title)
        dialog.setIcon(QMessageBox.Warning)
        dialog.setText(details)
        export_button = dialog.addButton("Export Now", QMessageBox.AcceptRole)
        later_button = dialog.addButton("Later", QMessageBox.ActionRole)
        cancel_button = dialog.addButton("Cancel", QMessageBox.RejectRole)
        dialog.exec()
        if dialog.clickedButton() is export_button:
            return "export"
        if dialog.clickedButton() is later_button:
            return "later"
        return "cancel"

    def _show_startup_export_reminder(self, profile_id):
        if (self._startup_export_reminder_shown
                or profile_id not in self._startup_pending_export_ids
                or not self.profile or self.profile.id != profile_id):
            return
        pending_path = self._pending_export_for_profile(profile_id)
        if pending_path is None:
            return
        self._startup_export_reminder_shown = True
        dialog = QMessageBox(self)
        dialog.setWindowTitle("ยังไม่ได้ Export งานแปล!")
        dialog.setIcon(QMessageBox.Warning)
        dialog.setText(f"มีงานแปลที่ยังไม่ได้ Export จากครั้งก่อน\nTranslator: {pending_path}")
        export_button = dialog.addButton("Export Now", QMessageBox.AcceptRole)
        dialog.addButton("Later", QMessageBox.ActionRole)
        dialog.exec()
        if dialog.clickedButton() is export_button:
            self._export_profile_translator(profile_id)

    def _guard_destructive_paste(self, profile_id, editor):
        path = EditorTabs._path(editor)
        if (path is None or not self._translator_profile_for_path(profile_id, path)
                or self._translator_export_status(profile_id, path, editor) != "not_exported"):
            return True
        dialog = QMessageBox(self)
        dialog.setWindowTitle("ยังไม่ได้ Export งานแปล!")
        dialog.setIcon(QMessageBox.Warning)
        dialog.setText(
            f"Translator: {path}\n\nมีงานแปลที่ยังไม่ได้ Export การวางนี้จะแทนที่ข้อความส่วนใหญ่ของไฟล์"
        )
        export_button = dialog.addButton("Export Now", QMessageBox.AcceptRole)
        keep_button = dialog.addButton("Keep Editing", QMessageBox.RejectRole)
        replace_button = dialog.addButton("Replace Anyway", QMessageBox.DestructiveRole)
        dialog.exec()
        if dialog.clickedButton() is export_button:
            if not self._export_profile_translator(profile_id):
                return False
            return True
        if dialog.clickedButton() is replace_button:
            workspace = self.workspaces.get(profile_id)
            if workspace is None:
                return False
            try:
                recovery = workspace.editor._recovery_path(path)
                write_json(recovery, {"path": str(path.resolve()), "text": editor.toPlainText()})
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, "สำรองงานเดิมไม่ได้", str(exc))
                return False
            return True
        if dialog.clickedButton() is keep_button:
            return False
        return False

    def _translator_profile_for_path(self, profile_id, path):
        try:
            candidate = Path(path).expanduser().resolve()
        except (OSError, TypeError, ValueError):
            return None
        profiles = self.repo.list_profiles()
        profile = next((item for item in profiles if item.id == profile_id), None)
        if profile is None or not profile.context_path:
            return None
        if not candidate.name.casefold().endswith("translator.txt") or candidate.name.casefold() == "translator.txt":
            return None
        bindings = [(item, self._profile_file_paths(item)) for item in profiles]
        profile_paths = next((paths for item, paths in bindings if item.id == profile_id), set())
        if candidate not in profile_paths:
            return None
        owners = [item for item, paths in bindings if candidate in paths]
        if len(owners) != 1 or owners[0].id != profile_id:
            return None
        try:
            context = Path(profile.context_path).expanduser().resolve()
            if not context.is_file():
                return None
            other_contexts = [
                item for item in profiles
                if item.id != profile_id and item.context_path
                and Path(item.context_path).expanduser().resolve() == context
            ]
            if other_contexts:
                return None
        except (OSError, TypeError, ValueError):
            return None
        return profile

    def update_context_from_translator(self, workspace, *, preauthorized=False):
        """Export bound Translator bytes and replace its Context in one transaction."""
        from copy import deepcopy
        from .recovery import translator_chapter_range
        if self._translator_export_in_progress:
            self.statusBar().showMessage("กำลังสำรองและ Export กรุณารอสักครู่", 5000)
            return False
        profile_id = workspace.profile_id
        if profile_id in self.repo.export_recovery_errors:
            QMessageBox.warning(self, 'Export ไม่ได้', self.repo.export_recovery_errors[profile_id])
            return False
        if not self.profile or self.profile.id != profile_id:
            QMessageBox.warning(self, "Export ไม่ได้", "โปรไฟล์ที่เลือกเปลี่ยนไปแล้ว กรุณาเลือกแท็บใหม่")
            return False
        editor = workspace.editor._current_editor()
        source = workspace.editor._path(editor) if editor else None
        profile = self._translator_profile_for_path(profile_id, source) if source else None
        if profile is None:
            QMessageBox.warning(self, "Export ไม่ได้", "ยืนยันไม่ได้ว่า Translator นี้ผูกกับนิยายที่เลือก")
            return False
        try:
            visible_text = editor.toPlainText()
            original_visible_text = editor.property("documentSavedText")
            if original_visible_text is None:
                original_source_bytes = source.read_bytes()
                from .text_normalization import normalize_editor_text
                original_visible_text = normalize_editor_text(
                    source, original_source_bytes.decode("utf-8-sig")
                )
        except (OSError, UnicodeError) as exc:
            QMessageBox.warning(self, "Export ไม่ได้", str(exc))
            return False
        editor_has_unsaved_changes = bool(
            workspace.editor._dirty(editor) and visible_text != original_visible_text
        )
        if (editor_has_unsaved_changes
                and not workspace.editor.save_editor(editor, quiet=True, normalize=False)):
            QMessageBox.warning(self, "Export ไม่ได้", "บันทึก Translator ไม่สำเร็จหรือพบการแก้ไขจากภายนอก")
            return False
        staged_files = []
        try:
            profile = self._translator_profile_for_path(profile_id, source)
            if profile is None:
                raise OSError("โปรไฟล์หรือรายการไฟล์ที่ผูกไว้เปลี่ยนไประหว่างบันทึก")
            source = source.expanduser().resolve()
            context = Path(profile.context_path).expanduser().resolve()
            if source == context:
                raise OSError("ไฟล์ Translator และ Context เป็นไฟล์เดียวกัน")
            if not context.is_file():
                raise OSError("ไม่พบไฟล์ Context ที่ผูกกับโปรไฟล์นี้")
            translator_bytes = source.read_bytes()
            source_digest = hashlib.sha256(translator_bytes).digest()
            from .translation_progress import translator_chapters
            confirmed_chapters = translator_chapters(translator_bytes)
            if source_digest != editor.disk_digest:
                raise OSError("Translator ถูกแก้ไขจากภายนอก")
            original_digest = hashlib.sha256(context.read_bytes()).digest()
            chapter_range = translator_chapter_range(translator_bytes)
            history_range = chapter_range
            if chapter_range is None:
                entered_range, accepted = QInputDialog.getText(
                    self, "ระบุช่วงบท", "ยืนยันช่วงบทจาก Translator เช่น 6-10:"
                )
                if not accepted:
                    return False
                from .polish_history import parse_range
                history_range = parse_range(entered_range)
            history_step = self._history_step_for_profile(profile)
            if history_step is None:
                raise OSError("เลือกขั้นตอนตรวจคำแปลสำหรับ Polish History ใน Settings ก่อน")
            if not profile.main_folder.strip():
                raise OSError("กรุณาตั้งค่าโฟลเดอร์หลักของนิยายก่อน Export")
            profile_for_snapshot, step_for_snapshot = deepcopy(profile), deepcopy(history_step)
            planned, _attachments = self.polish_history._plan(profile_for_snapshot, step_for_snapshot)

            def attachment_signature(entries):
                return tuple((str(path), item.id, item.reference_type, item.order,
                              item.enabled, is_context)
                             for path, _target, item, is_context in entries)

            initial_attachment_signature = attachment_signature(planned)
            if not any(path.resolve() == context for path, _target, _item, _ctx in planned):
                raise OSError("ยังไม่ได้เลือกไฟล์ Context ในขั้นตอนตรวจคำแปล")
            root = (Path(profile.main_folder).expanduser() if profile.main_folder.strip()
                    else self.repo.profile_dir(profile.id))
            if not root.is_dir():
                raise OSError("ไม่พบโฟลเดอร์หลักของนิยาย")
            export_folder = root.resolve() / "Context Exports"
            export_folder.mkdir(parents=True, exist_ok=True)
            if chapter_range is None:
                base = f"{source.stem} {datetime.now().strftime('%Y%m%d-%H%M%S')}"
                chapter_label = "ไม่พบหัวบทที่รองรับ · ใช้ Timestamp"
            else:
                base = f"{source.stem} {chapter_range}"
                chapter_label = f"ช่วงบท: {chapter_range}"
            occupied = {item.name.casefold().rstrip(" .") for item in export_folder.iterdir()}
            target_name = f"{base}.txt"
            suffix = 2
            while target_name.casefold().rstrip(" .") in occupied:
                target_name = f"{base} ({suffix}).txt"
                suffix += 1
            target = export_folder / target_name
            if not os.access(export_folder, os.W_OK):
                raise OSError("ไม่มีสิทธิ์เขียนในโฟลเดอร์ Context Exports")
        except (OSError, ValueError, TypeError) as exc:
            QMessageBox.warning(self, "Export ไม่ได้", str(exc))
            return False

        context_editor = next((workspace.editor.tabs.widget(index)
                               for index in range(workspace.editor.tabs.count())
                               if workspace.editor._path(workspace.editor.tabs.widget(index)) == context), None)
        if context_editor is not None:
            try:
                # Opening Context can compact empty lines only in the display.
                # Do not write this presentation-only change over old Context.
                normalization_only = (
                    context_editor.property("normalizationPending")
                    and context_editor.property("displayNormalization")
                    and context_editor.toPlainText() == context_editor.property("documentSavedText")
                )
                if workspace.editor._dirty(context_editor) and not normalization_only:
                    QMessageBox.warning(self, "Export ไม่ได้", "Context มีการแก้ไขที่ยังไม่ได้บันทึก")
                    return False
                if hashlib.sha256(context.read_bytes()).digest() != context_editor.disk_digest:
                    QMessageBox.warning(self, "Export ไม่ได้", "Context ถูกแก้ไขจากภายนอก กรุณาเปิดไฟล์ใหม่เพื่อตรวจสอบ")
                    return False
            except OSError as exc:
                QMessageBox.warning(self, "Export ไม่ได้", str(exc))
                return False
        if not preauthorized:
            preview = QMessageBox(self)
            preview.setWindowTitle("ยืนยัน Export")
            preview.setIcon(QMessageBox.Information)
            preview.setText(
                f"สำรองไฟล์ขั้นตอนตรวจคำแปลก่อน แล้วสร้างไฟล์ TXT และแทนที่ Context ทั้งหมด?\n"
                f"TXT: {target.name}\n{chapter_label}\n"
                f"Translator: {source}\nContext: {context}"
            )
            preview.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            if preview.exec() != QMessageBox.Yes:
                return False

        self._translator_export_in_progress = True
        snapshot_verified = False
        try:
            if self.history_busy():
                raise OSError("กำลังจัดการประวัติ กรุณารอสักครู่แล้วลอง Export อีกครั้ง")
            fresh_profile = self._translator_profile_for_path(profile_id, source)
            if (fresh_profile is None
                    or Path(fresh_profile.context_path).expanduser().resolve() != context
                    or getattr(fresh_profile, "polish_history_step_id", None) != history_step.id):
                raise OSError("โปรไฟล์หรือไฟล์ที่ผูกไว้เปลี่ยนไประหว่างยืนยัน")
            fresh_step = self._history_step_for_profile(fresh_profile)
            if fresh_step is None or fresh_step != history_step:
                raise OSError("รายการไฟล์ขั้นตอนตรวจคำแปลเปลี่ยนระหว่างยืนยัน")
            fresh_plan, _fresh_attachments = self.polish_history._plan(fresh_profile, fresh_step)
            if attachment_signature(fresh_plan) != initial_attachment_signature:
                raise OSError("ไฟล์ที่ Resolve สำหรับขั้นตอนตรวจคำแปลเปลี่ยนระหว่างยืนยัน")
            if hashlib.sha256(source.read_bytes()).digest() != source_digest:
                raise OSError("Translator ถูกแก้ไขจากภายนอกระหว่างยืนยัน")
            if hashlib.sha256(context.read_bytes()).digest() != original_digest:
                raise OSError("Context ถูกแก้ไขจากภายนอกระหว่างยืนยัน")
            loop = QEventLoop(self)
            outcome = {}
            self._history_pending = True
            self.statusBar().showMessage("กำลังสำรองไฟล์ขั้นตอนตรวจคำแปลก่อน Export…")
            worker = HistoryWorker(
                lambda: self.polish_history.create(profile_for_snapshot, step_for_snapshot, history_range, capture_reason='translator_pre_export'), self
            )
            self._history_workers.append(worker)

            def snapshot_succeeded(value):
                outcome["snapshot"] = value
                self._history_pending = False
                QTimer.singleShot(0, loop.quit)

            def snapshot_failed(error):
                outcome["error"] = error
                self._history_pending = False
                QTimer.singleShot(0, loop.quit)

            worker.succeeded.connect(snapshot_succeeded, Qt.ConnectionType.QueuedConnection)
            worker.failed.connect(snapshot_failed, Qt.ConnectionType.QueuedConnection)

            def cleanup_snapshot_worker():
                if worker in self._history_workers:
                    self._history_workers.remove(worker)
                worker.deleteLater()
            worker.start()
            loop.exec()
            worker.wait()
            cleanup_snapshot_worker()
            if "error" in outcome:
                raise OSError(f"สำรองไฟล์ขั้นตอนตรวจคำแปลไม่สำเร็จ: {outcome['error']}")
            snapshot = outcome.get("snapshot")
            if snapshot is None:
                raise OSError("ไม่พบผลการบันทึก Polish History")
            payloads = self.polish_history.validate(profile, snapshot.path)
            manifest = snapshot.manifest
            if (manifest.get("step_id") != history_step.id
                    or manifest.get("chapter_range") != history_range
                    or manifest.get("file_count") != len(payloads)):
                raise OSError("ตรวจสอบ Snapshot แล้วพบ Metadata ไม่ตรงกับ Export")
            saved_attachment_signature = tuple(
                (entry["original_path"], entry["attachment_id"], entry["reference_type"],
                 entry["order"], entry["enabled"], entry["is_context"])
                for entry in manifest.get("files", [])
            )
            if saved_attachment_signature != initial_attachment_signature:
                raise OSError("รายการไฟล์ใน Snapshot ไม่ตรงกับชุดที่ยืนยันไว้ก่อน Export")
            saved_context = next((entry for entry in manifest.get("files", [])
                                  if entry.get("is_context") and
                                  Path(entry.get("original_path", "")).resolve() == context), None)
            if saved_context is None or saved_context.get("sha256") != original_digest.hex():
                raise OSError("ตรวจสอบ Snapshot แล้วไม่พบ Context เวอร์ชันก่อน Export")
            snapshot_verified = True
            fresh_profile = self._translator_profile_for_path(profile_id, source)
            if (fresh_profile is None
                    or Path(fresh_profile.context_path).expanduser().resolve() != context
                    or getattr(fresh_profile, "polish_history_step_id", None) != history_step.id):
                raise OSError("โปรไฟล์หรือไฟล์ที่ผูกไว้เปลี่ยนไประหว่างยืนยัน")
            fresh_step = self._history_step_for_profile(fresh_profile)
            if fresh_step is None or fresh_step != history_step:
                raise OSError("รายการไฟล์ขั้นตอนตรวจคำแปลเปลี่ยนระหว่างสำรอง")
            if hashlib.sha256(source.read_bytes()).digest() != source_digest:
                raise OSError("Translator ถูกแก้ไขระหว่างสำรอง")
            if target.exists():
                raise OSError("พบไฟล์ชื่อเดียวกันระหว่างเตรียม Export กรุณาลองอีกครั้ง")
            if hashlib.sha256(context.read_bytes()).digest() != original_digest:
                raise OSError("Context ถูกแก้ไขจากภายนอกระหว่างการยืนยัน")
            staged_files.append((target, _stage_bytes_file(target, translator_bytes)))
            staged_files.append((context, _stage_bytes_file(context, translator_bytes)))
            with self.repo.profile_lock:
                from .translation_progress import record_translator_export
                import uuid
                event = record_translator_export(fresh_profile, confirmed_chapters,
                    source_path=str(source), digest=source_digest.hex(), exported_path=str(target),
                    event_id=uuid.uuid4().hex, snapshot_path=str(snapshot.path))
                profile_path = self.repo.profile_dir(profile_id) / 'profile.json'
                from .workflow_archive import file_digest
                profile_before_digest = file_digest(profile_path)
                staged_profile = _stage_bytes_file(profile_path, b'')
                staged_files.append((profile_path, staged_profile))
                self.repo.save_profile(fresh_profile, destination=staged_profile)
                records = deepcopy(self._export_records(profile_id))
                key = self._export_path_key(source)
                records[key] = {'profile_id': profile_id, 'translator_path': key,
                    'digest': source_digest.hex(), 'exported_at': event['completed_at'],
                    'exported_txt_path': str(target), 'pending': False, 'event_id': event['event_id']}
                status_path = self._export_status_path(profile_id)
                status_before_digest = file_digest(status_path) if status_path.exists() else None
                staged_status = _stage_bytes_file(status_path, b'')
                staged_files.append((status_path, staged_status))
                write_json(staged_status, records)
                def verify_transaction():
                    if target.read_bytes() != translator_bytes or context.read_bytes() != translator_bytes:
                        raise OSError('ตรวจสอบหลังเขียนพบว่าไฟล์ TXT หรือ Context ไม่ตรงกับ Translator')
                    persisted = read_json(profile_path, {})
                    if not any(e.get('event_id') == event['event_id'] for e in persisted.get('translator_export_events', [])):
                        raise OSError('บันทึกสถิติ Translator Export ไม่สำเร็จ')
                journal_path = self.repo.profile_dir(profile_id) / 'translator_export_transaction.json'
                if journal_path.exists(): raise OSError('ยังมี Export ค้างที่ต้องตรวจสอบก่อน Export ใหม่')
                def verify_before():
                    current_status_digest = file_digest(status_path) if status_path.exists() else None
                    if (file_digest(context) != original_digest or file_digest(source) != source_digest
                            or file_digest(profile_path) != profile_before_digest
                            or current_status_digest != status_before_digest):
                        raise OSError('ไฟล์ถูกแก้ไขจากภายนอกระหว่างเตรียม Export · ไม่เขียนทับข้อมูล')
                def prepare_destination(destination, staged):
                    if destination == profile_path.resolve():
                        if target.read_bytes() != translator_bytes or context.read_bytes() != translator_bytes:
                            raise OSError('ตรวจสอบ TXT/Context ก่อนบันทึกสถิติไม่สำเร็จ')
                        when = datetime.now().astimezone()
                        event['completed_at'] = when.isoformat(timespec='microseconds')
                        event['local_date'] = when.date().isoformat()
                        records[key]['exported_at'] = event['completed_at']
                        self.repo.save_profile(fresh_profile, destination=staged_profile)
                        write_json(staged_status, records)
                        return True
                    return False
                commit_staged(staged_files, commit_metadata=verify_transaction,
                    create_backups=False, no_overwrite=(target,), journal_path=journal_path,
                    verify_before=verify_before, prepare_destination=prepare_destination)
                self._export_status_cache.pop(profile_id, None)
        except (OSError, ValueError) as exc:
            self._export_status_cache.pop(profile_id, None)
            if snapshot_verified:
                message = f"สำรองประวัติสำเร็จ แต่ Export ไม่สำเร็จ\n{exc}"
            else:
                message = f"สำรองไฟล์ขั้นตอนที่ 2 ไม่สำเร็จ\n{exc}\n\nContext เดิมยังไม่ถูกเปลี่ยนแปลง"
            QMessageBox.warning(self, "Export ไม่สำเร็จ", message)
            return False
        finally:
            self._translator_export_in_progress = False
            for _destination, staged in staged_files:
                _cleanup_staged_text_file(staged)

        self.ps_list = [fresh_profile if p.id == profile_id else p for p in self.ps_list]
        self.profile = fresh_profile
        workspace.editor.apply_external_update(context, visible_text)
        workspace.refresh_export_status()
        self.refresh_translation_progress()
        count = snapshot.manifest["file_count"]
        if not confirmed_chapters:
            QMessageBox.warning(self, 'ยังยืนยันจำนวนบทไม่ได้', 'Export สำเร็จ แต่ไม่พบหัวบทที่ตรวจสอบได้ จึงไม่ได้เพิ่มยอดแปลเสร็จ')
        self.statusBar().showMessage(
            f"สำรอง {history_step.name} บท {history_range} สำเร็จ · {count} ไฟล์ · Export {target.name} สำเร็จ", 8000
        )
        QMessageBox.information(
            self, "Export สำเร็จ",
            f"สำรอง {history_step.name} บท {history_range} สำเร็จ\n"
            f"สำรองไฟล์ {count} ไฟล์\nContext ที่สำรอง: เวอร์ชันก่อน Export\n\n"
            f"ส่งออก Translator สำเร็จ\nอัปเดต Context ปัจจุบันเรียบร้อย",
        )
        return True

    def launch_profile(self):
        """Open supported profile targets inside the current workspace."""
        if not self.profile:
            return

        has_main_folder = bool(self.profile.main_folder.strip())
        has_enabled_targets = any(item.enabled for item in self.profile.launch_targets)
        if not has_main_folder and not has_enabled_targets:
            self.settings_dialog()
            self.statusBar().showMessage(
                "ยังไม่มีรายการให้เปิด · เพิ่มไฟล์หรือโฟลเดอร์ได้ในหน้าตั้งค่านิยาย", 5000
            )
            return

        workspace = self._workspace(self.profile)
        if workspace is None:
            return
        succeeded = 0
        failures = []

        if self.profile.main_folder.strip():
            main_folder = Path(self.profile.main_folder).expanduser()
            if main_folder.is_dir():
                workspace.configure(self.profile)
                succeeded += 1
            else:
                failures.append(
                    f"โฟลเดอร์หลัก: ไม่พบโฟลเดอร์ {main_folder}"
                )

        targets = sorted(
            (entry for entry in self.profile.launch_targets if entry.enabled),
            key=lambda entry: entry.order,
        )

        for entry in targets:
            try:
                if entry.kind == "file":
                    path = Path(entry.target).expanduser()
                    if not path.is_file():
                        raise FileNotFoundError(path)
                    if workspace.editor.supports(path):
                        workspace.editor.open_file(path)
                        succeeded += 1
                    else:
                        ok, message = self.launcher.launch_target(entry)
                        succeeded += int(ok)
                        if not ok:
                            failures.append(message)
                elif entry.kind == "folder":
                    path = Path(entry.target).expanduser()
                    if not path.is_dir():
                        raise FileNotFoundError(path)
                    workspace.root_path = path.resolve()
                    index = workspace.file_model.setRootPath(
                        str(workspace.root_path)
                    )
                    workspace.file_tree.setRootIndex(index)
                    succeeded += 1
                else:
                    ok, message = self.launcher.launch_target(entry)
                    succeeded += int(ok)
                    if not ok:
                        failures.append(message)
            except Exception as exc:
                failures.append(f"{entry.label or entry.target}: {exc}")

        if failures:
            QMessageBox.warning(
                self,
                "Valhalla",
                f"เปิดสำเร็จ {succeeded} รายการ\n\n" + "\n".join(failures),
            )
        else:
            self.statusBar().showMessage(
                f"เปิดรายการของ {self.profile.name} แล้ว ({succeeded} รายการ)",
                4000,
            )

    def refresh_goal_indicator(self):
        super().refresh_goal_indicator()
        if self.profile:
            workspace = self.workspaces.get(self.profile.id)
            if workspace:
                self._update_progress_page(workspace)

    def _update_progress_page(self, workspace):
        if not self.profile:
            return

        latest = None
        if self.profile.context_path:
            try:
                context = Path(self.profile.context_path).expanduser()
                if context.is_file():
                    latest = read_context_chapter(context)
            except OSError:
                latest = None

        self._latest_context_chapter = latest
        if not self.profile.context_path:
            self.context_status.setFullText("ยังไม่ได้เลือก Context")
        elif latest is None:
            self.context_status.setFullText("ไม่พบบทใน Context")
        else:
            self.context_status.setFullText(f"Context: บท {latest}")
        self._latest_chapter_status = (
            f"  ·  ล่าสุดบท {latest}" if latest is not None else ""
        )
        self._update_editor_status()

    def _capture_sessions(self):
        self.settings.workspace_open_profile_ids = list(self._open_workspace_ids)
        for profile_id, workspace in self.workspaces.items():
            self.settings.editor_tabs[profile_id] = (
                workspace.editor.open_paths()
            )
            current_tab = workspace.editor.tabs.currentIndex()
            self.settings.editor_active_tabs[profile_id] = (
                sum(
                    1 for index in range(current_tab)
                    if workspace.editor._path(workspace.editor.tabs.widget(index))
                )
            )
            self.settings.editor_tab_order[profile_id] = workspace.editor.tab_order()
            active_key = workspace.editor.active_tab_key()
            if active_key:
                self.settings.editor_active_tab_keys[profile_id] = active_key
            self.settings.workspace_step_indices[profile_id] = workspace.step_index
            self.settings.workspace_vocabulary_modes[profile_id] = workspace.vocabulary_mode
            sidebar_size = workspace.workspace_splitter.sizes()[0]
            self.settings.sidebar_visible = sidebar_size > 0
            if sidebar_size > 0:
                self.settings.sidebar_width = sidebar_size
            positions = {}
            for index in range(workspace.editor.tabs.count()):
                editor = workspace.editor.tabs.widget(index)
                path = workspace.editor._path(editor)
                if path:
                    positions[str(path)] = {
                        "cursor": editor.textCursor().position(),
                        "scroll": editor.verticalScrollBar().value(),
                    }
            self.settings.editor_positions[profile_id] = positions

    def save(self):
        self._capture_sessions()
        super().save()

    def _workspace_editor_status_changed(self, editor, text):
        """Cursor changes update only the status label, never files or covers."""
        if not self.profile:
            return
        workspace = self.workspaces.get(self.profile.id)
        if workspace is not None and workspace.editor is editor:
            self.editor_status.setFullText(text)

    def _update_editor_status(self, text=None):
        workspace = self.workspaces.get(self.profile.id) if self.profile else None
        if text is None:
            text = (
                workspace.editor.current_status_text()
                if workspace else "พร้อมใช้งาน  ·  0 คำ  ·  0 อักขระ"
            )
        full_text = text or "พร้อมใช้งาน  ·  0 คำ  ·  0 อักขระ"
        self.editor_status.setFullText(full_text)

        if not self.profile:
            self.progress_status.setFullText("วันนี้ +0 บท")
            self.goal_status.setFullText("ยังไม่ได้ตั้งเป้าหมาย")
            self.context_status.setFullText("ยังไม่ได้เลือก Context")
            self.goal_status_bar.hide()
            return

        today = daily_chapter_count(self.profile)
        latest = getattr(self, "_latest_context_chapter", None)
        today_text = f"วันนี้ +{today} บท"
        if latest is not None:
            progress_tooltip = f"วันนี้ {today} บท · Context ล่าสุดบท {latest}"
        else:
            progress_tooltip = "จำนวนบทใหม่จาก Translator Export ที่สำเร็จครบทุกขั้นตอน"
        self.progress_status.setFullText(today_text)
        if workspace:
            workspace.novel_header.refresh(self.profile, latest)
            workspace.editor.export_tab.refresh_verified()
        self.progress_status.setToolTip(progress_tooltip)

        goal = goal_progress(self.profile)
        if goal:
            completed, target, percentage = goal
            self.goal_status.setFullText(f"เป้าหมาย {completed}/{target} บท · {percentage}%")
            self.goal_status_bar.setValue(percentage)
            self.goal_status_bar.hide()
            self.goal_status.setToolTip(f"{self.profile.name}: {completed} จาก {target} บท")
        else:
            self.goal_status.setFullText("ยังไม่ได้ตั้งเป้าหมาย")
            self.goal_status_bar.hide()
            self.goal_status.setToolTip(f"{self.profile.name}: ยังไม่ได้ตั้งเป้าหมาย")

    def closeEvent(self, event):
        pending = self._pending_export_profiles()
        if pending and not self._close_export_reminder_accepted:
            entries = "\n".join(f"• {profile.name} — {path.name}" for profile, path in pending)
            dialog = QMessageBox(self)
            dialog.setWindowTitle("ยังไม่ได้ Export งานแปล!")
            dialog.setIcon(QMessageBox.Warning)
            dialog.setText(f"มี Translator ที่ยังไม่ได้ Export:\n{entries}")
            later_button = dialog.addButton("Later", QMessageBox.AcceptRole)
            cancel_button = dialog.addButton("Cancel", QMessageBox.RejectRole)
            dialog.exec()
            if dialog.clickedButton() is not later_button:
                event.ignore()
                return
            self._close_export_reminder_accepted = True
        self._automatic_update_timer.stop()
        timer = getattr(self, "_session_save_timer", None)
        if timer is not None:
            timer.stop()
        workers = [self._update_check_worker, self._update_download_worker]
        workers.extend(self._history_workers)
        inspector_page = self._utility_pages.get("novel-inspector")
        if inspector_page is not None:
            workers.extend([inspector_page.worker, inspector_page.write_worker])
        for worker in workers:
            if worker and worker.isRunning():
                worker.requestInterruption()
                if not getattr(worker, "_close_resume_connected", False):
                    worker._close_resume_connected = True
                    worker.finished.connect(lambda: QTimer.singleShot(0, self.close))
                self.statusBar().showMessage('กำลังบันทึกประวัติให้เสร็จก่อนปิดโปรแกรม…' if isinstance(worker, HistoryWorker)
                                            else 'กำลังยกเลิกงานเบื้องหลังก่อนปิดโปรแกรม…')
                event.ignore()
                return
        for workspace in self.workspaces.values():
            if not workspace.editor.save_all(include_normalization=False):
                event.ignore()
                return

        self._capture_sessions()
        self.repo.save_settings(self.settings)
        event.accept()


ProfileWorkspace = WorkspacePage


class MainWindow(MainShell):
    """Public entry point for the composed desktop shell."""
    pass
