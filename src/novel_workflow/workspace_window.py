from __future__ import annotations

import shutil
import tempfile
from datetime import date
from pathlib import Path
import subprocess

from PySide6.QtCore import QDir, QFileSystemWatcher, QSize, Qt, QTimer, Signal, QThread
from PySide6.QtGui import QAction, QFontMetrics, QIcon, QPixmap, QPainter, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QFileDialog, QFileSystemModel, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QProgressBar, QPushButton, QSizePolicy, QSplitter, QStackedWidget,
    QToolButton, QTreeView, QVBoxLayout, QWidget, QInputDialog, QComboBox, QTextEdit,
    QTabWidget, QCheckBox, QProgressDialog,
)

from .models import LaunchTarget, StepFile, migrate_legacy_basic_workflow, migrate_legacy_vocabulary_step
from .translation_progress import (
    daily_chapter_count, goal_progress, latest_context_chapter,
    sync_profile_context,
)
from .ui import MainWindow as LegacyMainWindow
from .workspace_editor import EditorTabs
from . import __version__
from .updater import UpdateError, UpdateInfo, check_for_update, download_update


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
    """Draw the active marker in a reserved gutter without changing the label."""

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.property("workflowActive"):
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.TextAntialiasing)
        painter.setPen(self.palette().color(QPalette.ButtonText))
        painter.drawText(8, 0, 18, self.height(), Qt.AlignCenter, "›")


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


class ReorderableProfileList(QListWidget):
    """Profile list with native click-and-drag reordering."""

    orderChanged = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setToolTip("คลิกค้างที่นิยายแล้วลากเพื่อจัดลำดับ")

    def dropEvent(self, event):
        super().dropEvent(event)
        self.orderChanged.emit([
            self.item(index).data(Qt.UserRole)
            for index in range(self.count())
        ])


class ProfileWorkspace(QWidget):
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
        )
        self.steps = QListWidget()
        self.steps.setObjectName("workflowSteps")
        self.steps.setSelectionMode(QAbstractItemView.SingleSelection)
        self.steps.setSpacing(2)
        self.stage_buttons = []
        self.vocabulary_mode = False
        self.vocabulary_button = WorkflowStageButton("หาศัพท์")
        self.vocabulary_button.setObjectName("vocabularyButton")
        self.vocabulary_button.setProperty("workflowActive", False)
        self.vocabulary_button.setToolTip("คัดลอกไฟล์ของขั้นตอนหาศัพท์ไปยังคลิปบอร์ด")
        self.vocabulary_button.clicked.connect(
            lambda checked=False: self.owner.copy_named_stage(self.profile_id, "vocabulary")
        )
        self.files = QListWidget()
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
        self.sidebar_toggle.setToolTip("ซ่อน/แสดงแถบด้านข้าง")
        self.sidebar_toggle.clicked.connect(self.toggle_sidebar)
        self.editor_header = QFrame()
        header_layout = QHBoxLayout(self.editor_header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        self.breadcrumb = QLabel("เลือกไฟล์จากแถบด้านข้าง")
        self.breadcrumb.setObjectName("mutedLabel")
        header_layout.addWidget(self.sidebar_toggle)
        header_layout.addWidget(self.breadcrumb, 1)
        self.context_button = QToolButton()
        self.context_button.setText("Context")
        self.context_button.setToolTip("เลือกไฟล์ Context ที่ติดตามความคืบหน้า")
        self.context_button.clicked.connect(self._choose_context)
        header_layout.addWidget(self.context_button)
        find_button = QToolButton()
        find_button.setText("ค้นหา")
        find_button.setToolTip("ค้นหาในไฟล์ปัจจุบัน  ·  Ctrl+H")
        find_button.clicked.connect(self.editor.show_find)
        header_layout.addWidget(find_button)
        decrease_font = QToolButton()
        decrease_font.setText("A−")
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
        increase_font.setToolTip("เพิ่มขนาดตัวอักษร  ·  Ctrl++")
        increase_font.clicked.connect(lambda: self.owner.adjust_editor_font_size(1))
        header_layout.addWidget(increase_font)
        reset_font = QToolButton()
        reset_font.setText("A")
        reset_font.setToolTip("คืนขนาดตัวอักษรเริ่มต้น")
        reset_font.clicked.connect(lambda: self.owner.set_editor_font_size(11.0))
        header_layout.addWidget(reset_font)
        editor_layout = QVBoxLayout()
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(3)
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
        self.workspace_splitter.setSizes([290, 1100])
        self.workspace_splitter.splitterMoved.connect(self._remember_sidebar_width)

        self.goal_panel = QFrame()
        self.goal_panel.setObjectName("goalPanel")
        goal_layout = QVBoxLayout(self.goal_panel)
        self.goal_label = QLabel("เป้าหมายวันนี้")
        self.goal_bar = QProgressBar()
        self.goal_bar.setFixedHeight(15)
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
        if sizes and sizes[0] > 0:
            self.owner.settings.sidebar_width = sizes[0]
            self.owner.settings.sidebar_visible = False
            self.workspace_splitter.setSizes([0, max(1, sum(sizes))])
        else:
            self.owner.settings.sidebar_visible = True
            self.workspace_splitter.setSizes([
                max(220, int(self.owner.settings.sidebar_width or 290)),
                1000,
            ])
        self.owner.repo.save_settings(self.owner.settings)

    def _remember_sidebar_width(self, _position, index):
        if index == 1 and self.workspace_splitter.sizes()[0] > 0:
            self.owner.settings.sidebar_width = self.workspace_splitter.sizes()[0]

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


class MainWindow(LegacyMainWindow):
    """Novel Library with a focused workflow sidebar and full-size editor."""

    def __init__(self, repo=None):
        super().__init__(repo)
        changed = False
        if not self.settings.appearance_migrated:
            # Dark was the old default. Honor the user's newer request for the
            # readable light workspace once, while preserving future choices.
            if self.settings.appearance == "Dark":
                self.settings.appearance = "Light"
                changed = True
            self.settings.appearance_migrated = True
            changed = True
        if not self.settings.editor_style_migrated:
            # The previous default was 11 pt; move unusually enlarged legacy
            # settings back to the requested compact reference size once.
            if self.settings.editor_font_size > 12.0:
                self.settings.editor_font_size = 11.0
                changed = True
            self.settings.editor_style_migrated = True
            changed = True
        if changed:
            self.apply_theme()
            self.repo.save_settings(self.settings)

    def apply_theme(self):
        super().apply_theme()
        for workspace in getattr(self, "workspaces", {}).values():
            workspace.editor.set_appearance(self.settings.appearance)

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
            self.workspace_stack.setCurrentWidget(workspace)
            self.main_pages.setCurrentWidget(self.workspace_stack)
        else:
            self.main_pages.setCurrentWidget(self.library_page)

    def groups_dialog(self):
        self._show_utility_page("groups", "กลุ่มนิยาย", lambda: NovelGroupsPage(self))

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

    def _build_settings_page(self):
        original_lists = (self.profiles, self.steps, self.files)
        previous_profile_id = self.profile.id if self.profile else None
        active_step = self.step()
        active_step_id = active_step.id if active_step else None
        active_workspace = self.workspaces.get(previous_profile_id) if previous_profile_id else None
        active_vocabulary_mode = bool(active_workspace and active_workspace.vocabulary_mode)
        page = QWidget()
        root = QVBoxLayout(page)
        tabs = QTabWidget()
        root.addWidget(tabs, 1)

        self.profiles = ReorderableProfileList()
        self.profiles.orderChanged.connect(self._persist_profile_order)
        self.profiles.setSpacing(1)
        self.profiles.setCursor(Qt.PointingHandCursor)
        self.profiles.setAccessibleName("รายการนิยาย")
        self.profiles.currentRowChanged.connect(self.select_profile)
        self.steps = QListWidget()
        self.steps.setSpacing(1)
        self.steps.setCursor(Qt.PointingHandCursor)
        self.steps.setAccessibleName("ขั้นตอนงาน")
        self.steps.setSelectionMode(QAbstractItemView.SingleSelection)
        self.steps.currentRowChanged.connect(self.select_step)
        self.files = QListWidget()
        self.files.setSpacing(1)
        self.files.setCursor(Qt.PointingHandCursor)
        self.files.setAccessibleName("ไฟล์ของขั้นตอน")
        self.files.itemChanged.connect(self.toggle_file)
        self.file_scope_selector = QComboBox()
        self.file_scope_selector.addItems(["ไฟล์ของขั้นตอน", "ไฟล์หาศัพท์"])
        files_panel = QWidget()
        files_layout = QVBoxLayout(files_panel)
        files_layout.setContentsMargins(0, 0, 0, 0)
        files_layout.addWidget(self.file_scope_selector)
        files_layout.addWidget(self.files, 1)
        self.file_scope_selector.currentIndexChanged.connect(self._settings_file_scope_changed)

        def management_tab(title, widget, buttons):
            tab = QWidget()
            layout = QVBoxLayout(tab)
            layout.setContentsMargins(14, 14, 14, 14)
            layout.addWidget(widget, 1)
            grid = QGridLayout()
            grid.setHorizontalSpacing(8)
            grid.setVerticalSpacing(8)
            for index, (label, callback) in enumerate(buttons):
                button = QPushButton(label)
                button.setMinimumHeight(40)
                button.clicked.connect(callback)
                grid.addWidget(button, index // 2, index % 2)
            layout.addLayout(grid)
            tabs.addTab(tab, title)

        management_tab("นิยาย", self.profiles, [
            ("เพิ่มนิยาย", self.new_profile), ("ทำสำเนา", self.duplicate_profile),
            ("เลื่อนขึ้น", lambda: self.move_profile(-1)), ("เลื่อนลง", lambda: self.move_profile(1)),
            ("ตั้งรูปปก", self.set_cover), ("เอารูปปกออก", self.remove_cover),
            ("เลือก Context", self.set_context_file), ("เปลี่ยนชื่อ", self.rename_profile),
            ("รายการที่เปิด", self.launcher_dialog), ("ลบนิยาย", self.delete_profile),
        ])
        management_tab("ขั้นตอน", self.steps, [
            ("เพิ่มขั้นตอน", self.add_step), ("เปลี่ยนชื่อ", self.rename_step),
            ("ทำสำเนา", self.duplicate_step), ("ลบขั้นตอน", self.delete_step),
            ("เลื่อนขึ้น", lambda: self.move_step(-1)), ("เลื่อนลง", lambda: self.move_step(1)),
            ("บันทึกเป็นแม่แบบ", self.save_template),
        ])
        management_tab("ไฟล์แนบ", files_panel, [
            ("เพิ่มไฟล์", self.add_file), ("อ้างอิงบทปัจจุบัน", self.add_dynamic),
            ("เอาออกจากขั้นตอน", self.remove_file), ("เลื่อนขึ้น", lambda: self.move_file(-1)),
            ("เลื่อนลง", lambda: self.move_file(1)), ("เปลี่ยนชื่อที่แสดง", self.rename_file_label),
            ("จัดการไฟล์", self.file_manager), ("ดูตัวอย่าง", self.preview),
        ])

        preferences = QWidget()
        prefs = QVBoxLayout(preferences)
        appearance = QComboBox()
        appearance.addItems(["System", "Light", "Dark"])
        appearance.setCurrentText(self.settings.appearance)
        prefs.addWidget(QLabel("รูปลักษณ์"))
        prefs.addWidget(appearance)
        separator = QLineEdit(self.settings.separator)
        prefs.addWidget(QLabel("ตัวคั่นเนื้อหา (ใช้ {FILE_NAME})"))
        prefs.addWidget(separator)
        checks = []
        for label, attr in (("แสดงชื่อไฟล์", "show_filename_heading"),
                            ("ยืนยันก่อนลบ", "confirm_before_deleting"),
                            ("เปิดนิยายล่าสุดเมื่อเริ่มโปรแกรม", "open_last_profile")):
            check = QCheckBox(label)
            check.setChecked(getattr(self.settings, attr))
            prefs.addWidget(check)
            checks.append((check, attr))
        prefs.addStretch(1)
        tabs.addTab(preferences, "ทั่วไป")

        save = QPushButton("บันทึกการตั้งค่า")
        save.setMinimumHeight(42)
        root.addWidget(save, alignment=Qt.AlignRight)

        self._settings_open = True
        self._management_vocabulary_mode = False
        self._settings_page_state = {
            "page": page, "original_lists": original_lists,
            "profile_id": previous_profile_id, "step_id": active_step_id,
            "vocabulary_mode": active_vocabulary_mode,
        }
        self.refresh_profiles(previous_profile_id)

        def save_preferences():
            self.settings.appearance = appearance.currentText()
            self.settings.separator = separator.text()
            for check, attr in checks:
                setattr(self.settings, attr, check.isChecked())
            self.save()
            self.apply_theme()
            self.statusBar().showMessage("บันทึกการตั้งค่าแล้ว", 3000)

        save.clicked.connect(save_preferences)

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

    def launcher_dialog(self):
        if not self.profile:
            return
        page = QWidget()
        layout = QVBoxLayout(page)
        folder = QLineEdit(self.profile.main_folder)
        folder.setPlaceholderText("โฟลเดอร์หลักของนิยาย")
        layout.addWidget(QLabel("โฟลเดอร์หลัก"))
        layout.addWidget(folder)
        listing = QListWidget()
        targets = list(self.profile.launch_targets)
        for target in sorted(targets, key=lambda item: item.order):
            row = QListWidgetItem(f"{target.label or target.target}  ·  {target.kind}")
            row.setData(Qt.UserRole, target.id)
            row.setFlags(row.flags() | Qt.ItemIsUserCheckable)
            row.setCheckState(Qt.Checked if target.enabled else Qt.Unchecked)
            listing.addItem(row)
        layout.addWidget(listing, 1)
        actions = QHBoxLayout()

        def add_target(kind):
            if kind == "folder":
                target, _ = QFileDialog.getExistingDirectory(self, "เลือกโฟลเดอร์", str(self.profile_browse_directory())), True
            elif kind == "file":
                target, _ = QFileDialog.getOpenFileName(self, "เลือกไฟล์", str(self.profile_browse_directory()), "All files (*)")
            elif kind == "application":
                target, _ = QFileDialog.getOpenFileName(self, "เลือกโปรแกรม", str(Path.home()), "Applications (*.exe);;All files (*)")
            else:
                target, accepted = QInputDialog.getText(self, "เพิ่มเว็บไซต์", "URL (http/https):")
                if not accepted:
                    return
            if not target:
                return
            label = Path(target).name if kind != "website" else target
            if kind == "website":
                label, accepted = QInputDialog.getText(self, "ชื่อเว็บไซต์", "ชื่อ:", text=target)
                if not accepted:
                    return
            item = LaunchTarget(label=label, kind=kind, target=target, order=len(targets))
            targets.append(item)
            row = QListWidgetItem(f"{item.label}  ·  {item.kind}")
            row.setData(Qt.UserRole, item.id)
            row.setFlags(row.flags() | Qt.ItemIsUserCheckable)
            row.setCheckState(Qt.Checked)
            listing.addItem(row)

        for label, kind in (("＋ App", "application"), ("＋ ไฟล์", "file"), ("＋ โฟลเดอร์", "folder"), ("＋ Website", "website")):
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, value=kind: add_target(value))
            actions.addWidget(button)

        remove = QPushButton("เอารายการออก")
        def remove_target():
            row = listing.currentItem()
            if row is None:
                return
            targets[:] = [target for target in targets if target.id != row.data(Qt.UserRole)]
            listing.takeItem(listing.row(row))
        remove.clicked.connect(remove_target)
        actions.addWidget(remove)
        layout.addLayout(actions)
        save = QPushButton("บันทึก")
        save.clicked.connect(lambda: self._save_launch_page(targets, listing, folder.text()))
        layout.addWidget(save, alignment=Qt.AlignRight)
        self._show_utility_page("launcher", f"รายการที่เปิด · {self.profile.name}", lambda: page)

    def _save_launch_page(self, targets, listing, main_folder):
        if not self.profile:
            return
        for index in range(listing.count()):
            row = listing.item(index)
            target = next((item for item in targets if item.id == row.data(Qt.UserRole)), None)
            if target:
                target.enabled = row.checkState() == Qt.Checked
                target.order = index
        self.profile.main_folder = main_folder.strip()
        self.profile.launch_targets = targets
        self.save()
        self.statusBar().showMessage("บันทึกรายการที่เปิดแล้ว", 3000)

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

        def open_selected():
            path = selected_path()
            workspace = self.workspaces.get(profile.id)
            if path and workspace and workspace.editor.supports(path):
                workspace.editor.open_file(path)
                self.return_from_utility_page()

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
            source, _ = QFileDialog.getOpenFileName(self, "นำเข้าไฟล์", str(self.profile_browse_directory()), "Text files (*.txt *.md *.json)")
            if not source:
                return
            src = Path(source)
            if src.suffix.lower() not in (".txt", ".md", ".json"):
                QMessageBox.warning(self, "นำเข้าไม่ได้", "รองรับ .txt, .md และ .json")
                return
            relative, accepted = QInputDialog.getText(self, "นำเข้าไฟล์", "ตำแหน่งปลายทาง:", text=f"reference/{src.name}")
            if not accepted or not relative:
                return
            dest = self.repo.resolve_project_path(profile.id, relative)
            if dest.exists():
                QMessageBox.warning(self, "นำเข้าไม่ได้", "มีไฟล์ชื่อนี้แล้ว")
                return
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            refresh(search.text())
        import_button.clicked.connect(import_file)
        actions.addWidget(import_button)

        open_button = QPushButton("เปิด/แก้ไข")
        open_button.clicked.connect(open_selected)
        actions.addWidget(open_button)

        attach = QPushButton("เพิ่มในขั้นตอน")
        def attach_file():
            path = selected_path()
            step = self.step()
            if not path or not step:
                return
            relative = path.relative_to(root).as_posix()
            if any(file.path == relative for file in step.files):
                self.statusBar().showMessage("ไฟล์นี้อยู่ในขั้นตอนแล้ว", 2500)
                return
            step.files.append(StepFile(label=path.stem, path=relative, file_type=path.parent.name, order=len(step.files)))
            self.save()
            self.refresh_files()
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
        actions.addWidget(rename)

        delete = QPushButton("ลบไฟล์")
        def delete_file():
            path = selected_path()
            if not path:
                return
            if QMessageBox.question(self, "ลบไฟล์", f"ลบ {path.name} ถาวรใช่ไหม?") != QMessageBox.Yes:
                return
            path.unlink()
            for step in profile.workflow.steps:
                step.files = [file for file in step.files if file.reference_type == "external_file" or not file.path or self.repo.resolve_project_path(profile.id, file.path) != path]
            self.save()
            self.refresh_files()
            refresh(search.text())
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
        profiles = self.repo.list_profiles()
        for profile in profiles:
            if sync_profile_context(profile):
                try:
                    self.repo.save_profile(profile)
                except OSError as exc:
                    self.statusBar().showMessage(f"บันทึกความคืบหน้าไม่ได้: {exc}", 6000)
        self.ps_list = profiles
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
        self.resize(1440, 860)

        bar = self.addToolBar("Main")
        bar.setObjectName("mainToolbar")
        bar.setMovable(False)
        bar.setIconSize(QSize(28, 28))

        logo = Path(__file__).resolve().parent / "resources" / "novelworkflow.png"
        mark = QLabel()
        mark.setObjectName("toolbarLogo")
        if logo.is_file():
            mark.setPixmap(
                QPixmap(str(logo)).scaled(
                    28, 28, Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
            )
        bar.addWidget(mark)

        brand = QLabel("NovelWorkflow")
        brand.setObjectName("brandTitle")
        bar.addWidget(brand)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        bar.addWidget(spacer)

        for label, callback in (
            ("คลังนิยาย", self.show_library),
            ("เปิดรายการของเรื่อง", self.launch_profile),
            ("กลุ่มนิยาย", self.groups_dialog),
            ("สถิติ", self.translation_dashboard),
            ("ตรวจสอบอัปเดต", self.check_updates),
            ("ตั้งค่า", self.settings_dialog),
        ):
            action = QAction(label, self)
            action.triggered.connect(callback)
            bar.addAction(action)

        root = QWidget()
        root.setObjectName("appShell")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.main_pages = QStackedWidget()
        self.library_page = QWidget()
        library_layout = QVBoxLayout(self.library_page)
        library_layout.setContentsMargins(24, 18, 24, 18)
        library_header = QHBoxLayout()
        library_title = QLabel("Novel Library")
        library_title.setObjectName("currentNovel")
        library_header.addWidget(library_title, 1)
        self.library_search = QLineEdit()
        self.library_search.setPlaceholderText("ค้นหานิยาย…")
        self.library_search.setMaximumWidth(340)
        self.library_search.textChanged.connect(self.filter_profiles)
        library_header.addWidget(self.library_search)
        add_story = QPushButton("＋ เพิ่มนิยาย")
        add_story.clicked.connect(self.new_profile)
        library_header.addWidget(add_story)
        library_layout.addLayout(library_header)
        self.profile_cards = QListWidget()
        self.profile_cards.setObjectName("novelLibrary")
        self.profile_cards.setViewMode(QListWidget.IconMode)
        self.profile_cards.setFlow(QListWidget.LeftToRight)
        self.profile_cards.setWrapping(True)
        self.profile_cards.setResizeMode(QListWidget.Adjust)
        self.profile_cards.setMovement(QListWidget.Static)
        self.profile_cards.setSpacing(14)
        self.profile_cards.setIconSize(QSize(136, 170))
        self.profile_cards.setGridSize(QSize(192, 250))
        self.profile_cards.itemClicked.connect(self._open_profile_card)
        library_layout.addWidget(self.profile_cards, 1)
        self.main_pages.addWidget(self.library_page)

        self.workspace_stack = QStackedWidget()
        self.empty_page = QLabel("ยังไม่มีนิยาย\nกด + เพื่อเพิ่มนิยาย")
        self.empty_page.setAlignment(Qt.AlignCenter)
        self.empty_page.setObjectName("mutedLabel")
        self.workspace_stack.addWidget(self.empty_page)
        self.main_pages.addWidget(self.workspace_stack)

        self.utility_page = QWidget()
        utility_layout = QVBoxLayout(self.utility_page)
        utility_layout.setContentsMargins(24, 16, 24, 20)
        utility_layout.setSpacing(12)
        utility_header = QHBoxLayout()
        self.utility_back = QPushButton("← กลับ")
        self.utility_back.clicked.connect(self.return_from_utility_page)
        utility_header.addWidget(self.utility_back)
        self.utility_title = QLabel()
        self.utility_title.setObjectName("currentNovel")
        utility_header.addWidget(self.utility_title, 1)
        utility_layout.addLayout(utility_header)
        self.utility_stack = QStackedWidget()
        utility_layout.addWidget(self.utility_stack, 1)
        self.main_pages.addWidget(self.utility_page)
        self._utility_pages = {}
        self._active_utility_page = None
        self._utility_return_page = None
        self._settings_page_state = None
        root_layout.addWidget(self.main_pages, 1)


        self.setCentralWidget(root)

        # Compatibility widgets let the existing management workflows
        # services continue to operate without migrating stored data.
        self.profiles = QListWidget()
        self.profiles.currentRowChanged.connect(self.select_profile)
        self.novel = QLabel()
        self.steps = QListWidget()
        self.files = QListWidget()
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
        self.statusBar().addPermanentWidget(self.progress_status)
        self.goal_status = ElidingStatusLabel("ยังไม่ได้ตั้งเป้าหมาย")
        self.goal_status.setObjectName("goalStatusBar")
        self.goal_status.setMinimumWidth(150)
        self.goal_status.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        self.goal_status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.statusBar().addPermanentWidget(self.goal_status)
        self.goal_status_bar = QProgressBar()
        self.goal_status_bar.setObjectName("goalProgressStatusBar")
        self.goal_status_bar.setRange(0, 100)
        self.goal_status_bar.setFixedSize(92, 12)
        self.goal_status_bar.setTextVisible(False)
        self.statusBar().addPermanentWidget(self.goal_status_bar)
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
        if self.settings.last_update_check_date != date.today().isoformat():
            QTimer.singleShot(2500, lambda: self.check_updates(manual=False))

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
        answer = QMessageBox.question(
            self,
            f"มีอัปเดต v{update.version}",
            f"เวอร์ชันปัจจุบัน: v{__version__}\nเวอร์ชันใหม่: v{update.version}\n\n"
            f"{notes}\n\nดาวน์โหลดและตรวจสอบไฟล์ติดตั้งตอนนี้ไหม?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if answer == QMessageBox.Yes:
            destination = Path(tempfile.gettempdir()) / f"NovelWorkflow-Setup-{update.version}.exe"
            self._download_update(update, destination)

    def _download_update(self, update: UpdateInfo, destination: Path):
        dialog = QProgressDialog("กำลังดาวน์โหลดและตรวจสอบไฟล์ติดตั้ง…", "ยกเลิก", 0, 100, self)
        dialog.setWindowTitle(f"ดาวน์โหลด v{update.version}")
        dialog.setWindowModality(Qt.WindowModal)
        dialog.setMinimumDuration(0)
        worker = _UpdateDownloadWorker(update, destination, self)
        self._update_download_worker = worker
        self._update_progress = dialog
        dialog.canceled.connect(worker.requestInterruption)
        worker.progress.connect(dialog.setValue)

        def complete(path, error):
            self._update_download_worker = None
            self._update_progress = None
            dialog.close()
            dialog.deleteLater()
            if error:
                QMessageBox.warning(self, "ดาวน์โหลดอัปเดตไม่ได้", error)
                return
            answer = QMessageBox.question(
                self,
                "ติดตั้งอัปเดต",
                f"ดาวน์โหลด v{update.version} และตรวจ SHA-256 ผ่านแล้ว\n\n"
                "ต้องการปิดโปรแกรมและเปิดตัวติดตั้งหรือไม่?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if answer == QMessageBox.Yes:
                try:
                    subprocess.Popen([str(path)], close_fds=True)
                    QApplication.quit()
                except OSError as exc:
                    QMessageBox.warning(self, "เปิดตัวติดตั้งไม่ได้", str(exc))

        worker.finished_download.connect(complete)
        worker.start()

    def refresh_profiles(self, pid=None):
        if getattr(self, "_settings_open", False):
            result = super().refresh_profiles(pid)
            for index, profile in enumerate(getattr(self, "ps_list", [])):
                item = self.profiles.item(index)
                if item:
                    item.setData(Qt.UserRole, profile.id)
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
                pixmap = pixmap.scaled(136, 170, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                pixmap = pixmap.copy((pixmap.width()-136)//2, (pixmap.height()-170)//2, 136, 170)
            card = QListWidgetItem(QIcon(pixmap), f"{profile.name}\n{profile.status}")
            card.setData(Qt.UserRole, profile.id)
            card.setToolTip(profile.name)
            self.profile_cards.addItem(card)

        target_id = pid or (
            self.settings.last_profile_id
            if self.settings.open_last_profile else None
        )
        index = next(
            (i for i, profile in enumerate(self.ps_list) if profile.id == target_id),
            0 if self.ps_list else -1,
        )
        if index >= 0:
            self.select_profile(index)
        else:
            self.profile = None
            self.si = -1
            self.workspace_stack.setCurrentWidget(self.empty_page)
            self.main_pages.setCurrentWidget(self.library_page)

    def filter_profiles(self, query):
        query = query.strip().casefold()
        for index in range(self.profile_cards.count()):
            item = self.profile_cards.item(index)
            item.setHidden(bool(query) and query not in item.text().casefold())

    def _open_profile_card(self, item):
        profile_id = item.data(Qt.UserRole)
        index = next((i for i, profile in enumerate(self.ps_list) if profile.id == profile_id), -1)
        if index >= 0:
            self.select_profile(index)

    def show_library(self):
        if self._settings_page_state:
            self._restore_settings_management()
        self._active_utility_page = None
        self._utility_return_page = None
        if self.profile:
            workspace = self.workspaces.get(self.profile.id)
            if workspace and not workspace.editor.save_all():
                self.statusBar().showMessage("บันทึกไม่สำเร็จ จึงยังเปลี่ยนหน้าไม่ได้", 5000)
                return
        self.main_pages.setCurrentWidget(self.library_page)

    def _workspace(self, profile):
        workspace = self.workspaces.get(profile.id)
        if workspace is None:
            workspace = ProfileWorkspace(self, profile)
            workspace.steps.currentRowChanged.connect(
                lambda row, pid=profile.id: self._step_changed(pid, row)
            )
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
            )
            workspace.step_index = int(self.settings.workspace_step_indices.get(profile.id, 0))
            if self.settings.sidebar_visible:
                workspace.workspace_splitter.setSizes([
                    max(220, int(self.settings.sidebar_width or 290)), 1000
                ])
            else:
                workspace.workspace_splitter.setSizes([0, 1000])
            positions = self.settings.editor_positions.get(profile.id, {})
            for editor_index in range(workspace.editor.tabs.count()):
                editor = workspace.editor.tabs.widget(editor_index)
                path = str(workspace.editor._path(editor))
                position = positions.get(path, {})
                cursor = editor.textCursor()
                cursor.setPosition(min(int(position.get("cursor", 0)), len(editor.toPlainText())))
                editor.setTextCursor(cursor)
                editor.verticalScrollBar().setValue(int(position.get("scroll", 0)))
        else:
            workspace.configure(profile)
        return workspace

    def select_profile(self, index):
        if getattr(self, "_settings_open", False):
            return super().select_profile(index)
        if index < 0 or index >= len(getattr(self, "ps_list", [])):
            return

        old_profile = getattr(self, "profile", None)
        if old_profile and old_profile.id != self.ps_list[index].id:
            previous = self.workspaces.get(old_profile.id)
            if previous and not previous.editor.save_all():
                self.statusBar().showMessage("บันทึกไม่สำเร็จ จึงยังเปลี่ยนนิยายไม่ได้", 5000)
                return
        self.profile = self.ps_list[index]
        self.settings.last_profile_id = self.profile.id
        workspace = self._workspace(self.profile)

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

    def refresh_steps(self):
        if getattr(self, "_settings_open", False):
            return super().refresh_steps()

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
                item = QListWidgetItem(step.name)
                item.setSizeHint(QSize(0, 42))
                self.steps.addItem(item)
                if workspace:
                    button = WorkflowStageButton(step.name)
                    button.setObjectName("workflowStageButton")
                    button.setProperty("workflowStageName", step.name)
                    button.setProperty("workflowActive", False)
                    button.setMinimumHeight(38)
                    button.setCursor(Qt.PointingHandCursor)
                    button.setToolTip(f"เลือกและคัดลอกไฟล์ของขั้นตอน{step.name}")
                    button.clicked.connect(
                        lambda checked=False, row=index, pid=self.profile.id:
                            self.copy_named_stage(pid, row)
                    )
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
            if not workspace.editor.save_all():
                self.statusBar().showMessage("บันทึกไม่สำเร็จ จึงยังเปลี่ยนขั้นตอนไม่ได้", 5000)
                workspace.steps.blockSignals(True)
                workspace.steps.setCurrentRow(workspace.step_index)
                workspace.steps.blockSignals(False)
                return
            workspace.vocabulary_mode = False
            workspace.vocabulary_button.setProperty("workflowActive", False)
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
            active = not workspace.vocabulary_mode and index == workspace.step_index
            button.setProperty("workflowActive", active)
            button.update()
        workspace.vocabulary_button.setProperty(
            "workflowActive", workspace.vocabulary_mode
        )
        workspace.vocabulary_button.update()

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

    def step(self):
        """Return the currently active vocabulary or translation step."""
        if self.profile:
            if getattr(self, "_settings_open", False):
                if getattr(self, "_management_vocabulary_mode", False):
                    return self.profile.vocabulary_step
            else:
                workspace = self.workspaces.get(self.profile.id)
                if workspace and workspace.vocabulary_mode:
                    return self.profile.vocabulary_step
        return super().step()

    def _settings_file_scope_changed(self, index):
        self._management_vocabulary_mode = index == 1
        if getattr(self, "_settings_open", False):
            self.refresh_files()

    def set_vocabulary_mode(self, profile_id, enabled):
        workspace = self.workspaces.get(profile_id)
        if not workspace or not self.profile or self.profile.id != profile_id:
            return
        if not workspace.editor.save_all():
            workspace.vocabulary_button.setProperty("workflowActive", not enabled)
            workspace.vocabulary_button.update()
            self.statusBar().showMessage("บันทึกไม่สำเร็จ จึงยังเปลี่ยนขั้นตอนไม่ได้", 5000)
            return
        workspace.vocabulary_mode = enabled
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
            return super().select_step(index)
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


    def copy_step(self, advance=True):
        workspace = self.workspaces.get(self.profile.id) if self.profile else None
        super().copy_step(advance=advance)
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

    def launch_profile(self):
        """Open supported profile targets inside the current workspace."""
        if not self.profile:
            return

        workspace = self._workspace(self.profile)
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
                "NovelWorkflow",
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
                    latest = latest_context_chapter(
                        context.read_text(
                            encoding="utf-8-sig", errors="replace"
                        )
                    )
            except OSError:
                latest = None

        self._latest_context_chapter = latest
        self._latest_chapter_status = (
            f"  ·  ล่าสุดบท {latest}" if latest is not None else ""
        )
        self._update_editor_status()

    def _capture_sessions(self):
        for profile_id, workspace in self.workspaces.items():
            self.settings.editor_tabs[profile_id] = (
                workspace.editor.open_paths()
            )
            self.settings.editor_active_tabs[profile_id] = (
                workspace.editor.tabs.currentIndex()
            )
            self.settings.workspace_step_indices[profile_id] = workspace.step_index
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
        self.progress_status.setToolTip(progress_tooltip)

        goal = goal_progress(self.profile)
        if goal:
            completed, target, percentage = goal
            self.goal_status.setFullText(f"เป้าหมาย {completed}/{target} บท · {percentage}%")
            self.goal_status_bar.setValue(percentage)
            self.goal_status_bar.show()
            self.goal_status.setToolTip(f"{self.profile.name}: {completed} จาก {target} บท")
        else:
            self.goal_status.setFullText("ยังไม่ได้ตั้งเป้าหมาย")
            self.goal_status_bar.hide()
            self.goal_status.setToolTip(f"{self.profile.name}: ยังไม่ได้ตั้งเป้าหมาย")

    def closeEvent(self, event):
        for worker in (self._update_check_worker, self._update_download_worker):
            if worker and worker.isRunning():
                worker.requestInterruption()
                if not getattr(self, "_close_after_update_worker", False):
                    self._close_after_update_worker = True
                    signal = getattr(worker, "finished_check", None) or getattr(worker, "finished_download", None)
                    signal.connect(lambda *_: QTimer.singleShot(0, self.close))
                self.statusBar().showMessage("กำลังหยุดงานอัปเดตก่อนปิดโปรแกรม…")
                event.ignore()
                return
        for workspace in self.workspaces.values():
            if not workspace.editor.save_all():
                event.ignore()
                return

        self._capture_sessions()
        self.repo.save_settings(self.settings)
        event.accept()
