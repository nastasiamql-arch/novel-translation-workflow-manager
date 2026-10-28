from __future__ import annotations

import shutil
import tempfile
import hashlib
import os
import re
from datetime import date, datetime, datetime as DateTime
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
        # Kept only as the management/file-binding adapter used by the existing
        # ManagementActionsMixin. It has no visible rows or copy-action buttons.
        self.steps = QListWidget(self)
        self.steps.setObjectName("workflowSteps")
        self.steps.setSelectionMode(QAbstractItemView.NoSelection)
        self.steps.hide()
        self.vocabulary_mode = False
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
        sidebar_root = QVBoxLayout(self.sidebar)
        sidebar_root.setContentsMargins(0, 0, 0, 0)
        sidebar_root.setSpacing(0)
        self.sidebar_normal = QWidget(self.sidebar)
        sidebar_root.addWidget(self.sidebar_normal, 1)
        sidebar_layout = QVBoxLayout(self.sidebar_normal)
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
        self.history_button = QPushButton('Novel Polish')
        self.history_button.clicked.connect(lambda: self.owner.open_polish_history())
        history_row.addWidget(self.history_button)
        self.history_range = QLineEdit()
        self.history_range.setPlaceholderText('ช่วงบท เช่น 6-10')
        self.history_range.setAccessibleName('ช่วงบทสำหรับประวัติใหม่')
        self.history_range.setToolTip('กรอกเมื่อไม่สามารถยืนยันช่วงบทจากไฟล์เนื้อหาได้ · ไม่อ่านช่วงบทจาก Context')
        self.history_range.setMinimumWidth(0)
        history_row.addWidget(self.history_range, 1)
        sidebar_layout.addLayout(history_row)
        tools_heading = QLabel("เครื่องมือทำงาน")
        tools_heading.setObjectName("sectionHeading")
        sidebar_layout.addWidget(tools_heading)
        self.editor_shortcut = QPushButton("Editor")
        self.editor_shortcut.setObjectName("workspaceEditorShortcut")
        self.editor_shortcut.setCheckable(True)
        self.editor_shortcut.clicked.connect(self.open_editor)
        sidebar_layout.addWidget(self.editor_shortcut)
        self.txt_vocabulary_shortcut = QPushButton("หาศัพท์")
        self.txt_vocabulary_shortcut.setObjectName("txtVocabularyShortcut")
        self.txt_vocabulary_shortcut.setCheckable(True)
        self.txt_vocabulary_shortcut.clicked.connect(
            lambda checked=False: self.owner.open_txt_vocabulary(self.profile_id)
        )
        sidebar_layout.addWidget(self.txt_vocabulary_shortcut)
        self.translation_batch_shortcut = QPushButton("แปล")
        self.translation_batch_shortcut.setObjectName("translationBatchShortcut")
        self.translation_batch_shortcut.setCheckable(True)
        self.translation_batch_shortcut.clicked.connect(
            lambda checked=False: self.owner.open_translation_batches(self.profile_id)
        )
        sidebar_layout.addWidget(self.translation_batch_shortcut)
        self.current_step_label = QLabel("ขั้นตอนปัจจุบัน")
        self.current_step_label.setObjectName("sectionHeading")
        sidebar_layout.addWidget(self.current_step_label)
        self.step_selector = QComboBox()
        self.step_selector.setObjectName("workspaceStepSelector")
        self.step_selector.setAccessibleName("ขั้นตอนปัจจุบัน")
        self.step_selector.setToolTip("เลือกขั้นตอนโดยไม่คัดลอกไฟล์ · คลิกขวาเพื่อดูคำสั่งคัดลอกขั้นตอน")
        self.step_selector.setMinimumHeight(38)
        self.step_selector.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.step_selector.currentIndexChanged.connect(
            lambda _index: self.owner._sidebar_step_selected(self.profile_id)
        )
        self.step_selector.setContextMenuPolicy(Qt.CustomContextMenu)
        self.step_selector.customContextMenuRequested.connect(
            lambda pos: self.owner._workspace_step_menu(self.profile_id, pos)
        )
        sidebar_layout.addWidget(self.step_selector)
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

        # The same sidebar keeps its file/step controls mounted in both modes;
        # focus uses a narrow rail, never a second EditorTabs instance.
        self.focus_rail = QWidget(self.sidebar)
        rail_layout = QVBoxLayout(self.focus_rail)
        rail_layout.setContentsMargins(3, 8, 3, 8)
        rail_layout.setSpacing(6)
        self.focus_buttons = {}
        for name, glyph, title, callback in (
            ("editor", "▤", "Editor", self.open_editor),
            ("vocabulary", "字", "หาศัพท์", lambda: self.owner.open_txt_vocabulary(self.profile_id)),
            ("translation", "文", "แปล", lambda: self.owner.open_translation_batches(self.profile_id)),
        ):
            button = QToolButton(self.focus_rail)
            button.setText(glyph)
            button.setObjectName("focus" + name.title())
            button.setToolTip(title)
            button.setAccessibleName(title)
            button.setCheckable(True)
            button.setMinimumHeight(40)
            button.clicked.connect(callback)
            rail_layout.addWidget(button)
            self.focus_buttons[name] = button
        self.focus_step_button = QToolButton(self.focus_rail)
        self.focus_step_button.setText("☷")
        self.focus_step_button.setToolTip("ขั้นตอนปัจจุบัน")
        self.focus_step_button.setAccessibleName("เลือกขั้นตอนปัจจุบัน")
        self.focus_step_menu = QMenu(self.focus_step_button)
        self.focus_step_menu.aboutToShow.connect(self._fill_focus_step_menu)
        self.focus_step_button.setMenu(self.focus_step_menu)
        self.focus_step_button.setPopupMode(QToolButton.InstantPopup)
        self.focus_step_button.setMinimumHeight(40)
        rail_layout.addWidget(self.focus_step_button)
        self.focus_files_button = QToolButton(self.focus_rail)
        self.focus_files_button.setText("▤")
        self.focus_files_button.setToolTip("ไฟล์และการจัดการไฟล์")
        self.focus_files_button.setAccessibleName("เปิดและจัดการไฟล์")
        self.focus_files_menu = QMenu(self.focus_files_button)
        self.focus_files_menu.aboutToShow.connect(self._fill_focus_files_menu)
        self.focus_files_button.setMenu(self.focus_files_menu)
        self.focus_files_button.setPopupMode(QToolButton.InstantPopup)
        self.focus_files_button.setMinimumHeight(40)
        rail_layout.addWidget(self.focus_files_button)
        rail_layout.addStretch(1)
        sidebar_root.addWidget(self.focus_rail)
        self.focus_rail.hide()
        self._focus_mode = False
        self._view_ready = False

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
        self.editor_content_stack.currentChanged.connect(
            lambda _index: self._sync_tool_buttons()
        )
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
        self.workspace_splitter.setSizes([max(220, int(owner.settings.sidebar_width or 290)), 900])
        self.workspace_splitter.splitterMoved.connect(self._remember_sidebar_width)
        self.set_focus_mode(bool(getattr(owner.settings, "workspace_focus_mode", False)
                                 or not owner.settings.sidebar_visible), persist=False)

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
        self._view_ready = True
        self._sync_tool_buttons()

    def _sync_tool_buttons(self):
        """Selected appearance follows the existing stacked widget, not the step."""
        current = self.editor_content_stack.currentWidget()
        for button, target in (
            (self.editor_shortcut, self.editor),
            (self.txt_vocabulary_shortcut, self.txt_vocabulary_page),
            (self.translation_batch_shortcut, self.translation_batch_page),
        ):
            button.setChecked(target is not None and current is target)
        view = ("translation" if current is self.translation_batch_page and self.translation_batch_page is not None
                else "vocabulary" if current is self.txt_vocabulary_page and self.txt_vocabulary_page is not None
                else "editor")
        for name, button in self.focus_buttons.items():
            button.setChecked(name == view)
        if self._view_ready:
            views = self.owner.settings.workspace_active_views
            if views.get(self.profile_id) != view:
                views[self.profile_id] = view
                self.owner._schedule_workspace_session_save()

    def open_editor(self):
        """Return to the one existing EditorTabs without changing its session."""
        self.workspace_sections.blockSignals(True)
        self.workspace_sections.setCurrentIndex(0)
        self.workspace_sections.blockSignals(False)
        self.editor_content_stack.setCurrentWidget(self.editor)
        self._sync_tool_buttons()

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
        # Keep the last user-chosen normal width; Qt's splitter clamps it as
        # needed for small windows without overwriting the persisted setting.

    def _fill_focus_step_menu(self):
        self.focus_step_menu.clear()
        for index in range(self.step_selector.count()):
            action = self.focus_step_menu.addAction(self.step_selector.itemText(index))
            action.setCheckable(True)
            action.setChecked(index == self.step_selector.currentIndex())
            action.triggered.connect(
                lambda _checked=False, row=index: self.step_selector.setCurrentIndex(row)
            )

    def _fill_focus_files_menu(self):
        self.focus_files_menu.clear()
        for index in range(self.files.count()):
            item = self.files.item(index)
            if item.isHidden():
                continue
            action = self.focus_files_menu.addAction(item.text())
            action.triggered.connect(
                lambda _checked=False, current=item: self.owner.open_workflow_file(self.profile_id, current)
            )
        self.focus_files_menu.addSeparator()
        for title, callback in (
            ("ไฟล์ใหม่", self.new_file), ("โฟลเดอร์ใหม่", self.new_folder),
            ("เปลี่ยนชื่อ", self.rename_selected), ("ลบ", self.delete_selected),
        ):
            self.focus_files_menu.addAction(title, callback)
        self.focus_files_menu.addAction("เปิด File Explorer", lambda: self.toggle_sidebar())

    def set_focus_mode(self, enabled: bool, *, persist=True):
        enabled = bool(enabled)
        if enabled == self._focus_mode and persist:
            return
        if not enabled and self._focus_mode:
            self.sidebar.setMinimumWidth(0)
            self.sidebar.setMaximumWidth(16777215)
        self._focus_mode = enabled
        self.sidebar_normal.setVisible(not enabled)
        self.focus_rail.setVisible(enabled)
        if enabled:
            widths = self.workspace_splitter.sizes()
            if widths and widths[0] > 100:
                self.owner.settings.sidebar_width = widths[0]
            self.sidebar.setFixedWidth(56)
            self.workspace_splitter.setSizes([56, max(1, self.workspace_splitter.width() - 56)])
        else:
            saved = max(220, int(self.owner.settings.sidebar_width or 290))
            self.workspace_splitter.setSizes([saved, max(1, self.workspace_splitter.width() - saved)])
        self.sidebar_toggle.setToolTip("กลับสู่มุมมองปกติ" if enabled else "ขยายพื้นที่ทำงาน (Focus)")
        self.sidebar_toggle.setAccessibleName("กลับสู่มุมมองปกติ" if enabled else "ขยายพื้นที่ทำงาน")
        if persist:
            self.owner.settings.workspace_focus_mode = enabled
            self.owner.settings.sidebar_visible = not enabled
            self.owner._schedule_workspace_session_save()

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
        self.refresh_context_update_button()

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
        review = (self.owner._chapter_review_status(self.owner.profile, path)
                  if chapter_allowed else None)
        if pending:
            label = "ตรวจเลขบท • รอตรวจ"
            tooltip = "มีบทใหม่รอตรวจ · กดเพื่อตรวจเลขบทเอง"
        elif review and review.get('current'):
            label = "✓ ตรวจเลขบทแล้ว"
            tooltip = "ตรวจล่าสุด: " + str(review.get('verified_at') or '') + "\n" + str(review.get('review_result') or '')
        elif review:
            label = "ตรวจเลขบท • ต้องตรวจใหม่"
            tooltip = "ต้นฉบับเปลี่ยนหลังตรวจครั้งล่าสุด · กรุณาตรวจเลขบทใหม่"
        else:
            label = "ตรวจเลขบท"
            tooltip = "ตรวจและแก้เลขหัวบทในต้นฉบับ · ไม่มี Export"
        self.chapter_number_button.setText(label)
        self.chapter_number_button.setToolTip(tooltip)
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
        record = self.owner._export_records(self.profile_id).get(key, {})
        export_detail = self.owner._export_status_errors.get(self.profile_id, "")
        if status in {"exported", "not_exported"} and record:
            try:
                exported_at = DateTime.fromisoformat(str(record.get('exported_at') or '')).astimezone().strftime('%d/%m/%Y %H:%M')
            except (ValueError, TypeError):
                exported_at = str(record.get('exported_at') or '')
            chapter_range = record.get('chapter_range')
            if chapter_range:
                export_detail = f"Export ล่าสุด: บท {chapter_range} · {exported_at}"
            elif exported_at:
                export_detail = f"Export ล่าสุด: {exported_at}"
            if status == "not_exported":
                export_detail += "\nTranslator เปลี่ยนหลัง Export · ต้อง Export เนื้อหาปัจจุบันใหม่"
        self.export_status_label.setText({
            "exported": "Exported",
            "not_exported": "Modified Since Export" if record and record.get('digest') else "Not Exported",
            "unknown": "Export Status Unknown",
            "error": "ตรวจสอบสถานะ Export ไม่สำเร็จ",
        }[status])
        self.export_status_label.setToolTip(export_detail)
        colors = theme_colors(self.owner.settings.appearance)
        if status in {"not_exported", "error"}:
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
                repo=self.owner.repo,
                profile_id=profile.id,
                draft_reader=lambda pid=profile.id: self.owner.repo.load_batch_draft(pid, "vocabulary"),
                draft_writer=lambda text, pid=profile.id: self.owner.repo.save_batch_draft(pid, "vocabulary", text),
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
        # Do not eject the user from an independent Translation Batch view.
        if self.editor_content_stack.currentWidget() is self.translation_batch_page and self.translation_batch_page is not None:
            return
        if show_files:
            self._ensure_txt_vocabulary_page()
            self.editor_content_stack.setCurrentWidget(self.txt_vocabulary_page)
        elif self.editor_content_stack.currentWidget() is self.txt_vocabulary_page and self.txt_vocabulary_page is not None:
            self.editor_content_stack.setCurrentWidget(self.editor)

    def filter_files(self, query):
        query = query.strip().casefold()
        for index in range(self.files.count()):
            item = self.files.item(index)
            item.setHidden(bool(query) and query not in item.text().casefold())

    def toggle_sidebar(self):
        self.set_focus_mode(not self._focus_mode)

    def _remember_sidebar_width(self, _position, index):
        sizes = self.workspace_splitter.sizes()
        if (not self._focus_mode and index == 1 and len(sizes) == 2
                and sizes[0] >= 180):
            self.owner.settings.sidebar_width = sizes[0]
            self.owner._schedule_workspace_session_save()

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
        self._export_status_errors = {}
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
        changed = not all((self.settings.appearance_migrated, self.settings.flat_vscode_theme_migrated, self.settings.editor_style_migrated))
        self.settings.appearance_migrated = True
        self.settings.flat_vscode_theme_migrated = True
        self.settings.editor_style_migrated = True
        if changed: self.repo.save_settings(self.settings)

    def showEvent(self, event):
        super().showEvent(event)
        if self.profile:
            QTimer.singleShot(0, lambda pid=self.profile.id: self._show_startup_export_reminder(pid))

    def apply_theme(self):
        super().apply_theme()
        if hasattr(self, "profile_cards"):
            self.profile_cards._update_library_grid_size()
        if hasattr(self, "navigation"):
            self.navigation.refresh_icons(self.settings.appearance)
        for workspace in getattr(self, "workspaces", {}).values():
            workspace.editor.set_appearance(self.settings.appearance)
            workspace.refresh_export_status()
        for page in getattr(self, "_utility_pages", {}).values():
            if isinstance(page, PolishHistoryPage):
                page.render()

    def show_submit_toast(self, message):
        self.submit_toast.show_message(message)

    def history_busy(self):
        return (self._history_pending or bool(self._pending_export_snapshots)
                or any(w.isRunning() for w in self._history_workers))

    def run_history_job(self, operation, success, failure=None):
        if self._history_pending:
            self.statusBar().showMessage('กำลังจัดการประวัติ กรุณารอสักครู่', 3000)
            return
        self._history_pending = True
        self.statusBar().showMessage('กำลังตรวจสอบและบันทึกไฟล์ประวัติ…')
        worker = HistoryWorker(operation, self)
        self._history_workers.append(worker)
        def complete(result):
            self._history_pending = False
            success(result)
            QTimer.singleShot(0, self._drain_export_snapshot_queue)
        def failed(error):
            self._history_pending = False
            self.statusBar().showMessage(str(error), 8000)
            if failure: failure(error)
            QTimer.singleShot(0, self._drain_export_snapshot_queue)
        worker.succeeded.connect(complete)
        worker.failed.connect(failed)
        def cleanup():
            # ``finished`` is emitted at the very end of run(), but the native
            # thread can remain alive for a brief finalization window. Join it
            # before dropping the last owner reference so close/next tests do
            # not race a worker still touching filesystem paths.
            worker.wait()
            self._history_workers.remove(worker)
            worker.deleteLater()
        worker.finished.connect(cleanup)
        worker.start()

    def open_polish_history(self):
        if not self.profile: return
        key = 'polish-history:' + self.profile.id
        self._show_utility_page(key, 'Novel Polish', lambda: PolishHistoryPage(self, self.profile))
        self._utility_pages[key].profile = self.profile
        self._utility_pages[key].refresh()

    def update_copy_mode_labels(self):
        """Reflect the persisted clipboard mode without changing Export controls."""
        zipped = self.settings.copy_files_as_zip
        for workspace in self.workspaces.values():
            workspace.copy_step_button.setText('COPY ZIP' if zipped else 'COPY STEP')
            workspace.copy_step_button.setToolTip(
                'รวมไฟล์ทั้งหมดของขั้นตอนที่เลือกเป็น ZIP เดียว · Ctrl+Shift+C' if zipped
                else 'คัดลอกไฟล์ของขั้นตอนที่เลือก · Ctrl+Shift+C')
        for page in self._utility_pages.values():
            if isinstance(page, PolishHistoryPage):
                # Update the existing buttons in place. Qt deleteLater() keeps old
                # card widgets discoverable until the event loop processes them.
                for button in page.findChildren(QPushButton, 'polishHistoryCopy'):
                    history_zip = self.settings.history_zip_for_profile(page.profile.id)
                    button.setText('คัดลอก ZIP' if history_zip else 'คัดลอก')
                    button.setToolTip(
                        'รวมไฟล์ทั้งหมดของรายการนี้เป็น ZIP เดียว · วางด้วย Ctrl+V' if history_zip
                        else 'คัดลอกไฟล์ทั้งหมดของรายการนี้ · วางด้วย Ctrl+V')

    def _history_clipboard(self, paths, count, zipped):
        from .clipboard_files import copy_file_paths
        copy_file_paths(paths)
        message = f'คัดลอก ZIP 1 ไฟล์ · ภายใน {count} ไฟล์' if zipped else f'คัดลอก {count} ไฟล์แล้ว'
        self.statusBar().showMessage(message + ' · วางด้วย Ctrl+V', 7000)

    def copy_history_snapshot(self, profile, snapshot):
        zipped = self.settings.history_zip_for_profile(profile.id)
        def operation():
            paths = self.polish_history.clipboard_paths(profile, snapshot.path, zipped=zipped)
            count = len(paths)
            if zipped:
                import zipfile
                with zipfile.ZipFile(paths[0]) as archive:
                    count = sum(not item.is_dir() for item in archive.infolist())
            return paths, count
        def publish(result):
            try:
                self._history_clipboard(result[0], result[1], zipped)
            except Exception as exc:
                self.statusBar().showMessage('ส่งไฟล์ไปยัง Clipboard ไม่สำเร็จ: ' + str(exc), 8000)
                return
            try:
                self._record_history_copy_success(profile, snapshot, result[1], zipped)
            except Exception as exc:
                self.statusBar().showMessage(
                    'คัดลอกไฟล์แล้ว แต่บันทึกสถานะการคัดลอกไม่สำเร็จ: ' + str(exc), 8000
                )
        self.run_history_job(operation, publish)

    def _record_history_copy_success(self, profile, snapshot, file_count, zipped):
        """Persist one durable event after the file Clipboard operation succeeds."""
        from datetime import datetime, timezone
        from uuid import uuid4
        step_id = str(snapshot.manifest.get('step_id') or profile.polish_history_step_id or 'all')
        key = f'{profile.id}:{step_id}'
        previous = self.settings.history_copy_state.get(key)
        previous_events = list(self.settings.history_copy_events.get(key, []))
        old_ends = []
        for item in previous_events:
            if not isinstance(item, dict) or item.get('result') != 'clipboard_set':
                continue
            match = re.fullmatch(r'\s*(\d+)(?:\s*[-–]\s*(\d+))?\s*', str(item.get('chapter_range') or ''))
            if match:
                old_ends.append(int(match.group(2) or match.group(1)))
        if not old_ends and isinstance(previous, dict):
            match = re.fullmatch(r'\s*(\d+)(?:\s*[-–]\s*(\d+))?\s*', str(previous.get('chapter_range') or ''))
            if match:
                old_ends.append(int(match.group(2) or match.group(1)))
        current_range = str(snapshot.manifest.get('chapter_range') or '')
        match = re.fullmatch(r'\s*(\d+)(?:\s*[-–]\s*(\d+))?\s*', current_range)
        new_end = int(match.group(2) or match.group(1)) if match else None
        old_forward = max(old_ends) if old_ends else None
        event = {
            'event_id': uuid4().hex, 'profile_id': profile.id, 'step_id': step_id,
            'snapshot_id': str(snapshot.manifest.get('snapshot_id') or snapshot.path.name),
            'chapter_range': current_range,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'file_count': int(file_count), 'mode': 'zip' if zipped else 'files',
            'result': 'clipboard_set',
        }
        self.settings.history_copy_events[key] = [*previous_events, event]
        self.settings.history_copy_state[key] = event
        try:
            self.repo.save_settings(self.settings)
        except (OSError, ValueError) as exc:
            if previous is None: self.settings.history_copy_state.pop(key, None)
            else: self.settings.history_copy_state[key] = previous
            if previous_events: self.settings.history_copy_events[key] = previous_events
            else: self.settings.history_copy_events.pop(key, None)
            self.statusBar().showMessage('คัดลอกสำเร็จ แต่บันทึกประวัติการคัดลอกไม่ได้: ' + str(exc), 8000)
            return False
        page = self._utility_pages.get('polish-history:' + profile.id)
        if isinstance(page, PolishHistoryPage):
            advanced = new_end is not None and (old_forward is None or new_end > old_forward)
            page.on_copy_success(snapshot, advanced=advanced)
        return True

    def _history_step_for_profile(self, profile):
        step_id = getattr(profile, 'polish_history_step_id', None)
        return next((step for step in profile.workflow.steps if step.id == step_id), None)

    def save_for_review(self):
        workspace = self.workspaces.get(self.profile.id) if self.profile else None
        if not self.profile or not workspace:
            return
        step = self._history_step_for_profile(self.profile)
        if step is None:
            self.statusBar().showMessage('เลือกขั้นตอนตรวจคำแปลใน Settings ก่อน', 6000)
            return
        if not workspace.editor.save_all(include_normalization=False):
            self.statusBar().showMessage('บันทึกไฟล์ Editor ไม่สำเร็จ จึงสร้างประวัติไม่ได้', 6000)
            return
        span = workspace.history_range.text().strip()
        from copy import deepcopy
        profile_copy, step_copy = deepcopy(self.profile), deepcopy(step)
        self.run_history_job(
            lambda: self.polish_history.create(profile_copy, step_copy, span),
            lambda snapshot: self.statusBar().showMessage(
                f'บันทึกไว้รอตรวจสำเร็จ · {snapshot.manifest["file_count"]} ไฟล์', 7000),
            lambda error: workspace.history_range.setFocus() if isinstance(error, RangeRequired) else None,
        )

    def snapshot_export_for_review(self, profile_id, chapter_range=None):
        if self._history_pending or any(worker.isRunning() for worker in self._history_workers):
            self._pending_export_snapshots.append((profile_id, chapter_range))
            return
        from copy import deepcopy
        profile = next((item for item in self.repo.list_profiles() if item.id == profile_id), None)
        if profile is None:
            profile = self.profile if self.profile and self.profile.id == profile_id else None
        step = self._history_step_for_profile(profile) if profile else None
        if profile is None or step is None:
            message = 'Export สำเร็จ แต่บันทึกประวัติรอตรวจไม่สำเร็จ'
            self.statusBar().showMessage(message, 8000)
            return
        profile_copy, step_copy = deepcopy(profile), deepcopy(step)
        def operation():
            return self.polish_history.create(profile_copy, step_copy, chapter_range, allow_unresolved=True, prefer_pre_export=True)
        def success(snapshot):
            span = snapshot.manifest.get('chapter_range')
            label = f'บท {span}' if span else 'รอระบุช่วงบท'
            message = f'Export สำเร็จ · บันทึกประวัติรอตรวจ {label} · {snapshot.manifest["file_count"]} ไฟล์'
            self.statusBar().showMessage(message, 9000)
        def failure(_error):
            message = 'Export สำเร็จ แต่บันทึกประวัติรอตรวจไม่สำเร็จ'
            self.statusBar().showMessage(message, 9000)
        self.run_history_job(operation, success, failure)

    def _drain_export_snapshot_queue(self):
        if self._history_pending or any(worker.isRunning() for worker in self._history_workers):
            if self._pending_export_snapshots:
                QTimer.singleShot(100, self._drain_export_snapshot_queue)
            return
        if self._pending_export_snapshots:
            profile_id, chapter_range = self._pending_export_snapshots.pop(0)
            self.snapshot_export_for_review(profile_id, chapter_range)

    def save_settings_history_step(self, _index):
        if not self.profile: return
        self.profile.polish_history_step_id = self.settings_history_step.currentData()
        self.save()

    def _show_utility_page(self, key, title, factory):
        if self._settings_page_state and key != "settings":
            self._restore_settings_management()
        if self.main_pages.currentWidget() is not self.utility_page and self._utility_return_page is None:
            self._utility_return_page = self.main_pages.currentWidget()
        page = self._utility_pages.get(key)
        if page is None:
            page = factory()
            self._utility_pages[key] = page
            self.utility_stack.addWidget(page)
        elif key == "progress":
            page.set_profiles(self.ps_list)
        elif key.startswith(("resources:", "novel-progress:")):
            page.refresh()
        elif key in {"groups", "launcher", "file-manager", "preview", "story-planner"}:
            self.utility_stack.removeWidget(page)
            page.deleteLater()
            page = factory()
            self._utility_pages[key] = page
            self.utility_stack.addWidget(page)
        self.utility_title.setText(title)
        self.utility_refresh.setVisible(key.startswith("polish-history:"))
        self.utility_back.setText("← กลับไปทำงาน" if self.profile else "← คลังนิยาย")
        self.utility_stack.setCurrentWidget(page)
        self._active_utility_page = key
        self.main_pages.setCurrentWidget(self.utility_page)
        if key == "settings" and page.layout():
            page.layout().activate()
            sidebar = page.findChild(QFrame, "preferencesSidebar")
            if sidebar and sidebar.layout():
                sidebar.layout().activate()
        self._sync_navigation()

    def return_from_utility_page(self):
        if self._settings_page_state:
            self._restore_settings_management()
        self._active_utility_page = None
        return_page = self._utility_return_page
        self._utility_return_page = None
        if return_page is self.library_page:
            self.main_pages.setCurrentWidget(self.library_page)
            return
        if self.profile:
            workspace = self.workspaces.get(self.profile.id)
            if workspace is None:
                workspace = self._workspace(self.profile)
            if workspace is None:
                return
            self.workspace_stack.setCurrentWidget(workspace)
            self.main_pages.setCurrentWidget(self.workspace_stack)
        else:
            self.main_pages.setCurrentWidget(self.library_page)

    def groups_dialog(self):
        self._show_utility_page("groups", "กลุ่มนิยาย", lambda: NovelGroupsPage(self))

    def translation_dashboard(self):
        profiles = self.ps_list

        def create_dashboard():
            from .progress_dialog import TranslationDashboardDialog
            return TranslationDashboardDialog(self, profiles, self.repo, self.refresh_translation_progress)

        self._show_utility_page("progress", "ความคืบหน้าการแปล", create_dashboard)

    def open_story_planner(self, profile_id):
        """Show the plan only for the currently selected novel."""
        from .story_planner_page import StoryPlannerPage
        if not any(profile.id == profile_id for profile in self.repo.list_profiles()):
            return
        self._show_utility_page("story-planner", "แผนการแปล",
                                lambda: StoryPlannerPage(self.repo, profile_id, self))

    def open_novel_resources(self, profile_id):
        """Show working files, Context, glossary and workflow for this novel."""
        from .novel_pages import NovelResourcesPage
        if not self.profile or self.profile.id != profile_id:
            return
        key = "resources:" + profile_id
        self._show_utility_page(
            key, "ไฟล์และคำศัพท์", lambda: NovelResourcesPage(self, profile_id, self))

    def open_novel_progress(self, profile_id):
        """Use confirmed Translator Export events without mixing novel ledgers."""
        from .novel_pages import NovelProgressPage
        if not self.profile or self.profile.id != profile_id:
            return
        key = "novel-progress:" + profile_id
        self._show_utility_page(
            key, "ความคืบหน้า", lambda: NovelProgressPage(self.repo, profile_id, self))

    def novel_inspector_dialog(self):
        """Standalone inspector; does not change translation stages."""
        from .novel_file_inspector_page import NovelFileInspectorPage
        self._show_utility_page("novel-inspector", "ตรวจสอบไฟล์นิยาย",
                                lambda: NovelFileInspectorPage(self.repo, self))

    def settings_dialog(self):
        if self._settings_page_state is None:
            self._build_settings_page()
        self._show_utility_page("settings", "ตั้งค่าและจัดการ", lambda: self._settings_page_state["page"])

    def delete_profile(self):
        profile_id = self.profile.id if self.profile else None
        super().delete_profile()
        if profile_id and not any(item.id == profile_id for item in self.repo.list_profiles()):
            self.settings.closed_workspace_profile_ids = [
                pid for pid in self.settings.closed_workspace_profile_ids if pid != profile_id
            ]
            self._open_workspace_ids = [pid for pid in self._open_workspace_ids if pid != profile_id]
            self._persist_workspace_session()

    def _build_settings_page(self):
        return SettingsPage.build(self, ReorderableProfileList)

    def program_settings_dialog(self):
        """Compatibility entry point into the single preferences page."""
        self.settings_dialog()
        self._settings_page_state["page"].select_category("General")

    def edit_workspace_goal(self, profile_id):
        """Edit this novel's goal in its own workspace, not in global settings."""
        profile = next((p for p in self.repo.list_profiles() if p.id == profile_id), None)
        if profile is None:
            return
        target, accepted = QInputDialog.getInt(
            self, f"เป้าหมายการแปล · {profile.name}",
            "จำนวนบทต่อรอบ (0 = ยกเลิกเป้าหมาย):",
            profile.translation_goal_target or 10, 0, 100000, 1,
        )
        if not accepted:
            return
        if profile.translation_goal_target is None or profile.translator_goal_baseline is None:
            profile.translator_goal_baseline = completed_chapter_count(profile)
        profile.translation_goal_target = target or None
        try:
            self.repo.save_profile(profile)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "บันทึกเป้าหมายไม่สำเร็จ", str(exc))
            return
        self.refresh_translation_progress()
        if self.profile and self.profile.id == profile_id and hasattr(self, "settings_goal_target"):
            self.settings_goal_target.setValue(target)
        self.statusBar().showMessage(
            "บันทึกเป้าหมายการแปลแล้ว" if target else "ยกเลิกเป้าหมายการแปลแล้ว", 3500
        )

    def reset_workspace_goal(self, profile_id):
        """Reset only this novel's goal baseline; keep its Export history intact."""
        profile = next((p for p in self.repo.list_profiles() if p.id == profile_id), None)
        if profile is None or goal_progress(profile) is None:
            return
        answer = QMessageBox.question(
            self, "รีเซ็ตเป้าหมายการแปล",
            f"เริ่มนับเป้าหมาย {profile.translation_goal_target} บทของ {profile.name} ใหม่จาก Translator Export ถัดไปใช่ไหม?\n\n"
            "ประวัติ Export และจำนวนบทที่แปลรายวันจะยังอยู่",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        reset_goal_progress(profile)
        try:
            self.repo.save_profile(profile)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "รีเซ็ตเป้าหมายไม่สำเร็จ", str(exc))
            return
        self.refresh_translation_progress()
        self.statusBar().showMessage("รีเซ็ตความคืบหน้าเป้าหมายแล้ว", 3500)

    def save_settings_goal_target(self):
        if not self.profile:
            return
        if self.profile.translation_goal_target is None or self.profile.translator_goal_baseline is None:
            self.profile.translator_goal_baseline = completed_chapter_count(self.profile)
        self.profile.translation_goal_target = self.settings_goal_target.value() or None
        self.save()
        self.refresh_translation_progress()
        self.statusBar().showMessage("บันทึกเป้าหมายนิยายแล้ว", 2500)

    def refresh_working_files(self):
        if not hasattr(self, "working_files"):
            return
        self.working_files.clear()
        if not self.profile:
            self.working_files.addItem("เลือกนิยายก่อน")
            return
        for file_ref in sorted(self.profile.working_files, key=lambda item: item.order):
            label = file_ref.label or Path(file_ref.path or "").name
            row = QListWidgetItem()
            row.setData(Qt.UserRole, file_ref.id)
            row.setToolTip(file_ref.path or "")
            row.setSizeHint(QSize(0, 38))
            self.working_files.addItem(row)
            row_widget = QWidget(self.working_files)
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(8, 2, 4, 2)
            row_label = QLabel(label)
            row_label.setToolTip(file_ref.path or "")
            row_layout.addWidget(row_label, 1)
            open_button = QPushButton("เปิด")
            open_button.clicked.connect(
                lambda checked=False, item_id=file_ref.id: self.open_working_file(item_id)
            )
            row_layout.addWidget(open_button)
            self.working_files.setItemWidget(row, row_widget)
        if not self.profile.working_files:
            self.working_files.addItem("ยังไม่มีไฟล์ · กด “เลือกหลายไฟล์” เพื่อเพิ่ม")

    def save_settings_auto_chapter_review(self, *_args):
        if not self.profile or not hasattr(self, "settings_auto_review_enabled"):
            return
        enabled = self.settings_auto_review_enabled.isChecked()
        self.profile.auto_review_enabled = enabled
        self.profile.auto_chapter_number_mode = (
            self.settings_auto_chapter_number_mode.currentData() if enabled else "off"
        )
        self.save()

    def refresh_settings_launch_targets(self):
        if not hasattr(self, "settings_launch_targets") or not self.profile:
            return
        self.settings_main_folder.setText(self.profile.main_folder)
        if hasattr(self, "settings_auto_review_enabled"):
            controls = (self.settings_auto_review_enabled, self.settings_auto_chapter_number_mode)
            for control in controls:
                control.blockSignals(True)
            try:
                self.settings_auto_review_enabled.setChecked(self.profile.auto_review_enabled)
                self.settings_auto_chapter_number_mode.setCurrentIndex(
                    1 if self.profile.auto_chapter_number_mode == "fix" else 0
                )
            finally:
                for control in controls:
                    control.blockSignals(False)
        if hasattr(self, 'settings_history_step'):
            self.settings_history_step.blockSignals(True)
            self.settings_history_step.clear()
            self.settings_history_step.addItem('ปิดการบันทึกชุดงาน', None)
            for step in self.profile.workflow.steps:
                self.settings_history_step.addItem(step.name, step.id)
            current = self.settings_history_step.findData(self.profile.polish_history_step_id)
            self.settings_history_step.setCurrentIndex(max(0, current))
            self.settings_history_step.blockSignals(False)
        context = Path(self.profile.context_path).expanduser() if self.profile.context_path else None
        if context and context.is_file():
            self.settings_context_hint.setText(
                f"✓ Context พร้อมใช้กับ Translator Export\n{context.name} · {context}"
            )
            self.settings_context_hint.setToolTip(str(context))
        elif context:
            self.settings_context_hint.setText(f"⚠ ไม่พบไฟล์ Context\n{context}")
            self.settings_context_hint.setToolTip(str(context))
        else:
            self.settings_context_hint.setText("⚠ ยังไม่ได้เชื่อม Context")
            self.settings_context_hint.setToolTip("")
        self.settings_goal_target.setValue(self.profile.translation_goal_target or 0)
        self.settings_launch_targets.blockSignals(True)
        self.settings_launch_targets.clear()
        for target in sorted(self.profile.launch_targets, key=lambda item: item.order):
            row = QListWidgetItem(f"{target.label or target.target}  ·  {target.kind}")
            row.setToolTip(target.target)
            row.setData(Qt.UserRole, target.id)
            row.setFlags(row.flags() | Qt.ItemIsUserCheckable)
            row.setCheckState(Qt.Checked if target.enabled else Qt.Unchecked)
            row.setSizeHint(QSize(0, 44))
            self.settings_launch_targets.addItem(row)
        self.settings_launch_targets.blockSignals(False)

    def save_settings_launch_target_state(self, _row):
        if not self.profile:
            return
        for index in range(self.settings_launch_targets.count()):
            row = self.settings_launch_targets.item(index)
            target = next((value for value in self.profile.launch_targets
                           if value.id == row.data(Qt.UserRole)), None)
            if target:
                target.enabled = row.checkState() == Qt.Checked
                target.order = index
        self.save()

    def choose_settings_main_folder(self):
        if not self.profile:
            return
        start = self.settings_main_folder.text()
        if not Path(start).is_dir():
            start = str(self.profile_browse_directory())
        selected = QFileDialog.getExistingDirectory(self, "เลือกโฟลเดอร์หลักของนิยาย", start)
        if selected:
            self.remember_profile_browse_directory(selected)
            self.settings_main_folder.setText(selected)
            self.save_settings_main_folder()

    def save_settings_main_folder(self):
        if not self.profile:
            return
        self.profile.main_folder = self.settings_main_folder.text().strip()
        self.save()
        self.statusBar().showMessage("บันทึกโฟลเดอร์หลักแล้ว", 2500)

    def configure_smart_files(self):
        """Preview bounded folder matches, then add confirmed links without clearing old ones."""
        if not self.profile:
            return
        from .smart_folder import SmartFolderDialog
        from copy import deepcopy
        profile = self.profile
        dialog = SmartFolderDialog(profile, self,
                                   shared_instruction_path=self.settings.shared_vocabulary_instruction_path)
        if dialog.exec() != QDialog.Accepted:
            return
        selections = {role: combo.currentData() for role, combo in dialog.combos.items()}
        # Validate the entire selection before mutating the active profile.
        for role, path in selections.items():
            if path and not Path(path).is_file():
                QMessageBox.warning(self, "ไฟล์เปลี่ยนแปลง", f"ไม่พบไฟล์ {role}:\n{path}\n\nโปรดสแกนใหม่หรือเลือกไฟล์อื่น")
                return
        updated = deepcopy(profile)
        updated.main_folder = str(Path(dialog.folder.text()).expanduser())
        updated.last_browse_directory = str(Path(updated.main_folder).resolve())
        updated.novel_code = dialog.code.text().strip()
        translate = next((step for step in updated.workflow.steps if step.name.strip() == "แปล"), None)
        review = next((step for step in updated.workflow.steps if step.name.strip() == "ตรวจคำแปล"), None)
        if translate is None and updated.workflow.steps:
            translate = updated.workflow.steps[0]
        mappings = (
            ("prompt", translate, "Prompt"), ("style", translate, "Style"),
            ("guideline", translate, "ไกด์ไลน์การแปล"), ("main", translate, "ไฟล์หลัก"),
            ("context", translate, "Context"), ("glossary", translate, "Glossary"),
            ("context", review, "Context"), ("glossary", review, "Glossary"),
            ("translator", review, "Translator"),
            ("novel", updated.vocabulary_step, "Novel"),
            ("vocab_instruction", updated.vocabulary_step, "คำสั่งหาศัพท์"),
        )
        for role, step, label in mappings:
            path = selections.get(role)
            if not step or not path:
                continue
            resolved = str(Path(path).expanduser().resolve())
            if any(item.path and str(Path(item.path).expanduser().resolve()) == resolved
                   for item in step.files if item.reference_type == "external_file"):
                continue
            step.files.append(StepFile(label=label, reference_type="external_file", path=resolved,
                                       file_type=role, order=len(step.files)))
        context = selections.get("context")
        if context:
            updated.context_path = str(Path(context).expanduser().resolve())
            updated.translation_checkpoint_path = updated.context_path
            try:
                chapter = read_context_chapter(Path(context))
                if chapter is not None:
                    updated.chapter_state.current_chapter = chapter
            except OSError:
                pass
        instruction = selections.get("vocab_instruction")
        previous_settings = deepcopy(self.settings)
        if instruction:
            updated.vocabulary_instruction_path = str(Path(instruction).expanduser().resolve())
            if dialog.shared_instruction.isChecked():
                self.settings.shared_vocabulary_instruction_path = updated.vocabulary_instruction_path
        try:
            if instruction and dialog.shared_instruction.isChecked():
                self.repo.save_settings(self.settings)
            self.repo.save_profile(updated)
        except (OSError, ValueError) as exc:
            if instruction and dialog.shared_instruction.isChecked():
                self.settings = previous_settings
                try: self.repo.save_settings(self.settings)
                except (OSError, ValueError): pass
            QMessageBox.warning(self, "บันทึกการตั้งค่าไม่สำเร็จ", str(exc))
            return
        profile.__dict__.update(updated.__dict__)
        self.refresh_profiles(updated.id)
        self.refresh_steps()
        self.refresh_files()
        self.refresh_settings_launch_targets()
        self.statusBar().showMessage("ตั้งค่าไฟล์นิยายแล้ว · รายการเดิมที่เชื่อมไว้ยังคงอยู่", 5000)

    def add_settings_launch_target(self, kind):
        if not self.profile:
            return
        if kind == "folder":
            targets = [QFileDialog.getExistingDirectory(self, "เลือกโฟลเดอร์", str(self.profile_browse_directory()))]
        elif kind == "file":
            targets, _ = QFileDialog.getOpenFileNames(
                self, "เลือกไฟล์ที่จะเปิดพร้อมเรื่อง (เลือกได้หลายไฟล์)",
                str(self.profile_browse_directory()), "ทุกไฟล์ (*)",
            )
        elif kind == "application":
            targets, _ = QFileDialog.getOpenFileNames(self, "เลือกโปรแกรม (เลือกได้หลายรายการ)", str(Path.home()), "โปรแกรม (*.exe);;ทุกไฟล์ (*)")
        else:
            target, accepted = QInputDialog.getText(self, "เพิ่มเว็บไซต์", "URL (http/https):")
            if not accepted:
                return
            targets = [target]
        targets = [target for target in targets if target]
        if not targets:
            return
        if kind in {"folder", "file", "application"}:
            self.remember_profile_browse_directory(targets[-1])
        if kind == "website":
            label, accepted = QInputDialog.getText(self, "ชื่อเว็บไซต์", "ชื่อ:", text=targets[0])
            if not accepted:
                return
            labels = [label]
        else:
            labels = [Path(target).name if kind != "website" else target for target in targets]
        for target, label in zip(targets, labels):
            self.profile.launch_targets.append(LaunchTarget(
                label=label, kind=kind, target=target, order=len(self.profile.launch_targets),
            ))
        self.save()
        self.refresh_settings_launch_targets()

    def remove_settings_launch_target(self):
        ids = {row.data(Qt.UserRole) for row in self.settings_launch_targets.selectedItems()}
        if not ids or not self.profile:
            return
        self.profile.launch_targets = [item for item in self.profile.launch_targets if item.id not in ids]
        for index, item in enumerate(self.profile.launch_targets):
            item.order = index
        self.save()
        self.refresh_settings_launch_targets()

    def add_working_files(self):
        if not self.profile:
            return
        sources, _ = QFileDialog.getOpenFileNames(
            self, "เลือกไฟล์สำหรับเปิดทำงาน (เลือกได้หลายไฟล์)",
            str(self.profile_browse_directory()),
            "ไฟล์ที่เปิดได้ (*.txt *.md *.markdown *.json *.yaml *.yml *.toml *.py *.js *.ts *.css *.html *.xml *.csv);;ทุกไฟล์ (*)",
        )
        if not sources:
            return
        self.remember_profile_browse_directory(sources[-1])
        profile_root = self.repo.profile_dir(self.profile.id).resolve()
        existing = {(item.reference_type, item.path) for item in self.profile.working_files}
        for source_value in sources:
            source = Path(source_value).expanduser().resolve()
            try:
                stored_path = source.relative_to(profile_root).as_posix()
                reference_type = "repository_file"
            except ValueError:
                stored_path = str(source)
                reference_type = "external_file"
            key = (reference_type, stored_path)
            if key in existing:
                continue
            self.profile.working_files.append(StepFile(
                label=source.name, reference_type=reference_type, path=stored_path,
                order=len(self.profile.working_files),
            ))
            existing.add(key)
        self.remember_profile_browse_directory(sources[-1])
        self.save()
        self.refresh_working_files()

    def _selected_working_file(self):
        row = self.working_files.currentItem() if hasattr(self, "working_files") else None
        if not row or not self.profile:
            return None
        return next((item for item in self.profile.working_files if item.id == row.data(Qt.UserRole)), None)

    def open_selected_working_file(self, *_args):
        ids = [row.data(Qt.UserRole) for row in self.working_files.selectedItems()]
        for item_id in ids:
            self.open_working_file(item_id)

    def open_working_file(self, item_id):
        item = next((value for value in self.profile.working_files if value.id == item_id), None) if self.profile else None
        if not item or not self.profile:
            return
        try:
            path = (Path(item.path).expanduser().resolve()
                    if item.reference_type == "external_file"
                    else self.repo.resolve_project_path(self.profile.id, item.path))
        except (OSError, ValueError, TypeError) as exc:
            QMessageBox.warning(self, "เปิดไฟล์ไม่ได้", str(exc))
            return
        workspace = self.workspaces.get(self.profile.id)
        if not workspace:
            return
        if workspace.editor.open_file(path):
            workspace.breadcrumb.setText(f"{self.profile.name}  ›  ไฟล์ทำงาน  ›  {path.name}")
            self.return_from_utility_page()

    def save_working_tabs_open_setting(self, enabled):
        if not self.profile:
            return
        self.profile.open_working_tabs_on_open = bool(enabled)
        self.repo.save_profile(self.profile)
        self.statusBar().showMessage("บันทึกการตั้งค่าการเปิดไฟล์ของนิยายแล้ว", 2500)

    def move_working_file(self, direction):
        if not self.profile or not hasattr(self, "working_files"):
            return
        row = self.working_files.currentRow()
        files = sorted(self.profile.working_files, key=lambda item: item.order)
        target = row + int(direction)
        if row < 0 or target < 0 or target >= len(files):
            return
        files[row], files[target] = files[target], files[row]
        for index, item in enumerate(files):
            item.order = index
        self.profile.working_files = files
        self.save()
        self.refresh_working_files()
        self.working_files.setCurrentRow(target)

    def remove_working_file(self):
        ids = {row.data(Qt.UserRole) for row in self.working_files.selectedItems()}
        if not ids or not self.profile:
            return
        self.profile.working_files = [value for value in self.profile.working_files if value.id not in ids]
        for index, value in enumerate(self.profile.working_files):
            value.order = index
        self.save()
        self.refresh_working_files()

    def show_vocabulary_files(self):
        """Select the vocabulary step in the combined novel settings page."""
        if not self._settings_page_state:
            self.settings_dialog()
        self._settings_page_state["page"].select_category("Workflow Files")
        vocabulary_row = len(self.profile.workflow.steps) if self.profile else -1
        if vocabulary_row >= 0:
            self.steps.setCurrentRow(vocabulary_row)
        self.refresh_files()

    def _open_selected_step_files(self, item):
        if item.data(Qt.UserRole) == "vocabulary-step" and self._settings_page_state:
            self._management_vocabulary_mode = True

    def _restore_settings_management(self):
        state = self._settings_page_state
        if not state:
            return
        profile_id = self.profile.id if self.profile else state["profile_id"]
        self.profiles, self.steps, self.files = state["original_lists"]
        self._settings_page_state = None
        self._settings_open = False
        self._management_vocabulary_mode = False
        self.refresh_profiles(profile_id)
        workspace = self.workspaces.get(profile_id) if profile_id else None
        if workspace and state.get("vocabulary_mode"):
            workspace.vocabulary_mode = True
            self._sync_stage_buttons(workspace)
            self.refresh_files()
        elif self.profile and self.profile.workflow.steps:
            row = next((index for index, step in enumerate(self.profile.workflow.steps)
                        if step.id == state["step_id"]), self.si)
            if 0 <= row < len(self.profile.workflow.steps):
                self.steps.setCurrentRow(row)
        page = state["page"]
        self._utility_pages.pop("settings", None)
        self.utility_stack.removeWidget(page)
        page.deleteLater()

    def _persist_profile_order(self, profile_ids):
        """Persist profile order after a drag in Settings → Novels."""
        profiles = {profile.id: profile for profile in self.repo.list_profiles()}
        if len(profile_ids) != len(profiles) or set(profile_ids) != set(profiles):
            return
        for order, profile_id in enumerate(profile_ids):
            profile = profiles[profile_id]
            if profile.order != order:
                profile.order = order
                self.repo.save_profile(profile)
        self.ps_list = [profiles[profile_id] for profile_id in profile_ids]
        if self.profile and self.profile.id in profiles:
            self.profile = profiles[self.profile.id]

    def launcher_dialog(self):
        """Compatibility action that now leads to the one-page novel settings."""
        self.settings_dialog()
        self._settings_page_state["page"].select_category("Novel")
        if self.profile:
            self.statusBar().showMessage(
                "ตั้งค่าโฟลเดอร์และไฟล์ที่เปิดพร้อมเรื่องได้ในหน้านี้", 3500
            )

    def preview(self):
        if not self.profile or not self.step():
            return
        try:
            text = self.assembler.assemble(
                self.profile, self.step(), self.settings.separator,
                self.settings.show_filename_heading,
            )
        except Exception as exc:
            QMessageBox.warning(self, "ดูตัวอย่างไม่ได้", str(exc))
            return
        page = QWidget()
        layout = QVBoxLayout(page)
        preview = QTextEdit()
        preview.setReadOnly(True)
        preview.setPlainText(text)
        layout.addWidget(preview, 1)
        footer = QHBoxLayout()
        footer.addWidget(QLabel(f"{len(text):,} อักขระ"), 1)
        copy = QPushButton("คัดลอกเนื้อหา")
        copy.clicked.connect(lambda: (QApplication.clipboard().setText(text), self.statusBar().showMessage("คัดลอกแล้ว", 2500)))
        footer.addWidget(copy)
        layout.addLayout(footer)
        self._show_utility_page("preview", f"ตัวอย่าง · {self.step().name}", lambda: page)

    def edit_file(self):
        if not self.profile or not self.file():
            return
        item = self.file()
        if item.reference_type == "dynamic":
            return
        path = (Path(item.path).expanduser().resolve()
                if item.reference_type == "external_file"
                else self.repo.resolve_project_path(self.profile.id, item.path))
        editor = self.editor_for_profile(self.profile.id)
        if editor and editor.open_file(path):
            self.return_from_utility_page()

    def editor_for_profile(self, profile_id):
        workspace = self.workspaces.get(profile_id)
        return workspace.editor if workspace else None

    def file_manager(self):
        if not self.profile:
            return
        profile = self.profile
        root = self.repo.profile_dir(profile.id)
        page = QWidget()
        layout = QVBoxLayout(page)
        search = QLineEdit()
        search.setPlaceholderText("ค้นหาชื่อไฟล์หรือโฟลเดอร์")
        layout.addWidget(search)
        listing = QListWidget()
        listing.setObjectName("fileManagerList")
        listing.setSelectionMode(QAbstractItemView.ExtendedSelection)
        layout.addWidget(listing, 1)

        def refresh(query=""):
            listing.clear()
            folded = query.casefold()
            for path in sorted(root.rglob("*")):
                if path.is_file() and path.name != "profile.json":
                    relative = path.relative_to(root).as_posix()
                    if not folded or folded in relative.casefold():
                        listing.addItem(relative)

        def selected_path():
            row = listing.currentItem()
            return self.repo.resolve_project_path(profile.id, row.text()) if row else None

        def selected_paths():
            return [self.repo.resolve_project_path(profile.id,row.text()) for row in listing.selectedItems()]

        def open_selected():
            workspace = self.workspaces.get(profile.id)
            opened = False
            for path in selected_paths():
                if workspace and workspace.editor.supports(path):
                    opened = workspace.editor.open_file(path) or opened
            if opened:self.return_from_utility_page()

        actions = QHBoxLayout()
        create = QPushButton("＋ ไฟล์ใหม่")
        def create_file():
            relative, accepted = QInputDialog.getText(self, "ไฟล์ใหม่", "ตำแหน่งสัมพัทธ์:", text="reference/new.txt")
            if not accepted or not relative:
                return
            path = self.repo.resolve_project_path(profile.id, relative)
            if path.suffix.lower() not in (".txt", ".md", ".json") or path.exists():
                QMessageBox.warning(self, "สร้างไฟล์ไม่ได้", "เลือก .txt, .md หรือ .json และใช้ชื่อที่ยังไม่มี")
                return
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")
            refresh(search.text())
            workspace = self.workspaces.get(profile.id)
            if workspace:
                workspace.editor.open_file(path)
                self.return_from_utility_page()
        create.clicked.connect(create_file)
        actions.addWidget(create)

        import_button = QPushButton("นำเข้าไฟล์")
        def import_file():
            sources, _ = QFileDialog.getOpenFileNames(
                self,
                "เลือกไฟล์ที่จะนำเข้า (เลือกหลายไฟล์ได้ด้วย Ctrl/Shift)",
                str(self.profile_browse_directory()),
                "ไฟล์ข้อความ (*.txt *.md *.json);;ทุกไฟล์ (*)",
            )
            if not sources:
                return
            self.remember_profile_browse_directory(sources[-1])
            relative, accepted = QInputDialog.getText(
                self,
                "นำเข้าไฟล์",
                f"โฟลเดอร์ปลายทางในเรื่องนี้ (เลือก {len(sources)} ไฟล์):",
                text="reference",
            )
            if not accepted or not relative:
                return
            try:
                destination = self.repo.resolve_project_path(profile.id, relative)
            except (ValueError, OSError) as exc:
                QMessageBox.warning(self, "นำเข้าไม่ได้", f"โฟลเดอร์ปลายทางไม่ถูกต้อง: {exc}")
                return
            if destination.exists() and not destination.is_dir():
                QMessageBox.warning(self, "นำเข้าไม่ได้", "ตำแหน่งปลายทางต้องเป็นโฟลเดอร์")
                return
            try:
                copied, skipped = import_files_into_directory(sources, destination)
            except OSError as exc:
                QMessageBox.warning(self, "นำเข้าไม่ได้", str(exc))
                return
            refresh(search.text())
            message = f"นำเข้าแล้ว {copied} ไฟล์"
            if skipped:
                message += f" · ข้าม {skipped} ไฟล์ (ชนชื่อหรือไม่รองรับ)"
            self.statusBar().showMessage(message, 6000)
        import_button.clicked.connect(import_file)
        actions.addWidget(import_button)

        open_button = QPushButton("เปิด/แก้ไข")
        open_button.clicked.connect(open_selected)
        actions.addWidget(open_button)

        attach = QPushButton("เพิ่มในขั้นตอน")
        def attach_file():
            step = self.step()
            if not step:return
            existing={file.path for file in step.files}
            for path in selected_paths():
                relative=path.relative_to(root).as_posix()
                if relative not in existing:
                    step.files.append(StepFile(label=path.stem,path=relative,file_type=path.parent.name,order=len(step.files)))
                    existing.add(relative)
            self.save();self.refresh_files()
        attach.clicked.connect(attach_file)
        actions.addWidget(attach)

        rename = QPushButton("เปลี่ยนชื่อ")
        def rename_file():
            path = selected_path()
            if not path:
                return
            relative, accepted = QInputDialog.getText(self, "เปลี่ยนชื่อไฟล์", "ชื่อใหม่:", text=path.relative_to(root).as_posix())
            if not accepted:
                return
            destination = self.repo.resolve_project_path(profile.id, relative)
            if destination.exists():
                QMessageBox.warning(self, "เปลี่ยนชื่อไม่ได้", "มีปลายทางนี้แล้ว")
                return
            destination.parent.mkdir(parents=True, exist_ok=True)
            old_relative = path.relative_to(root).as_posix()
            path.rename(destination)
            new_relative = destination.relative_to(root).as_posix()
            for step in profile.workflow.steps:
                for file in step.files:
                    if file.path == old_relative:
                        file.path = new_relative
            self.save()
            refresh(search.text())
        rename.clicked.connect(rename_file)
        listing.itemSelectionChanged.connect(lambda: rename.setEnabled(len(listing.selectedItems()) == 1))
        rename.setEnabled(False)
        actions.addWidget(rename)

        delete = QPushButton("ลบไฟล์")
        def delete_file():
            paths=selected_paths()
            if not paths:return
            names="\n".join(path.name for path in paths[:10])
            if QMessageBox.question(self,"ลบไฟล์",f"ลบ {len(paths)} ไฟล์ถาวรใช่ไหม?\n{names}") != QMessageBox.Yes:return
            removed=set();errors=[]
            for path in paths:
                try:path.unlink();removed.add(path)
                except OSError as exc:errors.append(f"{path.name}: {exc}")
            steps=list(profile.workflow.steps)
            if profile.vocabulary_step:steps.append(profile.vocabulary_step)
            for step in steps:
                step.files=[file for file in step.files if file.reference_type == "external_file" or not file.path or self.repo.resolve_project_path(profile.id,file.path) not in removed]
            profile.working_files=[file for file in profile.working_files if file.reference_type == "external_file" or not file.path or self.repo.resolve_project_path(profile.id,file.path) not in removed]
            self.save();self.refresh_files();refresh(search.text())
            if errors:QMessageBox.warning(self,"ลบบางไฟล์ไม่ได้","\n".join(errors))
        delete.clicked.connect(delete_file)
        actions.addWidget(delete)
        layout.addLayout(actions)
        search.textChanged.connect(refresh)
        listing.itemDoubleClicked.connect(lambda _item: open_selected())
        refresh()
        self._show_utility_page("file-manager", "จัดการไฟล์โครงการ", lambda: page)

    def _schedule_context_refresh(self, *_args):
        self.context_refresh_timer.start()

    def _watch_context_paths(self):
        watcher = getattr(self, "context_watcher", None)
        if watcher is None:
            return
        watched = watcher.files() + watcher.directories()
        if watched:
            watcher.removePaths(watched)
        files = set()
        directories = set()
        for profile in getattr(self, "ps_list", []):
            if not profile.context_path:
                continue
            path = Path(profile.context_path).expanduser()
            try:
                if path.is_file():
                    files.add(str(path.resolve()))
                    if path.parent.is_dir():
                        directories.add(str(path.parent.resolve()))
            except OSError:
                continue
        to_watch = list(files | directories)
        if to_watch:
            watcher.addPaths(to_watch)

    def undo_context_retranslation(self, profile_id):
        try:
            profile = self.repo.load_profile(profile_id)
            resets = [r for r in profile.translation_retranslation_resets
                      if isinstance(r, dict) and r.get("active") is True]
            if not resets:
                QMessageBox.information(self, "คืนสถานะย้อนแปล", "ไม่มีการย้อนแปลที่ต้องคืนสถานะ")
                return
            last = resets[-1]
            if QMessageBox.question(
                self, "คืนสถานะการนับบท",
                f"คืนสถานะก่อนย้อนแปลจากบท {last['start_chapter']}?\n"
                "ประวัติและไฟล์ Export ทั้งหมดยังคงอยู่",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            ) != QMessageBox.Yes:
                return
            if undo_retranslation(profile, last.get("reset_id")):
                self.repo.save_profile(profile)
                self.refresh_translation_progress()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "คืนสถานะไม่สำเร็จ", str(exc))

    def review_context_retranslation(self, profile_id):
        """Explicit preview and confirmation; Context never resets Export by itself."""
        try:
            profile = self.repo.load_profile(profile_id)
            if not profile.context_path:
                QMessageBox.information(self, "ตรวจ Context", "เลือกไฟล์ Context ของเรื่องนี้ก่อน")
                return
            path = Path(profile.context_path).expanduser().resolve()
            if not path.is_file():
                QMessageBox.warning(self, "ตรวจ Context", "ไม่พบไฟล์ Context ที่เลือก")
                return
            workspace = self.workspaces.get(profile_id)
            if workspace:
                for index in range(workspace.editor.tabs.count()):
                    editor = workspace.editor.tabs.widget(index)
                    if workspace.editor._path(editor) == path and workspace.editor._dirty(editor):
                        if not workspace.editor.save_editor(editor, quiet=True):
                            QMessageBox.warning(self, "ตรวจ Context", "บันทึก Context ไม่สำเร็จ")
                            return
            text = path.read_text(encoding="utf-8-sig")
            chapter, detected = retranslation_context_candidate(text)
            if chapter is None:
                found = ", ".join(str(n) for n in detected[-12:]) if detected else "ไม่พบ"
                value, ok = QInputDialog.getInt(
                    self, "ยืนยันเลขบท",
                    f"เลขบทใน Context ไม่ชัดเจน (ที่พบ: {found})\nกรอกบทล่าสุดที่ยืนยันด้วยตัวเอง:",
                    value=detected[-1] if detected else 1, min=1, max=2147483646)
                if not ok:
                    return
                chapter = value
            start = chapter + 1
            preview = retranslation_preview(profile, start)
            if not preview['chapters']:
                QMessageBox.information(self, "ย้อนแปลจาก Context",
                                        f"Context ล่าสุด: บท {chapter}\nไม่มีบทที่ต้องยกเลิกการนับ")
                return
            display = (
                f"Context ล่าสุด: บท {chapter}\nเสนอเริ่มแปล: บท {start}\n"
                f"Export เดิมสูงสุด: บท {preview['latest_export']}\n"
                f"ช่วงที่ได้รับผลกระทบ: บท {preview['chapters'][0]}–{preview['chapters'][-1]}\n"
                f"จำนวน: {preview['count']} บท\n\n"
                "ยกเลิกการนับเฉพาะบทเหล่านี้ โดยไม่ลบไฟล์และประวัติ Export?"
            )
            if QMessageBox.question(
                self, "ยืนยันย้อนแปลจาก Context", display,
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            ) != QMessageBox.Yes:
                return
            fresh = self.repo.load_profile(profile_id)
            record = confirm_retranslation(fresh, start, context_chapter=chapter,
                                           reason="Context-based retranslation")
            if record is not None:
                self.repo.save_profile(fresh)
                self.refresh_translation_progress()
                self.statusBar().showMessage(
                    f"เริ่มแปลใหม่บท {start} · ยกเลิกการนับ {preview['count']} บท", 8000)
        except (OSError, ValueError, UnicodeError) as exc:
            QMessageBox.warning(self, "ย้อนแปลไม่สำเร็จ", str(exc))

    def refresh_translation_progress(self):
        """Refresh confirmed Export activity plus informational Context state."""
        if any(getattr(listing,"_dragging",False) for listing in (self.profile_cards,self.profiles)):
            self.context_refresh_timer.start(250)
            return self.ps_list
        profiles = self.repo.list_profiles()
        for profile in profiles:
            if profile.id not in self.repo.export_recovery_errors and sync_profile_context(profile):
                try:
                    self.repo.save_profile(profile)
                except OSError as exc:
                    self.statusBar().showMessage(f"บันทึกความคืบหน้าไม่ได้: {exc}", 6000)
        self.ps_list = profiles
        by_id = {profile.id: profile for profile in profiles}
        for index in range(self.profile_cards.count()):
            card = self.profile_cards.item(index)
            profile = by_id.get(card.data(Qt.UserRole))
            if profile:
                # Library cards are strictly visual book shelves: title + cover.
                # Progress and verified information remain stored in profile data.
                card.setText(profile.name)
                final_goal = getattr(self, "_progress_goals", None)
                from .translation_planner import TranslationPlanner
                final = (TranslationPlanner(self.repo).finish_goal(profile.id) or {}).get("final_chapter")
                status = _profile_status_label(_profile_status(profile))
                if type(final) is int and final > 0:
                    within = len({n for n in completed_chapters(profile) if 1 <= n <= final})
                    footer = f"{status} · {within}/{final} บท"
                else:
                    footer = f"{status} · สำเร็จ {completed_chapter_count(profile)} บท"
                card.setData(Qt.UserRole + 2, footer)
                card.setToolTip(f"{profile.name}\n{footer}")
        if self.profile:
            fresh = next((item for item in profiles if item.id == self.profile.id), None)
            if fresh:
                self.profile = fresh
        self._watch_context_paths()
        if hasattr(self, 'today_page'):
            self.today_page.refresh()
        if self.profile:
            self.refresh_goal_indicator()
            self._update_editor_status()
        dashboard = self._utility_pages.get("progress")
        if dashboard is not None:
            dashboard.set_profiles(profiles)
        return profiles

    def build(self):
        self._settings_open = False
        self.workspaces = {}
        # Keep two recently visited workspaces warm without opening multiple novels.
        self._workspace_cache = {}
        self._workspace_cache_host = QWidget(self)
        self._workspace_cache_host.hide()
        # Old multi-novel sessions retain per-novel file state, not open tabs.
        self._open_workspace_ids = []
        self._session_save_timer = QTimer(self)
        self._session_save_timer.setSingleShot(True)
        self._session_save_timer.setInterval(250)
        self._session_save_timer.timeout.connect(self._persist_workspace_session)
        self.resize(1440, 860)

        bar = self.addToolBar("Main")
        self.brand_toolbar = bar
        bar.setObjectName("mainToolbar")
        bar.hide()
        bar.setMovable(False)
        bar.setIconSize(QSize(20, 20))

        brand = QLabel("Valhalla")
        brand.setObjectName("brandTitle")
        bar.addWidget(brand)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        bar.addWidget(spacer)

        update_action = QAction("ตรวจสอบอัปเดต", self)
        update_action.triggered.connect(self.check_updates)
        self.menuBar().addMenu("โปรแกรม").addAction(update_action)
        self.navigation = NavigationSidebar(self.settings.navigation_collapsed)
        self.navigation.refresh_icons(self.settings.appearance)
        self.navigation.selected.connect(self.navigate)
        self.navigation.collapsedChanged.connect(self._navigation_collapsed_changed)

        root = QWidget()
        root.setObjectName("appShell")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.main_pages = MainPageStack()
        from .translation_planner_page import TodayPage
        self.today_page = TodayPage(self.repo, self)
        self.today_page.openNovel.connect(self.open_planned_novel)
        self.main_pages.addWidget(self.today_page)
        self.library_page = LibraryPage(self, PROFILE_STATUSES)
        self.main_pages.addWidget(self.library_page)

        self.workspace_stack = QStackedWidget()
        self.empty_page = QLabel("ยังไม่มีนิยาย\nกด + เพื่อเพิ่มนิยาย")
        self.empty_page.setAlignment(Qt.AlignCenter)
        self.empty_page.setObjectName("mutedLabel")
        self.workspace_stack.addWidget(self.empty_page)
        self.main_pages.addWidget(self.workspace_stack)

        self.utility_page = QWidget()
        utility_layout = QVBoxLayout(self.utility_page)
        utility_layout.setContentsMargins(28, 22, 28, 24)
        utility_layout.setSpacing(14)
        utility_header = QHBoxLayout()
        self.utility_back = QPushButton("← กลับ")
        self.utility_back.clicked.connect(self.return_from_utility_page)
        utility_header.addWidget(self.utility_back)
        self.utility_title = QLabel()
        self.utility_title.setObjectName("pageTitle")
        utility_header.addWidget(self.utility_title, 1)
        self.utility_refresh = QPushButton("รีเฟรชรายการ")
        self.utility_refresh.clicked.connect(lambda: self.utility_stack.currentWidget().refresh())
        self.utility_refresh.hide()
        utility_header.addWidget(self.utility_refresh)
        utility_layout.addLayout(utility_header)
        self.utility_stack = QStackedWidget()
        utility_layout.addWidget(self.utility_stack, 1)
        self.main_pages.addWidget(self.utility_page)
        self._utility_pages = {}
        self._active_utility_page = None
        self._utility_return_page = None
        self._settings_page_state = None
        self.shell_splitter = QSplitter(Qt.Horizontal)
        self.shell_splitter.addWidget(self.navigation); self.shell_splitter.addWidget(self.main_pages)
        self.shell_splitter.setStretchFactor(1, 1)
        self.shell_splitter.setChildrenCollapsible(False)
        self.shell_splitter.setSizes([60 if self.navigation.collapsed else 196, 1200])
        root_layout.addWidget(self.shell_splitter, 1)
        self.main_pages.currentChanged.connect(self._sync_navigation)


        self.setCentralWidget(root)

        # Compatibility widgets let the existing management workflows
        # services continue to operate without migrating stored data.
        self.profiles = QListWidget()
        self.profiles.currentRowChanged.connect(self.select_profile)
        self.novel = QLabel()
        self.steps = QListWidget()
        self.files = QListWidget()
        self.files.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.goal_label = QLabel()
        self.goal_bar = QProgressBar()
        self.latest_chapter_label = QLabel()

        self.statusBar().showMessage("เลือกเรื่องเพื่อเริ่มทำงาน")
        self.editor_status = ElidingStatusLabel("พร้อมใช้งาน  ·  0 คำ  ·  0 อักขระ")
        self.editor_status.setObjectName("editorStatusBar")
        self.editor_status.setMinimumWidth(0)
        self.editor_status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.editor_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.statusBar().addPermanentWidget(self.editor_status, 1)
        self.progress_status = ElidingStatusLabel("วันนี้ +0 บท")
        self.progress_status.setObjectName("progressStatusBar")
        self.progress_status.setMinimumWidth(100)
        self.progress_status.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        self.progress_status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.progress_status.hide()
        self.context_status = ElidingStatusLabel("ยังไม่ได้เลือก Context")
        self.context_status.setObjectName("contextStatusBar")
        self.context_status.setMinimumWidth(150)
        self.context_status.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        self.context_status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.context_status.hide()
        self.goal_status = ElidingStatusLabel("ยังไม่ได้ตั้งเป้าหมาย")
        self.goal_status.setObjectName("goalStatusBar")
        self.goal_status.setMinimumWidth(150)
        self.goal_status.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        self.goal_status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.goal_status.hide()
        self.goal_status_bar = QProgressBar()
        self.goal_status_bar.setObjectName("goalProgressStatusBar")
        self.goal_status_bar.setRange(0, 100)
        self.goal_status_bar.setFixedSize(92, 12)
        self.goal_status_bar.setTextVisible(False)
        self.goal_status_bar.hide()
        self.shortcut("Ctrl+Shift+C", self.copy_step)
        self.shortcut("Ctrl+P", self.preview)
        self.shortcut("Ctrl+R", self.refresh)
        self.shortcut("Ctrl+S", self.save_active_document)
        self.shortcut("Ctrl+-", lambda: self.adjust_editor_font_size(-1))
        self.shortcut("Ctrl++", lambda: self.adjust_editor_font_size(1))
        self.shortcut("Ctrl+0", lambda: self.set_editor_font_size(11.0))

        self.progress_timer = QTimer(self)
        self.progress_timer.setInterval(60000)
        self.progress_timer.timeout.connect(self.refresh_translation_progress)
        self.progress_timer.start()

        self.context_watcher = QFileSystemWatcher(self)
        self.context_watcher.fileChanged.connect(self._schedule_context_refresh)
        self.context_watcher.directoryChanged.connect(self._schedule_context_refresh)
        self.context_refresh_timer = QTimer(self)
        self.context_refresh_timer.setSingleShot(True)
        self.context_refresh_timer.setInterval(250)
        self.context_refresh_timer.timeout.connect(self.refresh_translation_progress)
        self._watch_context_paths()

        self._update_check_worker = None
        self._update_download_worker = None
        self._update_progress = None
        self._automatic_update_timer = QTimer(self)
        self._automatic_update_timer.setSingleShot(True)
        self._automatic_update_timer.timeout.connect(lambda: self.check_updates(manual=False))
        if self.settings.last_update_check_date != date.today().isoformat():
            self._automatic_update_timer.start(2500)

    def _navigation_collapsed_changed(self, collapsed):
        self.settings.navigation_collapsed = bool(collapsed)
        self._schedule_workspace_session_save()

    def navigate(self, key):
        if key == "today":
            self.today_page.refresh()
            self.main_pages.setCurrentWidget(self.today_page)
        elif key == "library": self.show_library()
        elif key == "workspace":
            self._utility_return_page = self.workspace_stack
            self.return_from_utility_page()
        elif key == "progress": self.translation_dashboard()
        elif key == "groups": self.groups_dialog()
        elif key == "novel-inspector": self.novel_inspector_dialog()
        elif key == "settings": self.settings_dialog()
        self._sync_navigation()

    def _sync_navigation(self, *_args):
        page = self.main_pages.currentWidget()
        key = "today" if page is self.today_page else ("library" if page is self.library_page else "workspace")
        if page is self.utility_page:
            key = {"progress":"library", "groups":"library", "settings":"settings", "novel-inspector":"novel-inspector"}.get(self._active_utility_page, "workspace")
        self.navigation.select(key)
        # Keep the native window titlebar and menu, without a custom title strip.
        self.brand_toolbar.hide()

    def check_updates(self, checked=False, manual=None):
        manual = True if manual is None else manual
        if self._update_check_worker and self._update_check_worker.isRunning():
            if manual:
                QMessageBox.information(self, "อัปเดต", "กำลังตรวจสอบอัปเดตอยู่ครับ")
            return
        worker = _UpdateCheckWorker(self)
        self._update_check_worker = worker

        def complete(update, error):
            self._update_check_worker = None
            if error:
                if manual:
                    QMessageBox.warning(self, "ตรวจสอบอัปเดตไม่ได้", error)
                return
            self.settings.last_update_check_date = date.today().isoformat()
            self.repo.save_settings(self.settings)
            if update is None:
                if manual:
                    QMessageBox.information(self, "อัปเดต", f"คุณใช้เวอร์ชันล่าสุดแล้ว (v{__version__})")
                return
            self._offer_update(update)

        worker.finished_check.connect(complete)
        worker.start()

    def _offer_update(self, update: UpdateInfo):
        notes = update.notes[:1600] if update.notes else "ไม่มีรายละเอียดการเปลี่ยนแปลง"
        dialog = QMessageBox(self)
        dialog.setWindowTitle("มีอัปเดตใหม่")
        dialog.setText(
            f"เวอร์ชันปัจจุบัน: v{__version__}\n"
            f"เวอร์ชันใหม่: v{update.version}\n\nรายละเอียดการเปลี่ยนแปลง:\n{notes}"
        )
        install = dialog.addButton("อัปเดตเลย", QMessageBox.AcceptRole)
        dialog.addButton("ไว้ทีหลัง", QMessageBox.RejectRole)
        dialog.setDefaultButton(install)
        dialog.exec()
        if dialog.clickedButton() is install:
            destination = Path(tempfile.gettempdir()) / f"NovelWorkflow-Setup-{update.version}.exe"
            self._download_update(update, destination)

    def _download_update(self, update: UpdateInfo, destination: Path):
        dialog = QProgressDialog("กำลังดาวน์โหลดและตรวจสอบตัวติดตั้ง… 0%", "ยกเลิก", 0, 100, self)
        dialog.setObjectName("updateProgressDialog")
        dialog.setWindowTitle(f"อัปเดตเป็น v{update.version}")
        dialog.setWindowModality(Qt.WindowModal)
        dialog.setMinimumDuration(0)
        dialog.setMinimumWidth(460)
        dialog.resize(480, 132)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        progress_bar = dialog.findChild(QProgressBar)
        if progress_bar is not None:
            progress_bar.setObjectName("updateProgressBar")
            progress_bar.setTextVisible(False)
        progress_label = dialog.findChild(QLabel)
        if progress_label is not None:
            progress_label.setObjectName("updateProgressLabel")
            progress_label.setWordWrap(True)
            progress_label.setMinimumHeight(28)
        worker = _UpdateDownloadWorker(update, destination, self)
        self._update_download_worker = worker
        self._update_progress = dialog
        dialog.canceled.connect(worker.requestInterruption)
        worker.progress.connect(self._update_download_progress)

        def complete(path, error):
            self._update_download_worker = None
            self._update_progress = None
            dialog.close()
            dialog.deleteLater()
            if error:
                QMessageBox.warning(self, "ดาวน์โหลดอัปเดตไม่ได้", error)
                return
            try:
                for workspace in self.workspaces.values():
                    if not workspace.editor.save_all(include_normalization=False):
                        raise OSError("บันทึกไฟล์ใน Editor ไม่สำเร็จ")
                self.save()
                self.repo.save_settings(self.settings)
                launch_update(path, update, self.repo.root)
                self.close()
            except (OSError, UpdateError) as exc:
                QMessageBox.warning(self, "เปิดตัวติดตั้งไม่ได้", str(exc))

        worker.finished_download.connect(complete)
        worker.start()

    def _update_download_progress(self, value: int):
        dialog = self._update_progress
        if dialog is None:
            return
        dialog.setValue(value)
        dialog.setLabelText(
            f"กำลังดาวน์โหลดและตรวจสอบตัวติดตั้ง… {value}%"
        )

    def refresh_profiles(self, pid=None):
        if getattr(self, "_settings_open", False):
            result = super().refresh_profiles(pid)
            for index, profile in enumerate(getattr(self, "ps_list", [])):
                item = self.profiles.item(index)
                if item:
                    item.setData(Qt.UserRole, profile.id)
            if self.profile:
                if hasattr(self, "settings_profile_heading"):
                    self.settings_profile_heading.setText(f"ตั้งค่านิยาย · {self.profile.name}")
                self.refresh_working_files()
                self.refresh_settings_launch_targets()
            else:
                if hasattr(self, "settings_profile_heading"):
                    self.settings_profile_heading.setText("เลือกนิยายเพื่อจัดการการตั้งค่า")
                self.refresh_working_files()
                self.settings_launch_targets.clear()
                self.settings_main_folder.clear()
                self.settings_context_hint.setText("ยังไม่ได้เลือกไฟล์ Context")
                self.settings_goal_target.setValue(0)
            return result

        self.ps_list = self.repo.list_profiles()
        for profile in self.ps_list:
            changed = migrate_legacy_basic_workflow(profile.workflow)
            if migrate_legacy_vocabulary_step(profile):
                changed = True
            if profile.id not in self.repo.export_recovery_errors and sync_profile_context(profile):
                changed = True
            if changed:
                self.repo.save_profile(profile)

        known_ids = {profile.id for profile in self.ps_list}
        for profile_id in list(self._workspace_cache):
            if profile_id not in known_ids:
                self._discard_workspace(profile_id)
        for profile_id in list(self.workspaces):
            if profile_id not in known_ids:
                workspace = self.workspaces.pop(profile_id)
                self.workspace_stack.removeWidget(workspace)
                workspace.deleteLater()

        self.profiles.blockSignals(True)
        self.profiles.clear()
        for profile in self.ps_list:
            item = QListWidgetItem(profile.name)
            item.setData(Qt.UserRole, profile.id)
            self.profiles.addItem(item)
        self.profiles.blockSignals(False)

        self._refresh_library_groups()
        self.profile_cards.clear()
        status_counts = {
            status: sum(1 for profile in self.ps_list if _profile_status(profile) == status)
            for status, _label in PROFILE_STATUSES
        }
        for index, (status, label) in enumerate(PROFILE_STATUSES):
            self.library_status_tabs.setTabText(
                index, f"{label} ({status_counts[status]})"
            )
        placeholder = Path(__file__).resolve().parent / "resources" / "novelworkflow.png"
        # Cache scaled covers until image identity changes.
        cache = getattr(self, "_library_cover_cache", {})
        updated_cache = {}
        for profile in self.ps_list:
            candidate = placeholder
            if profile.cover_image_path:
                try:
                    cover = self.repo.resolve_project_path(
                        profile.id, profile.cover_image_path
                    )
                    if cover.is_file():
                        candidate = cover
                except (OSError, ValueError):
                    pass
            try:
                info = candidate.stat()
                signature = (str(candidate), info.st_mtime_ns, info.st_size)
            except OSError:
                signature = (str(candidate), None, None)
            cached = cache.get(profile.id)
            if cached is not None and cached[0] == signature:
                pixmap = cached[1]
            else:
                pixmap = QPixmap(str(candidate))
                if not pixmap.isNull():
                    pixmap = pixmap.scaled(222, 296, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                    pixmap = pixmap.copy((pixmap.width()-222)//2, (pixmap.height()-296)//2, 222, 296)
            updated_cache[profile.id] = (signature, pixmap)
            status = _profile_status(profile)
            card = QListWidgetItem(QIcon(pixmap), profile.name)
            card.setData(Qt.UserRole, profile.id)
            card.setData(Qt.UserRole + 1, status)
            from .translation_planner import TranslationPlanner
            final_goal = TranslationPlanner(self.repo).finish_goal(profile.id) or {}
            last_chapter = final_goal.get("final_chapter")
            done = completed_chapter_count(profile)
            fraction = None
            if type(last_chapter) is int and last_chapter > 0:
                done_within = len({n for n in completed_chapters(profile) if 1 <= n <= last_chapter})
                progress_text = f"แปลสำเร็จ {done_within} / {last_chapter} บท"
                fraction = done_within / last_chapter
            else:
                progress_text = f"แปลสำเร็จ {done} บท"
            footnote = f"{_profile_status_label(status)} · {progress_text}"
            card.setData(Qt.UserRole + 2, footnote)
            card.setData(Qt.UserRole + 3, progress_text)
            card.setData(Qt.UserRole + 4, fraction)
            card.setToolTip(f"{profile.name}\n{footnote}")
            card.setData(Qt.AccessibleDescriptionRole, f"{profile.name}\n{footnote}")
            self.profile_cards.addItem(card)
        self._library_cover_cache = updated_cache

        target_id = pid or (
            self.settings.last_profile_id
            if self.settings.open_last_profile else None
        )
        index = next(
            (i for i, profile in enumerate(self.ps_list) if profile.id == target_id),
            0 if self.ps_list and not self.settings.closed_workspace_profile_ids else -1,
        )
        if index >= 0:
            self.select_profile(index)
        else:
            self.profile = None
            self.si = -1
            self.workspace_stack.setCurrentWidget(self.empty_page)
            self.main_pages.setCurrentWidget(self.library_page)
        self.filter_profiles(self.library_search.text())
        if self.repo.export_recovery_errors:
            self.statusBar().showMessage(' · '.join(self.repo.export_recovery_errors.values()), 15000)

    def _refresh_library_groups(self):
        selector = self.library_group_filter
        selected = selector.currentData()
        selector.blockSignals(True)
        try:
            selector.clear()
            selector.addItem("ทุกกลุ่ม", None)
            self._library_group_ids = {}
            for group in self.repo.load_groups():
                selector.addItem(group.name, group.id)
                self._library_group_ids[group.id] = set(group.profile_ids)
            selector.setCurrentIndex(max(0, selector.findData(selected)))
        finally:
            selector.blockSignals(False)
        if self.profile_cards.count():
            self.filter_profiles(self.library_search.text())

    def filter_profiles(self, query):
        query = query.strip().casefold()
        selected_status = self.library_status_tabs.tabData(
            self.library_status_tabs.currentIndex()
        )
        group_id = self.library_group_filter.currentData()
        group_members = getattr(self, "_library_group_ids", {}).get(group_id, set())
        visible = 0
        for index in range(self.profile_cards.count()):
            item = self.profile_cards.item(index)
            matches = (
                item.data(Qt.UserRole + 1) == selected_status
                and (group_id is None or item.data(Qt.UserRole) in group_members)
                and (not query or query in item.text().casefold())
            )
            item.setHidden(not matches)
            visible += int(matches)
        self.profile_cards.setVisible(visible > 0)
        self.library_section_title.setText(_profile_status_label(selected_status))
        self.library_section_count.setText(f"{visible} เรื่อง")
        if not self.ps_list:
            empty_title = "ยังไม่มีนิยายในคลัง"
            empty_hint = "เพิ่มนิยายเรื่องแรกเพื่อเริ่มจัดการงานแปล"
        elif query or group_id is not None:
            empty_title = "ไม่พบนิยายที่ตรงกับคำค้นหา" if query else "ไม่พบนิยายในกลุ่มนี้"
            empty_hint = "ลองเปลี่ยนคำค้นหาหรือตัวกรอง"
        else:
            empty_title = "ยังไม่มีนิยายในหมวดนี้"
            empty_hint = "เลือกหมวดอื่นหรือเพิ่มนิยายใหม่"
        self.library_empty_label.setText(empty_title)
        self.library_empty_hint.setText(empty_hint)
        self.library_empty_action.setText("ล้างคำค้นหา" if query else "＋ เพิ่มนิยาย")
        self.library_empty_box.setVisible(visible == 0)

    def _open_profile_card(self, item):
        if item is None:
            return
        profile_id = item.data(Qt.UserRole)
        index = next((i for i, profile in enumerate(self.ps_list) if profile.id == profile_id), -1)
        if index >= 0:
            self.select_profile(index)

    def set_profile_status(self, profile_id, status):
        if status not in {value for value, _label in PROFILE_STATUSES}:
            return
        profile = next(
            (item for item in getattr(self, "ps_list", []) if item.id == profile_id),
            None,
        )
        if profile is None:
            return
        if _profile_status(profile) == status:
            return
        old_status = profile.status
        profile.status = status
        try:
            self.repo.save_profile(profile)
        except OSError as exc:
            profile.status = old_status
            QMessageBox.warning(self, "บันทึกสถานะไม่ได้", str(exc))
            return
        self.refresh_profiles(profile_id)
        def undo():
            current = next((item for item in self.repo.list_profiles() if item.id == profile_id), None)
            if current is None or current.status != status: return
            current.status = old_status
            try: self.repo.save_profile(current)
            except OSError as exc:
                QMessageBox.warning(self, "ย้อนกลับไม่ได้", str(exc)); return
            self.refresh_profiles(profile_id)
        self.submit_toast.show_message(f"ย้าย {profile.name} ไป{_profile_status_label(status)}แล้ว", undo)


    def open_planned_novel(self, profile_id):
        index = next((i for i, p in enumerate(self.ps_list) if p.id == profile_id), -1)
        if index >= 0:
            self.select_profile(index)

    def show_library(self):
        if self._settings_page_state:
            self._restore_settings_management()
        self._active_utility_page = None
        self._utility_return_page = None
        if self.profile:
            workspace = self.workspaces.get(self.profile.id)
            if workspace and not workspace.editor.save_all(include_normalization=False):
                self.statusBar().showMessage("บันทึกไม่สำเร็จ จึงยังเปลี่ยนหน้าไม่ได้", 5000)
                return
        self.main_pages.setCurrentWidget(self.library_page)

    def _workspace(self, profile):
        if not self._prepare_workspace_switch(profile.id):
            return None
        closed_ids = list(self.settings.closed_workspace_profile_ids)
        was_closed = profile.id in closed_ids
        if was_closed:
            self.settings.closed_workspace_profile_ids = [pid for pid in closed_ids if pid != profile.id]
        self._open_workspace_ids = [profile.id]
        workspace = self.workspaces.get(profile.id)
        if workspace is None:
            cached = self._workspace_cache.pop(profile.id, None)
            if cached is not None:
                candidate, signature = cached
                if signature == self._workspace_signature(profile.id, candidate):
                    workspace = candidate
                    self.workspaces[profile.id] = workspace
                    self.workspace_stack.addWidget(workspace)
                    workspace.configure(profile)
                else:
                    candidate.deleteLater()
            if workspace is None:
                workspace = WorkspacePage(self, profile)
                workspace.files.itemChanged.connect(
                    lambda item, pid=profile.id: self._file_toggled(pid, item)
                )
                self.workspaces[profile.id] = workspace
                self.workspace_stack.addWidget(workspace)

                workspace.editor.statusChanged.connect(
                    lambda text, editor=workspace.editor:
                        self._workspace_editor_status_changed(editor, text)
                )
                workspace.editor.fontSizeChanged.connect(self.set_editor_font_size)
                workspace.editor.documentSaved.connect(self._document_saved)
                workspace.editor.restore_paths(
                    self.settings.editor_tabs.get(profile.id, []),
                    self.settings.editor_active_tabs.get(profile.id, 0),
                    self.settings.editor_tab_order.get(profile.id),
                    self.settings.editor_active_tab_keys.get(profile.id),
                )
                if profile.open_working_tabs_on_open:
                    self._open_profile_working_tabs(profile, workspace)
                workspace.editor.tabs.currentChanged.connect(self._schedule_workspace_session_save)
                workspace.editor.tabs.tabBar().tabMoved.connect(
                    lambda _from, _to: self._schedule_workspace_session_save()
                )
                workspace.editor.tabs.tabCloseRequested.connect(
                    lambda _index: self._schedule_workspace_session_save()
                )
                workspace.step_index = int(self.settings.workspace_step_indices.get(profile.id, 0))
                workspace.vocabulary_mode = bool(self.settings.workspace_vocabulary_modes.get(profile.id, False))
                workspace.sync_vocabulary_source()
                workspace.set_focus_mode(bool(self.settings.workspace_focus_mode
                                              or not self.settings.sidebar_visible), persist=False)
                positions = self.settings.editor_positions.get(profile.id, {})
                for editor_index in range(workspace.editor.tabs.count()):
                    widget = workspace.editor.tabs.widget(editor_index)
                    editor = widget.editor if hasattr(widget, "editor") else widget
                    document_path = workspace.editor._path(editor)
                    if document_path is None:
                        continue
                    path = str(document_path)
                    position = positions.get(path, {})
                    cursor = editor.textCursor()
                    cursor.setPosition(min(int(position.get("cursor", 0)), len(editor.toPlainText())))
                    editor.setTextCursor(cursor)
                    editor.verticalScrollBar().setValue(int(position.get("scroll", 0)))
        else:
            workspace.configure(profile)
            if was_closed and profile.open_working_tabs_on_open:
                self._open_profile_working_tabs(profile, workspace)
        if not getattr(workspace, "_last_view_restored", False):
            workspace._last_view_restored = True
            view = self.settings.workspace_active_views.get(profile.id, "editor")
            if view == "translation":
                workspace.open_translation_batches()
            elif view == "vocabulary":
                workspace.vocabulary_mode = True
                workspace.set_vocabulary_source("files")
        return workspace

    def _open_profile_working_tabs(self, profile, workspace):
        # Session order is user-owned. Open any newly configured working files,
        # then put the previous session order back ahead of the new additions.
        session_order = [key for key in workspace.editor.tab_order() if key != "txt-export"]
        active_key = workspace.editor.active_tab_key()
        preferred = []
        for item in sorted(profile.working_files, key=lambda value: value.order):
            try:
                path = (Path(item.path).expanduser().resolve()
                        if item.reference_type == "external_file"
                        else self.repo.resolve_project_path(profile.id, item.path))
                if path.is_file() and workspace.editor.open_file(path):
                    preferred.append(str(path.resolve()))
            except (OSError, ValueError, TypeError):
                continue
        ordered_paths = list(dict.fromkeys([*session_order, *preferred]))
        workspace.editor.prioritize_paths(ordered_paths)
        if active_key and active_key in workspace.editor.tab_order():
            workspace.editor.tabs.setCurrentIndex(workspace.editor.tab_order().index(active_key))

    def _workspace_signature(self, profile_id, workspace):
        """Invalidate a warm workspace if its profile or editor files changed outside Valhalla."""
        try:
            paths = [self.repo.profile_dir(profile_id) / "profile.json"]
            paths.extend(Path(path) for path in workspace.editor.open_paths())
            return tuple(
                (str(path.resolve()), path.stat().st_mtime_ns, path.stat().st_size)
                for path in paths
            )
        except (OSError, ValueError):
            return None

    def _suspend_workspace(self, profile_id):
        workspace = self.workspaces.pop(profile_id, None)
        if workspace is None:
            return
        signature = self._workspace_signature(profile_id, workspace)
        for timer in workspace.findChildren(QTimer):
            timer.stop()
        self.workspace_stack.removeWidget(workspace)
        workspace.hide()
        workspace.setParent(self._workspace_cache_host)
        if signature is None:
            workspace.deleteLater()
            return
        self._workspace_cache[profile_id] = (workspace, signature)
        while len(self._workspace_cache) > 2:
            _, (expired, _) = self._workspace_cache.popitem()
            expired.deleteLater()

    def _discard_workspace(self, profile_id):
        """Dispose an already saved workspace without deleting its profile/session."""
        workspace = self.workspaces.pop(profile_id, None)
        cached = self._workspace_cache.pop(profile_id, None)
        if workspace is None and cached is not None:
            workspace = cached[0]
        if workspace is not None:
            for timer in workspace.findChildren(QTimer):
                timer.stop()
            self.workspace_stack.removeWidget(workspace)
            workspace.hide()
            workspace.deleteLater()

    def _prepare_workspace_switch(self, target_id):
        """Guard every workspace entry point, including launches from Settings."""
        previous = [(pid, workspace) for pid, workspace in self.workspaces.items()
                    if pid != target_id]
        if not previous:
            return True
        for pid, workspace in previous:
            pending_path = self._pending_export_for_profile(pid)
            if pending_path is not None:
                profile = next((item for item in self.repo.list_profiles() if item.id == pid), None)
                name = profile.name if profile else "Novel"
                choice = self._export_reminder_choice(
                    "ยังไม่ได้ Export งานแปล!",
                    f"{name}\nTranslator: {pending_path}\n\nTranslator มีเนื้อหาที่เปลี่ยนแปลงหลัง Export ครั้งล่าสุด",
                )
                if choice == "cancel":
                    return False
                if choice == "export" and not self._export_profile_translator(pid):
                    return False
            if not workspace.editor.save_all(include_normalization=False):
                self.statusBar().showMessage("บันทึกไม่สำเร็จ จึงยังเปลี่ยนนิยายไม่ได้", 5000)
                return False
        self._capture_sessions()
        try:
            self.repo.save_settings(self.settings)
        except (OSError, ValueError) as exc:
            self.statusBar().showMessage(f"บันทึกสถานะไม่สำเร็จ จึงยังเปลี่ยนนิยายไม่ได้: {exc}", 6000)
            return False
        for pid, _workspace in previous:
            self._suspend_workspace(pid)
        return True

    def _close_novel_tab(self, profile_id):
        if not profile_id or profile_id not in self._open_workspace_ids:
            return
        workspace = self.workspaces.get(profile_id)
        pending_path = self._pending_export_for_profile(profile_id)
        if pending_path is not None:
            profile = next((item for item in self.repo.list_profiles() if item.id == profile_id), None)
            name = profile.name if profile else "Novel"
            choice = self._export_reminder_choice(
                "ยังไม่ได้ Export งานแปล!",
                f"{name}\nTranslator: {pending_path}\n\nTranslator มีเนื้อหาที่เปลี่ยนแปลงหลัง Export ครั้งล่าสุด",
            )
            if choice == "cancel":
                return
            if choice == "export" and not self._export_profile_translator(profile_id):
                return
        if workspace and not workspace.editor.save_all(include_normalization=False):
            self.statusBar().showMessage("บันทึกไม่สำเร็จ จึงยังปิดแท็บนิยายไม่ได้", 5000)
            return
        self._capture_sessions()
        self._open_workspace_ids = []
        if profile_id not in self.settings.closed_workspace_profile_ids:
            self.settings.closed_workspace_profile_ids.append(profile_id)
        if self.profile and self.profile.id == profile_id:
            self.profile = None
            self.si = -1
            self.settings.last_profile_id = None
            self.workspace_stack.setCurrentWidget(self.empty_page)
            self.main_pages.setCurrentWidget(self.library_page)
        self._discard_workspace(profile_id)
        self._persist_workspace_session()

    def select_profile(self, index):
        if getattr(self, "_settings_open", False):
            result = super().select_profile(index)
            if self.profile:
                self.settings_profile_heading.setText(f"ตั้งค่านิยาย · {self.profile.name}")
                self.refresh_working_files()
                self.refresh_settings_launch_targets()
                if hasattr(self, "auto_open_working_tabs"):
                    self.auto_open_working_tabs.blockSignals(True)
                    self.auto_open_working_tabs.setChecked(self.profile.open_working_tabs_on_open)
                    self.auto_open_working_tabs.blockSignals(False)
            return result
        if index < 0 or index >= len(getattr(self, "ps_list", [])):
            return

        target = self.ps_list[index]
        if not self._prepare_workspace_switch(target.id):
            # Settings may have selected another profile while the old editor
            # remained open. Restore that editor's binding when switching fails.
            active_id = getattr(self.workspace_stack.currentWidget(), 'profile_id', None)
            active = next((p for p in self.ps_list if p.id == active_id), None)
            if active is not None:
                self.profile = active
                self.settings.last_profile_id = active.id
            return
        self.profile = self.ps_list[index]
        self.settings.last_profile_id = self.profile.id
        workspace = self._workspace(self.profile)
        workspace.update_profile_status(_profile_status(self.profile))

        self.steps = workspace.steps
        self.files = workspace.files
        self.goal_label = workspace.goal_label
        self.goal_bar = workspace.goal_bar
        self.latest_chapter_label = workspace.latest_chapter_label

        if self.profile.workflow.steps:
            self.si = max(
                0,
                min(workspace.step_index, len(self.profile.workflow.steps) - 1),
            )
        else:
            self.si = -1

        self.profiles.blockSignals(True)
        self.profiles.setCurrentRow(index)
        self.profiles.blockSignals(False)

        self.workspace_stack.setCurrentWidget(workspace)
        self.main_pages.setCurrentWidget(self.workspace_stack)
        workspace.copy_step_button.setEnabled(
            bool(self.profile.workflow.steps or self.profile.vocabulary_step)
        )
        self._update_context_button(workspace)
        workspace.refresh_context_update_button()
        self.refresh_steps()
        if self.si >= 0:
            self.steps.setCurrentRow(self.si)
        self.refresh_goal_indicator()
        self.statusBar().showMessage(f"กำลังทำงาน: {self.profile.name}", 2500)
        self._update_editor_status()
        self._schedule_workspace_session_save()

    def _schedule_workspace_session_save(self, *_args):
        timer = getattr(self, "_session_save_timer", None)
        if timer is not None:
            timer.start()

    def _persist_workspace_session(self):
        """Persist tab/session changes promptly so a later crash loses little state."""
        if not hasattr(self, "workspaces"):
            return
        try:
            self._capture_sessions()
            self.repo.save_settings(self.settings)
        except (OSError, ValueError) as exc:
            if hasattr(self, "statusBar"):
                self.statusBar().showMessage(f"บันทึกสถานะหน้าทำงานไม่ได้: {exc}", 6000)

    def refresh_steps(self):
        if getattr(self, "_settings_open", False):
            result = super().refresh_steps()
            if self.profile and self.profile.vocabulary_step:
                vocabulary = QListWidgetItem(self.profile.vocabulary_step.name)
                vocabulary.setData(Qt.UserRole, "vocabulary-step")
                vocabulary.setToolTip(
                    "ดับเบิลคลิกเพื่อไปเพิ่มหรือจัดการไฟล์หาศัพท์"
                )
                vocabulary.setSizeHint(QSize(0, 42))
                self.steps.addItem(vocabulary)
            if hasattr(self, "settings_step_hint"):
                active_step = self.step()
                self.settings_step_hint.setText(
                    f"{active_step.name} · {len(active_step.files)} ไฟล์"
                    if active_step else "เลือกขั้นตอนเพื่อจัดการไฟล์"
                )
            return result

        workspace = (
            self.workspaces.get(self.profile.id) if self.profile else None
        )
        desired = workspace.step_index if workspace else 0
        self.steps.blockSignals(True)
        self.steps.clear()
        if workspace:
            workspace.step_selector.blockSignals(True)
            workspace.step_selector.clear()

        if self.profile:
            for step in self.profile.workflow.steps:
                # The legacy list is an internal adapter, never a visible button.
                self.steps.addItem(QListWidgetItem(step.name))
                if workspace:
                    workspace.step_selector.addItem(step.name, step.id)
            if workspace and self.profile.vocabulary_step is not None:
                vocabulary = self.profile.vocabulary_step
                workspace.step_selector.addItem(vocabulary.name, vocabulary.id)

        self.steps.blockSignals(False)
        if self.profile and self.profile.workflow.steps:
            self.si = max(0, min(desired, len(self.profile.workflow.steps) - 1))
            self.steps.setCurrentRow(self.si)
        else:
            self.si = -1
        if workspace:
            workspace.step_index = self.si
            workspace.vocabulary_mode = bool(
                workspace.vocabulary_mode and self.profile and self.profile.vocabulary_step
            )
            workspace.copy_step_button.setEnabled(
                bool(self.profile and (self.profile.workflow.steps or self.profile.vocabulary_step))
            )
            workspace.step_selector.blockSignals(False)
            self._sync_stage_buttons(workspace)
        self.refresh_files()

    def _sidebar_step_selected(self, profile_id):
        """Dropdown changes the stage, never the clipboard or tool page."""
        if not self.profile or self.profile.id != profile_id:
            return
        workspace = self.workspaces.get(profile_id)
        if workspace is None:
            return
        step_id = workspace.step_selector.currentData()
        vocabulary = self.profile.vocabulary_step
        if vocabulary is not None and step_id == vocabulary.id:
            self.set_vocabulary_mode(profile_id, True)
        else:
            row = next(
                (index for index, step in enumerate(self.profile.workflow.steps)
                 if step.id == step_id), -1
            )
            if row >= 0:
                self._step_changed(profile_id, row)
        self._sync_stage_buttons(workspace)

    def _workspace_step_menu(self, profile_id, position):
        """Accessible right-click menu for the current stage and ZIP selection."""
        if not self.profile or self.profile.id != profile_id:
            return
        workspace = self.workspaces.get(profile_id)
        if workspace is None or self.step() is None:
            return
        menu = QMenu(workspace.step_selector)
        copy_one = menu.addAction("คัดลอกขั้นตอนนี้")
        copy_multiple = menu.addAction("เลือกหลายขั้นตอนแล้วคัดลอกเป็น ZIP…")
        copy_multiple.setEnabled(self.settings.copy_files_as_zip)
        chosen = menu.exec(workspace.step_selector.mapToGlobal(position))
        if chosen == copy_one:
            stage = "vocabulary" if workspace.vocabulary_mode else workspace.step_index
            self.copy_named_stage(profile_id, stage)
        elif chosen == copy_multiple:
            self._workflow_copy_menu(workspace.step_selector, position, direct=True)

    def refresh_files(self):
        super().refresh_files()
        workspace = self.workspaces.get(self.profile.id) if self.profile else None
        if workspace:
            workspace.filter_files(workspace.file_search.text())

    def _step_changed(self, profile_id, row):
        if (not self.profile or self.profile.id != profile_id
                or not 0 <= row < len(self.profile.workflow.steps)):
            return
        workspace = self.workspaces.get(profile_id)
        if workspace:
            if not workspace.editor.save_all(include_normalization=False):
                self.statusBar().showMessage("บันทึกไม่สำเร็จ จึงยังเปลี่ยนขั้นตอนไม่ได้", 5000)
                workspace.steps.blockSignals(True)
                workspace.steps.setCurrentRow(workspace.step_index)
                workspace.steps.blockSignals(False)
                self._sync_stage_buttons(workspace)
                return
            workspace.vocabulary_mode = False
            workspace.step_index = row
            self.settings.workspace_step_indices[profile_id] = row
        self.si = row
        self.refresh_files()
        if workspace:
            self._sync_stage_buttons(workspace)
            self._schedule_workspace_session_save()

    @staticmethod
    def _sync_stage_buttons(workspace):
        """Synchronize the visible selector from one active stage state."""
        profile = workspace.owner.profile
        workspace.history_range.setVisible(bool(profile and profile.polish_history_step_id))
        active_id = None
        if profile:
            if workspace.vocabulary_mode and profile.vocabulary_step:
                active_id = profile.vocabulary_step.id
            elif 0 <= workspace.step_index < len(profile.workflow.steps):
                active_id = profile.workflow.steps[workspace.step_index].id
        selector = workspace.step_selector
        selector.blockSignals(True)
        selector.setCurrentIndex(selector.findData(active_id))
        selector.blockSignals(False)
        workspace.sync_vocabulary_source()

    def _workflow_copy_menu(self, button, position, *, direct=False):
        if not self.profile or not self.settings.copy_files_as_zip:
            return
        if not direct:
            menu = QMenu(button)
            choose = menu.addAction("เลือกหลายขั้นตอนแล้วคัดลอกเป็น ZIP…")
            if menu.exec(button.mapToGlobal(position)) != choose:
                return
        dialog = QDialog(self)
        dialog.setWindowTitle("เลือกขั้นตอนสำหรับ ZIP")
        layout = QVBoxLayout(dialog)
        choices = []
        steps = ([self.profile.vocabulary_step] if self.profile.vocabulary_step else []) + self.profile.workflow.steps
        for step in steps:
            check = QCheckBox(step.name)
            check.setChecked(step is self.step())
            layout.addWidget(check)
            choices.append((check, step))
        copy = QPushButton("COPY STEP")
        copy.clicked.connect(dialog.accept)
        layout.addWidget(copy)
        if dialog.exec() == QDialog.Accepted:
            selected = [step for check, step in choices if check.isChecked()]
            if selected:
                self.copy_step(advance=False, selected_steps=selected)

    def copy_named_stage(self, profile_id, stage):
        """Select and copy one stage immediately, without export, history, or advancing."""
        if not self.profile or self.profile.id != profile_id:
            return
        workspace = self.workspaces.get(profile_id)
        if not workspace:
            self.statusBar().showMessage("บันทึกไม่สำเร็จ จึงคัดลอกไฟล์ไม่ได้", 5000)
            return
        if stage == "vocabulary":
            workspace.vocabulary_mode = True
            self.si = workspace.step_index
        else:
            row = int(stage)
            if not 0 <= row < len(self.profile.workflow.steps):
                return
            workspace.vocabulary_mode = False
            workspace.step_index = row
            self.si = row
            self.settings.workspace_step_indices[profile_id] = row
            self.steps.blockSignals(True)
            self.steps.setCurrentRow(row)
            self.steps.blockSignals(False)
        self._sync_stage_buttons(workspace)
        self.refresh_files()
        self._schedule_workspace_session_save()
        self.copy_step(advance=False)

    def save_translation_batch_state(self, profile_id, state):
        saved = dict(state)
        saved.pop("draft", None)
        self.settings.translation_batch_profiles[profile_id] = saved
        self._schedule_workspace_session_save()

    def open_translation_batches(self, profile_id):
        if not self.profile or self.profile.id != profile_id:
            return
        workspace = self.workspaces.get(profile_id)
        if workspace is None:
            return
        # Opening the batch page is navigation, NOT a COPY STEP action.
        # Keep the sidebar in sync without triggering copy_named_stage().
        translation_indices = [
            index for index, step in enumerate(self.profile.workflow.steps)
            if step.name.strip() == "แปล"
        ]
        if len(translation_indices) == 1:
            index = translation_indices[0]
            workspace.vocabulary_mode = False
            workspace.step_index = index
            self.si = index
            self.settings.workspace_step_indices[profile_id] = index
            workspace.steps.blockSignals(True)
            workspace.steps.setCurrentRow(index)
            workspace.steps.blockSignals(False)
            self._sync_stage_buttons(workspace)
            self.refresh_files()
            workspace.copy_step_button.setEnabled(bool(self.step()))
            self._schedule_workspace_session_save()
        workspace.open_translation_batches()

    def save_txt_vocabulary_state(self, profile_id, state):
        saved = dict(state)
        saved.pop("draft", None)
        previous = self.settings.vocabulary_txt_profiles.get(profile_id, {})
        self.settings.vocabulary_txt_profiles[profile_id] = saved
        if saved.get("split_completed_at") != previous.get("split_completed_at"):
            # A successful chapter split is an explicit disk operation; persist
            # its result and tab selection immediately rather than relying on
            # the debounced session timer or a clean application shutdown.
            self._persist_workspace_session()
        else:
            self._schedule_workspace_session_save()

    def open_txt_vocabulary(self, profile_id):
        if not self.profile or self.profile.id != profile_id:
            return
        self.set_vocabulary_mode(profile_id, True)
        workspace = self.workspaces.get(profile_id)
        if workspace and workspace.vocabulary_mode:
            workspace.set_vocabulary_source("files")
            if workspace.txt_vocabulary_page is not None:
                workspace.editor_content_stack.setCurrentWidget(workspace.txt_vocabulary_page)

    def step(self):
        """Return the currently active vocabulary or translation step."""
        if self.profile:
            if getattr(self, "_settings_open", False):
                selected = self.steps.currentItem() if self.steps else None
                is_vocabulary_row = bool(
                    selected and selected.data(Qt.UserRole) == "vocabulary-step"
                )
                if getattr(self, "_management_vocabulary_mode", False) or is_vocabulary_row:
                    return self.profile.vocabulary_step
            else:
                workspace = self.workspaces.get(self.profile.id)
                if workspace and workspace.vocabulary_mode:
                    return self.profile.vocabulary_step
        return super().step()

    def set_vocabulary_mode(self, profile_id, enabled):
        workspace = self.workspaces.get(profile_id)
        if not workspace or not self.profile or self.profile.id != profile_id:
            return
        if enabled and self.profile.vocabulary_step is None:
            return
        if not workspace.editor.save_all(include_normalization=False):
            self._sync_stage_buttons(workspace)
            self.statusBar().showMessage("บันทึกไม่สำเร็จ จึงยังเปลี่ยนขั้นตอนไม่ได้", 5000)
            return
        workspace.vocabulary_mode = enabled
        self._schedule_workspace_session_save()
        self.si = workspace.step_index
        self.refresh_files()
        self._sync_stage_buttons(workspace)
        workspace.copy_step_button.setEnabled(bool(self.step()))
        stage = "หาศัพท์" if enabled else self.profile.workflow.steps[self.si].name if self.si >= 0 else ""
        self.statusBar().showMessage(f"ขั้นตอน: {stage}", 2500)

    def _file_toggled(self, profile_id, item):
        if self.profile and self.profile.id == profile_id:
            super().toggle_file(item)

    def select_step(self, index):
        if getattr(self, "_settings_open", False):
            selected = self.steps.currentItem() if self.steps else None
            row_type = selected.data(Qt.UserRole) if selected else None
            is_vocabulary_row = row_type == "vocabulary-step"
            self._management_vocabulary_mode = is_vocabulary_row
            if is_vocabulary_row:
                self.refresh_files()
                if hasattr(self, "settings_step_hint"):
                    active_step = self.step()
                    self.settings_step_hint.setText(f"{active_step.name} · ไฟล์ที่ใช้กับขั้นตอนนี้")
                return
            result = super().select_step(index)
            if hasattr(self, "settings_step_hint"):
                active_step = self.step()
                self.settings_step_hint.setText(
                    f"{active_step.name} · {len(active_step.files)} ไฟล์"
                    if active_step else "เลือกขั้นตอนเพื่อจัดการไฟล์"
                )
            return result
        if self.profile:
            self._step_changed(self.profile.id, index)

    def save_active_document(self):
        if not self.profile:
            return
        workspace = self.workspaces.get(self.profile.id)
        if workspace and workspace.editor.save_current():
            self.statusBar().showMessage("บันทึกไฟล์แล้ว", 2000)

    def open_workflow_file(self, profile_id, item):
        profile = next((value for value in self.ps_list if value.id == profile_id), None)
        workspace = self.workspaces.get(profile_id)
        if not profile or not workspace:
            return
        step = profile.vocabulary_step if workspace.vocabulary_mode else (
            profile.workflow.steps[workspace.step_index]
            if 0 <= workspace.step_index < len(profile.workflow.steps) else None
        )
        if not step:
            return
        step_file = next((value for value in step.files if value.id == item.data(Qt.UserRole)), None)
        if not step_file:
            return
        try:
            if step_file.reference_type == "dynamic":
                path = self.assembler.resolve(profile, step_file.dynamic_reference)
            elif step_file.reference_type == "external_file":
                path = Path(step_file.path).expanduser().resolve()
            else:
                path = self.repo.resolve_project_path(profile.id, step_file.path)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            QMessageBox.warning(self, "เปิดไฟล์ไม่ได้", str(exc))
            return
        if workspace.editor.open_file(path):
            workspace.breadcrumb.setText(f"{profile.name}  ›  {step.name}  ›  {path.name}")



    def _ensure_chapter_numbers_for_copy(self, workspace, profile, steps, *, zipped):
        """Synchronously finalize eligible source files before freezing the clipboard."""
        if (not workspace or not profile.auto_review_enabled
                or profile.auto_chapter_number_mode != "fix"):
            return
        from .polish_history import _files
        from .workflow_archive import resolve_attachment
        attached = set()
        for step in steps:
            for item in step.files:
                if not zipped and not item.enabled:
                    continue
                attached.update(_files(resolve_attachment(self.repo, self.assembler, profile, item)))

        pending = getattr(workspace, "auto_chapter_review_paths", set())
        blocked = getattr(workspace, "auto_chapter_review_failed_paths", set())
        candidates = {path for path in set(pending) | set(blocked)
                      if self._auto_original_source_eligible(profile, workspace, path)}
        editors = {}
        for index in range(workspace.editor.tabs.count()):
            editor = workspace.editor.tabs.widget(index)
            path = workspace.editor._path(editor)
            if path is None:
                continue
            path = Path(path).expanduser().resolve()
            editors[path] = editor
            needs_review = workspace.editor._dirty(editor) or path in pending or path in blocked
            if needs_review and self._auto_original_source_eligible(profile, workspace, path):
                candidates.add(path)
            elif (path in attached and workspace._source_file_eligible(path)
                    and not is_auxiliary_document(path)
                    and path.name.casefold() != "novel.txt"
                    and scan_original_chapter_issues(editor.toPlainText())[0]
                    and not self._auto_original_source_eligible(profile, workspace, path)):
                raise ValueError(
                    f"{path.name}: ไม่พบ Translator ที่จับคู่ได้แน่ชัด "
                    "จึงไม่คัดลอกต้นฉบับที่ยังตรวจเลขบทไม่ได้"
                )
        for path in sorted(candidates):
            editor = editors.get(path)
            if editor is None:
                raise ValueError(f"{path.name}: ปิดแท็บต้นฉบับก่อนตรวจเลขบทเสร็จ")
            if workspace.editor._dirty(editor) and not workspace.editor.save_editor(
                    editor, quiet=True, normalize=False):
                raise ValueError(f"{path.name}: บันทึกต้นฉบับไม่สำเร็จ")
            self.statusBar().showMessage(f"กำลังตรวจเลขบท {path.name} ก่อนคัดลอก…")
            if not self._run_auto_chapter_review(profile.id, path=path, for_copy=True):
                raise ValueError(
                    f"{path.name}: ยังตรวจหรือแก้เลขบทอัตโนมัติไม่สำเร็จ "
                    "กรุณาตรวจเลขบทในแท็บต้นฉบับก่อนคัดลอก"
                )
            pending.discard(path)
            blocked.discard(path)
        timer = getattr(workspace, "auto_chapter_review_timer", None)
        if timer is not None and not pending:
            timer.stop()

    def copy_step(self, advance=False, selected_steps=None):
        """Copy current stage files only; history snapshots require an explicit action.

        Keep source chapter validation and unsaved-editor preparation in place,
        but never create a review snapshot or advance the selected stage here.
        """
        if not self.profile or not self.step():
            return
        if self.history_busy():
            self.statusBar().showMessage('กำลังจัดการไฟล์ กรุณารอสักครู่', 3000)
            return
        from copy import deepcopy
        from .clipboard_bundle import prepare_bundle
        from .workflow_archive import create_workflow_archive
        workspace = self.workspaces.get(self.profile.id)
        profile = deepcopy(self.profile)
        selected = deepcopy(selected_steps or [self.step()])
        zipped = self.settings.copy_files_as_zip
        try:
            # Qt/editor access stays on the GUI thread; clipboard is touched
            # only after all input files have been validated and prepared.
            self._ensure_chapter_numbers_for_copy(workspace, profile, selected, zipped=zipped)
            bundle = prepare_bundle(
                self.repo, self.assembler, profile, selected,
                workspace.editor if workspace else None, all_files=zipped,
            )
            if zipped:
                paths = [create_workflow_archive(
                    self.repo, self.assembler, profile, selected, prepared=bundle,
                )]
                import zipfile
                with zipfile.ZipFile(paths[0]) as archive:
                    count = sum(not item.is_dir() for item in archive.infolist())
            else:
                paths = list(bundle.values())
                count = len(paths)
            self._history_clipboard(paths, count, zipped)
        except (OSError, ValueError, KeyError) as exc:
            # Failed preparation must leave the previous clipboard untouched.
            QMessageBox.warning(self, 'คัดลอกไฟล์ไม่สำเร็จ', str(exc))
            self.statusBar().showMessage('คัดลอกไฟล์ไม่สำเร็จ: ' + str(exc), 6000)
            return

    def set_editor_font_size(self, size):
        size = max(8.0, min(28.0, float(size)))
        self.settings.editor_font_size = size
        for workspace in self.workspaces.values():
            if workspace.editor.font_size() != size:
                workspace.editor.set_font_size(size)
            workspace.font_size_label.setText(f"{size:g}")
        self.repo.save_settings(self.settings)

    def adjust_editor_font_size(self, delta):
        size = self.settings.editor_font_size + float(delta)
        self.set_editor_font_size(size)

    def _chapter_review_status(self, profile, path):
        """Return persisted manual review state and compare its exact source bytes."""
        key = str(Path(path).expanduser().resolve())
        records = getattr(profile, 'chapter_review_state', {})
        record = records.get(key) if isinstance(records, dict) else None
        if not isinstance(record, dict):
            return None
        if record.get('profile_id') != profile.id or record.get('source_file_path') != key:
            return {**record, 'current': False}
        try:
            digest = hashlib.sha256(Path(key).read_bytes()).hexdigest()
        except OSError:
            return {**record, 'current': False}
        return {**record, 'current': digest == record.get('source_fingerprint')}

    def _document_saved(self, saved_path):
        for workspace in self.workspaces.values():
            workspace.refresh_history()
        self.refresh_translation_progress()
        if not self.profile:
            return
        workspace = self.workspaces.get(self.profile.id)
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
                if not isinstance(value, dict):
                    raise ValueError("รูปแบบ export_status.json ไม่ใช่ Object")
                self._export_status_cache[profile_id] = value
                self._export_status_errors.pop(profile_id, None)
            except (OSError, ValueError, TypeError) as exc:
                self._export_status_cache[profile_id] = {}
                self._export_status_errors[profile_id] = str(exc)
        return self._export_status_cache[profile_id]

    def _save_export_records(self, profile_id):
        if profile_id in self._export_status_errors:
            raise ValueError("อ่านประวัติ Export เดิมไม่ได้ จึงไม่เขียนทับไฟล์เดิม")
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
        if profile_id in self.repo.export_recovery_errors:
            return
        self._export_records(profile_id)
        if profile_id in self._export_status_errors:
            return
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
        if profile_id in self.repo.export_recovery_errors:
            self._export_status_errors[profile_id] = str(self.repo.export_recovery_errors[profile_id])
            return 'error'
        key = self._export_path_key(path)
        record = self._export_records(profile_id).get(key)
        if profile_id in self._export_status_errors:
            return 'error'
        if not record:
            if editor is not None and EditorTabs._dirty(editor) and not editor.property('normalizationPending'):
                self._mark_export_pending(profile_id, path)
                return "not_exported"
            return "unknown"
        try:
            from .workflow_archive import file_digest
            digest = file_digest(path)
        except OSError:
            self._export_status_errors[profile_id] = f"อ่านไฟล์ Translator ไม่ได้: {path}"
            return "error"
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
                    'exported_txt_path': str(target), 'pending': False,
                    'event_id': event['event_id'], 'chapter_range': event['chapter_range'],
                    'context_updated': True, 'status': 'committed'}
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
                self._export_status_errors.pop(profile_id, None)
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
            if workspace is self.workspace_stack.currentWidget():
                self.settings.workspace_focus_mode = workspace._focus_mode
                self.settings.sidebar_visible = not workspace._focus_mode
                if not workspace._focus_mode:
                    sidebar_size = workspace.workspace_splitter.sizes()[0]
                    if sidebar_size >= 180:
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
        if (self._pending_export_snapshots
                and not any(worker and worker.isRunning() for worker in workers)):
            self.statusBar().showMessage('กำลังบันทึกประวัติ Export ที่รออยู่ก่อนปิดโปรแกรม…')
            QTimer.singleShot(0, self._drain_export_snapshot_queue)
            event.ignore()
            return
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
            try:
                if workspace.txt_vocabulary_page is not None:
                    workspace.txt_vocabulary_page.flush_draft()
                if workspace.translation_batch_page is not None:
                    workspace.translation_batch_page.flush_draft()
            except (OSError, ValueError, TypeError) as exc:
                QMessageBox.warning(self, "บันทึกร่างไม่สำเร็จ", f"ยังปิดโปรแกรมไม่ได้ เพราะบันทึกร่างไม่สำเร็จ:\n{exc}")
                event.ignore()
                return
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
