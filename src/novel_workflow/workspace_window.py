from __future__ import annotations

import shutil
import tempfile
import hashlib
import os
from datetime import date, datetime
from pathlib import Path
import subprocess

from PySide6.QtCore import QDir, QFileSystemWatcher, QSize, Qt, QTimer, Signal, QThread
from PySide6.QtGui import QAction, QFontMetrics, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QDialog, QFileDialog, QFileSystemModel, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QProgressBar, QPushButton, QSizePolicy, QSplitter, QStackedWidget,
    QTabBar, QToolButton, QTreeView, QVBoxLayout, QWidget, QInputDialog, QComboBox, QTextEdit,
    QCheckBox, QProgressDialog, QScrollArea, QSpinBox, QMenu, QMainWindow,
)

from .models import LaunchTarget, StepFile, migrate_legacy_basic_workflow, migrate_legacy_vocabulary_step
from .translation_progress import (
    daily_chapter_count, goal_progress, latest_context_chapter,
    sync_profile_context, read_context_chapter,
)
from .ui import ManagementActionsMixin
from .shell_components import NovelHeader, NavigationSidebar, ElidingLabel, EditorToolbar, MainPageStack
from .library_page import LibraryPage
from .profile_list import ReorderableProfileList
from .settings_page import SettingsPage
from .export_service import ExportService, daily_export_count, verified_goal_text
from .workspace_editor import EditorTabs, _stage_text_file, _cleanup_staged_text_file
from .recovery import commit_staged
from .theme import theme_colors
from . import __version__
from .update_bootstrap import launch_update, read_update_result
from .updater import UpdateError, UpdateInfo, check_for_update, download_update
from .file_import import import_files_into_directory


PROFILE_STATUSES = (
    ("translating", "กำลังแปล"),
    ("paused", "พักแปล"),
    ("caught_up", "ชนต้นฉบับแล้ว"),
    ("checking_web", "กำลังเช็กกับเว็บ"),
)


def _stage_bytes_file(destination: Path, data: bytes) -> Path:
    """Stage exact document bytes beside their destination for atomic replacement."""
    staging_dir = Path(tempfile.mkdtemp(dir=destination.parent, prefix=".palantir-staging-"))
    staged = staging_dir / f"{destination.name}.part"
    try:
        with staged.open("xb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        return staged
    except OSError:
        _cleanup_staged_text_file(staged, staging_dir)
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
        self.vocabulary_button.setToolTip("คัดลอกไฟล์ของขั้นตอนหาศัพท์ไปยังคลิปบอร์ด")
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
        self.copy_step_button = QPushButton("COPY STEP")
        self.copy_step_button.setObjectName("copyStepButton")
        self.copy_step_button.setToolTip("คัดลอกไฟล์ของขั้นตอนที่เลือก  ·  Ctrl+Shift+C")
        self.copy_step_button.clicked.connect(
            lambda checked=False: self.owner.copy_step()
        )
        step_header.addWidget(self.copy_step_button)
        sidebar_layout.addLayout(step_header)
        sidebar_layout.addWidget(self.vocabulary_button)
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
        self.update_context_button.setToolTip("Export Translator to TXT and update Context")
        self.update_context_button.setAccessibleName("Export Translator to TXT and update Context")
        self.update_context_button.clicked.connect(
            lambda: self.owner.update_context_from_translator(self)
        )
        self.update_context_button.hide()
        header_layout.addWidget(self.update_context_button)
        web_source = QToolButton()
        web_source.setText("ต้นฉบับเว็บ")
        web_source.clicked.connect(self.owner.open_downloader)
        header_layout.addWidget(web_source)
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
        self.more_menu.addAction("เปิดรายการของเรื่อง", self.owner.launch_profile)
        self.more_menu.addAction("History / กู้ไฟล์", self.show_recovery)
        more = QToolButton(); more.setText("..."); more.setAccessibleName("คำสั่งเพิ่มเติม")
        more.setMenu(self.more_menu); more.setPopupMode(QToolButton.InstantPopup)
        header_layout.addWidget(more)
        self.undo_button = QToolButton(); self.undo_button.setText("Undo"); self.undo_button.setToolTip("Undo · Ctrl+Z"); self.undo_button.setAccessibleName("Undo")
        self.redo_button = QToolButton(); self.redo_button.setText("Redo"); self.redo_button.setToolTip("Redo · Ctrl+Y / Ctrl+Shift+Z"); self.redo_button.setAccessibleName("Redo")
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
        self.novel_header.close_button.clicked.connect(
            lambda: self.owner._close_novel_tab(self.profile_id))
        editor_layout.addWidget(self.novel_header)
        editor_layout.addWidget(self.editor_header)
        editor_layout.addWidget(self.editor, 1)
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
        layout.addWidget(self.content_stack, 1)

        self.configure(profile)
        self.set_mode(0)

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

    def refresh_context_update_button(self):
        editor = self.editor._current_editor()
        path = self.editor._path(editor) if editor else None
        allowed = bool(
            path is not None
            and self.owner.profile is not None
            and self.owner.profile.id == self.profile_id
            and self.owner._translator_profile_for_path(self.profile_id, path)
        )
        self.update_context_button.setVisible(allowed)

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
        super().__init__(repo)
        self.setWindowTitle("Palantir: Novel")
        self.submit_toast = SubmitToast(self)
        result = read_update_result(self.repo.root)
        if result:
            if result.get("success") and result.get("version") == __version__:
                QTimer.singleShot(100, lambda: self.show_submit_toast(f"อัปเดตเป็น v{__version__} สำเร็จ ✓"))
            else:
                message = result.get("error") or f"เปิดโปรแกรม v{__version__} แต่คาดว่าจะเป็น v{result.get('version', 'unknown')}"
                QTimer.singleShot(100, lambda: QMessageBox.warning(self, "อัปเดตไม่สำเร็จ", f"{message}\nLog: {result.get('log', '')}"))
        logo = Path(__file__).resolve().parent / "resources" / "palantir_novel.png"
        if logo.is_file():
            self.setWindowIcon(QIcon(str(logo)))
        # Mark historical cosmetic migrations without changing saved preferences.
        changed = not all((self.settings.appearance_migrated, self.settings.flat_vscode_theme_migrated, self.settings.editor_style_migrated))
        self.settings.appearance_migrated = True
        self.settings.flat_vscode_theme_migrated = True
        self.settings.editor_style_migrated = True
        if changed: self.repo.save_settings(self.settings)

    def apply_theme(self):
        super().apply_theme()
        if hasattr(self, "navigation"):
            self.navigation.refresh_icons(self.settings.appearance)
        for workspace in getattr(self, "workspaces", {}).values():
            workspace.editor.set_appearance(self.settings.appearance)

    def show_submit_toast(self, message):
        self.submit_toast.show_message(message)

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
            page.set_profiles(self.refresh_translation_progress())
        elif key in {"groups", "launcher", "file-manager", "preview"}:
            self.utility_stack.removeWidget(page)
            page.deleteLater()
            page = factory()
            self._utility_pages[key] = page
            self.utility_stack.addWidget(page)
        self.utility_title.setText(title)
        self.utility_back.setText("← กลับไปทำงาน" if self.profile else "← คลังนิยาย")
        self.utility_stack.setCurrentWidget(page)
        self._active_utility_page = key
        self.main_pages.setCurrentWidget(self.utility_page)

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

    def open_downloader(self):
        if not self.profile:
            return
        from .downloader_ui.panel import DownloaderPage
        key = f"downloader:{self.profile.id}"
        self._show_utility_page(key, "ต้นฉบับเว็บ", lambda: DownloaderPage(self))

    def translation_dashboard(self):
        profiles = self.refresh_translation_progress()

        def create_dashboard():
            from .progress_dialog import TranslationDashboardDialog
            return TranslationDashboardDialog(self, profiles, self.repo, self.refresh_translation_progress)

        self._show_utility_page("progress", "ความคืบหน้าการแปล", create_dashboard)

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

    def save_settings_goal_target(self):
        if not self.profile:
            return
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

    def refresh_settings_launch_targets(self):
        if not hasattr(self, "settings_launch_targets") or not self.profile:
            return
        self.settings_main_folder.setText(self.profile.main_folder)
        context = Path(self.profile.context_path).expanduser() if self.profile.context_path else None
        self.settings_context_hint.setText(
            f"Context: {context.name}" if context and context.is_file()
            else "ยังไม่ได้เลือกไฟล์ Context"
        )
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
            self.settings_main_folder.setText(selected)
            self.save_settings_main_folder()

    def save_settings_main_folder(self):
        if not self.profile:
            return
        self.profile.main_folder = self.settings_main_folder.text().strip()
        self.save()
        self.statusBar().showMessage("บันทึกโฟลเดอร์หลักแล้ว", 2500)

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

    def refresh_translation_progress(self):
        """Reload Context-backed progress from disk, including external edits."""
        if any(getattr(listing,"_dragging",False) for listing in (self.profile_cards,self.profiles)):
            self.context_refresh_timer.start(250)
            return self.ps_list
        profiles = self.repo.list_profiles()
        for profile in profiles:
            if sync_profile_context(profile):
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
                card.setText(f"{profile.name}\nแปลถึงบท {profile.chapter_state.current_chapter} · วันนี้ +{daily_chapter_count(profile)}\nวันนี้ส่ง {daily_export_count(profile)} ไฟล์ · {verified_goal_text(profile)}\n{_profile_status_label(_profile_status(profile))}")
                card.setToolTip(f"{profile.name}\nแปลถึงบท {profile.chapter_state.current_chapter}\nverified {verified_goal_text(profile)}")
        if self.profile:
            fresh = next((item for item in profiles if item.id == self.profile.id), None)
            if fresh:
                self.profile = fresh
        self._watch_context_paths()
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

        brand = QLabel("Palantir: Novel")
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

        root = QWidget()
        root.setObjectName("appShell")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.main_pages = MainPageStack()
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
        self.shell_splitter.setSizes([60, 1200])
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
        self.progress_timer.setInterval(10000)
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

    def navigate(self, key):
        if key == "library": self.show_library()
        elif key == "workspace":
            self._utility_return_page = self.workspace_stack
            self.return_from_utility_page()
        elif key == "progress": self.translation_dashboard()
        elif key == "groups": self.groups_dialog()
        elif key == "settings": self.settings_dialog()
        self._sync_navigation()

    def _sync_navigation(self, *_args):
        page = self.main_pages.currentWidget()
        key = "library" if page is self.library_page else "workspace"
        if page is self.utility_page:
            key = {"progress":"progress", "groups":"groups", "settings":"settings"}.get(self._active_utility_page, "workspace")
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
            if sync_profile_context(profile):
                changed = True
            if changed:
                self.repo.save_profile(profile)

        known_ids = {profile.id for profile in self.ps_list}
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
        for profile in self.ps_list:
            pixmap = QPixmap(str(placeholder)) if placeholder.is_file() else QPixmap()
            if profile.cover_image_path:
                try:
                    candidate = self.repo.resolve_project_path(
                        profile.id, profile.cover_image_path
                    )
                    if candidate.is_file():
                        pixmap = QPixmap(str(candidate))
                except ValueError:
                    pass
            if not pixmap.isNull():
                pixmap = pixmap.scaled(148, 188, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                pixmap = pixmap.copy((pixmap.width()-148)//2, (pixmap.height()-188)//2, 148, 188)
            status = _profile_status(profile)
            card = QListWidgetItem(
                QIcon(pixmap), f"{profile.name}\nแปลถึงบท {profile.chapter_state.current_chapter} · วันนี้ +{daily_chapter_count(profile)}\nวันนี้ส่ง {daily_export_count(profile)} ไฟล์ · {verified_goal_text(profile)}\n{_profile_status_label(status)}"
            )
            card.setData(Qt.UserRole, profile.id)
            card.setData(Qt.UserRole + 1, status)
            card.setToolTip(f"{profile.name}\nแปลถึงบท {profile.chapter_state.current_chapter}\nverified {verified_goal_text(profile)}")
            self.profile_cards.addItem(card)

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

    def filter_profiles(self, query):
        query = query.strip().casefold()
        selected_status = self.library_status_tabs.tabData(
            self.library_status_tabs.currentIndex()
        )
        visible = 0
        for index in range(self.profile_cards.count()):
            item = self.profile_cards.item(index)
            matches = (
                item.data(Qt.UserRole + 1) == selected_status
                and (not query or query in item.text().casefold())
            )
            item.setHidden(not matches)
            visible += int(matches)
        self.profile_cards.setVisible(visible > 0)
        self.library_empty_label.setText(
            f"ยังไม่มีนิยายในหมวด{_profile_status_label(selected_status)}"
            if not query else "ไม่พบนิยายที่ค้นหาในหมวดนี้"
        )
        self.library_empty_label.setVisible(visible == 0)

    def _open_profile_card(self, item):
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
            if self.settings.sidebar_visible:
                workspace.workspace_splitter.setSizes([
                    max(220, int(self.settings.sidebar_width or 290)), 1000,
                ])
            else:
                workspace.workspace_splitter.setSizes([0, 1000])
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
        return workspace

    def _open_profile_working_tabs(self, profile, workspace):
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
        workspace.editor.prioritize_paths(preferred)

    def _discard_workspace(self, profile_id):
        """Dispose an already saved workspace without deleting its profile/session."""
        workspace = self.workspaces.pop(profile_id, None)
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
        for _pid, workspace in previous:
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
            self._discard_workspace(pid)
        return True

    def _close_novel_tab(self, profile_id):
        if not profile_id or profile_id not in self._open_workspace_ids:
            return
        workspace = self.workspaces.get(profile_id)
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
        self.refresh_steps()
        if self.si >= 0:
            self.steps.setCurrentRow(self.si)
        self.refresh_goal_indicator()
        self._update_progress_page(workspace)
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
            workspace.stage_buttons = []

        if self.profile:
            for index, step in enumerate(self.profile.workflow.steps):
                # With an item widget the list paints both the item's text and
                # the button label. Keep the row text only when no button is used.
                item = QListWidgetItem("" if workspace else step.name)
                item.setSizeHint(QSize(0, 42))
                self.steps.addItem(item)
                if workspace:
                    button = WorkflowStageButton(step.name)
                    button.setObjectName("workflowStageButton")
                    button.setAccessibleName(step.name)
                    button.setProperty("workflowStageName", step.name)
                    button.setWorkflowActive(False)
                    button.setMinimumHeight(38)
                    button.setCursor(Qt.PointingHandCursor)
                    button.setToolTip(f"เลือกและคัดลอกไฟล์ของขั้นตอน{step.name}")
                    button.clicked.connect(
                        lambda checked=False, row=index, pid=self.profile.id:
                            self.copy_named_stage(pid, row)
                    )
                    button.setContextMenuPolicy(Qt.CustomContextMenu)
                    button.customContextMenuRequested.connect(
                        lambda pos, b=button: self._workflow_copy_menu(b, pos))
                    self.steps.setItemWidget(item, button)
                    workspace.stage_buttons.append(button)

        self.steps.blockSignals(False)
        if self.profile and self.profile.workflow.steps:
            if workspace:
                workspace.copy_step_button.setEnabled(
                    bool(self.profile.workflow.steps or self.profile.vocabulary_step)
                )
            self.si = max(
                0, min(desired, len(self.profile.workflow.steps) - 1)
            )
            self.steps.setCurrentRow(self.si)
        else:
            self.si = -1
            if workspace:
                workspace.copy_step_button.setEnabled(False)
        self.refresh_files()
        if workspace:
            self._sync_stage_buttons(workspace)

    def refresh_files(self):
        super().refresh_files()
        workspace = self.workspaces.get(self.profile.id) if self.profile else None
        if workspace:
            workspace.filter_files(workspace.file_search.text())

    def _step_changed(self, profile_id, row):
        if not self.profile or self.profile.id != profile_id or row < 0:
            return
        workspace = self.workspaces.get(profile_id)
        if workspace:
            if not workspace.editor.save_all(include_normalization=False):
                self.statusBar().showMessage("บันทึกไม่สำเร็จ จึงยังเปลี่ยนขั้นตอนไม่ได้", 5000)
                workspace.steps.blockSignals(True)
                workspace.steps.setCurrentRow(workspace.step_index)
                workspace.steps.blockSignals(False)
                return
            workspace.vocabulary_mode = False
            workspace.vocabulary_button.setWorkflowActive(False)
            workspace.vocabulary_button.update()
            workspace.step_index = row
            self.settings.workspace_step_indices[profile_id] = row
        self.si = row
        self.refresh_files()
        if workspace:
            self._sync_stage_buttons(workspace)

    @staticmethod
    def _sync_stage_buttons(workspace):
        for index, button in enumerate(workspace.stage_buttons):
            active = (
                not workspace.vocabulary_mode
                and index == workspace.step_index
            )
            button.setWorkflowActive(active)
        workspace.vocabulary_button.setWorkflowActive(workspace.vocabulary_mode)

    def _workflow_copy_menu(self, button, position):
        if not self.profile or not self.settings.copy_files_as_zip:
            return
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
        """Select a named stage and copy only its files without advancing."""
        if not self.profile or self.profile.id != profile_id:
            return
        workspace = self.workspaces.get(profile_id)
        if not workspace or not workspace.editor.save_all():
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
        self.copy_step(advance=False)
        self._schedule_workspace_session_save()

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
        if not workspace.editor.save_all(include_normalization=False):
            workspace.vocabulary_button.setWorkflowActive(not enabled)
            workspace.vocabulary_button.update()
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


    def copy_step(self, advance=True, selected_steps=None):
        workspace = self.workspaces.get(self.profile.id) if self.profile else None
        if workspace and not workspace.editor.save_all(include_normalization=False):
            self.statusBar().showMessage("บันทึกไม่สำเร็จ จึงคัดลอกไฟล์ไม่ได้", 5000)
            return
        super().copy_step(advance=advance, selected_steps=selected_steps)
        if advance and self.profile and workspace and not workspace.vocabulary_mode and self.si >= 0:
            workspace.step_index = self.si
        if workspace:
            self._sync_stage_buttons(workspace)

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

    def _document_saved(self, saved_path):
        for workspace in self.workspaces.values():
            workspace.refresh_history()
        self.refresh_translation_progress()
        if not self.profile:
            return
        if self.profile.context_path:
            try:
                if Path(self.profile.context_path).expanduser().resolve() == Path(saved_path).resolve():
                    self.refresh_translation_progress()
                    workspace = self.workspaces.get(self.profile.id)
                    if workspace:
                        self._update_context_button(workspace)
            except OSError:
                pass

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

    def update_context_from_translator(self, workspace):
        """Export bound Translator bytes and replace its Context in one transaction."""
        from .recovery import translator_chapter_range
        profile_id = workspace.profile_id
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
            if source_digest != editor.disk_digest:
                raise OSError("Translator ถูกแก้ไขจากภายนอก")
            original_digest = hashlib.sha256(context.read_bytes()).digest()
            chapter_range = translator_chapter_range(translator_bytes)
            root = (Path(profile.main_folder).expanduser() if profile.main_folder.strip()
                    else self.repo.profile_dir(profile.id))
            if not root.is_dir():
                root = self.repo.profile_dir(profile.id)
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
                if workspace.editor._dirty(context_editor):
                    QMessageBox.warning(self, "Export ไม่ได้", "Context มีการแก้ไขที่ยังไม่ได้บันทึก")
                    return False
                if hashlib.sha256(context.read_bytes()).digest() != context_editor.disk_digest:
                    QMessageBox.warning(self, "Export ไม่ได้", "Context ถูกแก้ไขจากภายนอก กรุณาเปิดไฟล์ใหม่เพื่อตรวจสอบ")
                    return False
            except OSError as exc:
                QMessageBox.warning(self, "Export ไม่ได้", str(exc))
                return False
        preview = QMessageBox(self)
        preview.setWindowTitle("ยืนยัน Export")
        preview.setIcon(QMessageBox.Information)
        preview.setText(
            f"สร้างไฟล์ TXT และแทนที่ Context ทั้งหมด?\n"
            f"TXT: {target.name}\n{chapter_label}\n"
            f"Translator: {source}\nContext: {context}"
        )
        preview.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        if preview.exec() != QMessageBox.Yes:
            return False

        try:
            fresh_profile = self._translator_profile_for_path(profile_id, source)
            if (fresh_profile is None
                    or Path(fresh_profile.context_path).expanduser().resolve() != context):
                raise OSError("โปรไฟล์หรือไฟล์ที่ผูกไว้เปลี่ยนไประหว่างยืนยัน")
            if hashlib.sha256(source.read_bytes()).digest() != source_digest:
                raise OSError("Translator ถูกแก้ไขจากภายนอกระหว่างยืนยัน")
            if target.exists():
                raise OSError("พบไฟล์ชื่อเดียวกันระหว่างเตรียม Export กรุณาลองอีกครั้ง")
            if hashlib.sha256(context.read_bytes()).digest() != original_digest:
                raise OSError("Context ถูกแก้ไขจากภายนอกระหว่างการยืนยัน")
            staged_files.append((target, _stage_bytes_file(target, translator_bytes)))
            staged_files.append((context, _stage_bytes_file(context, translator_bytes)))
            def verify_transaction():
                if target.read_bytes() != translator_bytes or context.read_bytes() != translator_bytes:
                    raise OSError("ตรวจสอบหลังเขียนพบว่าไฟล์ TXT หรือ Context ไม่ตรงกับ Translator")
            commit_staged(
                staged_files,
                commit_metadata=verify_transaction,
                create_backups=False,
                no_overwrite=(target,),
            )
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Export ไม่สำเร็จ", str(exc))
            return False
        finally:
            for _destination, staged in staged_files:
                _cleanup_staged_text_file(staged)

        workspace.editor.apply_external_update(context, visible_text)
        self.refresh_translation_progress()
        self.statusBar().showMessage(f"Export {target.name} และอัปเดต Context สำเร็จ", 5000)
        QMessageBox.information(self, "Export สำเร็จ", f"สร้าง {target.name} และอัปเดต Context สำเร็จ")
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
                "Palantir: Novel",
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
            self.context_status.setFullText(f"แปลถึงบท {latest}")
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
        if not self.profile:
            return
        workspace = self.workspaces.get(self.profile.id)
        if workspace is not None and workspace.editor is editor:
            context_path = Path(self.profile.context_path).expanduser().resolve() if self.profile.context_path else None
            if context_path:
                for index in range(editor.tabs.count()):
                    widget = editor.tabs.widget(index)
                    text_editor = widget.editor if hasattr(widget, "editor") else widget
                    path = editor._path(text_editor)
                    if path and path.expanduser().resolve() == context_path:
                        latest = latest_context_chapter(text_editor.toPlainText())
                        self._latest_context_chapter = latest
                        self.context_status.setFullText(
                            f"แปลถึงบท {latest}" if latest is not None else "ไม่พบบทใน Context"
                        )
                        break
            self._update_editor_status(text)

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
            progress_tooltip = "จำนวนบทที่ Context บันทึกเพิ่มในวันนี้"
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
        self._automatic_update_timer.stop()
        timer = getattr(self, "_session_save_timer", None)
        if timer is not None:
            timer.stop()
        workers = [self._update_check_worker, self._update_download_worker]
        workers.extend(getattr(page, "worker", None)
                       for key, page in self._utility_pages.items()
                       if key.startswith("downloader:"))
        for worker in workers:
            if worker and worker.isRunning():
                worker.requestInterruption()
                if not getattr(worker, "_close_resume_connected", False):
                    worker._close_resume_connected = True
                    worker.finished.connect(lambda: QTimer.singleShot(0, self.close))
                self.statusBar().showMessage("กำลังยกเลิกงานเบื้องหลังก่อนปิดโปรแกรม…")
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
