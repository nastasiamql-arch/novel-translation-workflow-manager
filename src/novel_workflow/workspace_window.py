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
     