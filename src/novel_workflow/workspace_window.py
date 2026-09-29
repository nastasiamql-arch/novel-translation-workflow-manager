from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import QDir, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QFileSystemModel, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QProgressBar, QPushButton, QSizePolicy, QSplitter, QStackedWidget,
    QToolButton, QTreeView, QVBoxLayout, QWidget, QInputDialog,
)

from .models import migrate_legacy_basic_workflow
from .translation_progress import (
    daily_chapter_count, goal_progress, latest_context_chapter,
    sync_profile_context,
)
from .ui import MainWindow as LegacyMainWindow
from .workspace_editor import EditorTabs


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
        self.steps.setSelectionMode(QAbstractItemView.SingleSelection)
        self.steps.setSpacing(2)
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
        self.copy_step_button.clicked.connect(self.owner.copy_step)
        step_header.addWidget(self.copy_step_button)
        sidebar_layout.addLayout(step_header)
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
                step_name = profile.workflow.steps[self.step_index].name if profile and self.step_index < len(profile.workflow.steps) else ""
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
        root_layout.addWidget(self.main_pages, 1)


        self.setCentralWidget(root)

        # Compatibility widgets let the existing settings dialogs and workflow
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
        self.editor_status = QLabel("พร้อมใช้งาน  ·  0 คำ  ·  0 อักขระ")
        self.editor_status.setObjectName("editorStatusBar")
        self.editor_status.setMinimumWidth(360)
        self.editor_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.statusBar().addPermanentWidget(self.editor_status, 1)
        self.progress_status = QLabel("วันนี้ +0 บท")
        self.progress_status.setObjectName("progressStatusBar")
        self.progress_status.setMinimumWidth(140)
        self.progress_status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.statusBar().addPermanentWidget(self.progress_status)
        self.goal_status = QLabel("ยังไม่ได้ตั้งเป้าหมาย")
        self.goal_status.setObjectName("goalStatusBar")
        self.goal_status.setMinimumWidth(150)
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

    def settings_dialog(self):
        self._settings_open = True
        try:
            return super().settings_dialog()
        finally:
            self._settings_open = False
            current_id = self.profile.id if self.profile else None
            self.refresh_profiles(current_id)

    def refresh_profiles(self, pid=None):
        if getattr(self, "_settings_open", False):
            return super().refresh_profiles(pid)

        self.ps_list = self.repo.list_profiles()
        for profile in self.ps_list:
            changed = migrate_legacy_basic_workflow(profile.workflow)
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
        workspace.copy_step_button.setEnabled(bool(self.profile.workflow.steps))
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

        if self.profile:
            for index, step in enumerate(self.profile.workflow.steps):
                self.steps.addItem(f"{index + 1}. {step.name}")

        self.steps.blockSignals(False)
        if self.profile and self.profile.workflow.steps:
            if workspace:
                workspace.copy_step_button.setEnabled(True)
            self.si = max(
                0, min(desired, len(self.profile.workflow.steps) - 1)
            )
            self.steps.setCurrentRow(self.si)
        else:
            self.si = -1
            if workspace:
                workspace.copy_step_button.setEnabled(False)
        self.refresh_files()

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
            workspace.step_index = row
            self.settings.workspace_step_indices[profile_id] = row
        self.si = row
        self.refresh_files()

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
        if not profile or not workspace or not (0 <= workspace.step_index < len(profile.workflow.steps)):
            return
        step = profile.workflow.steps[workspace.step_index]
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


    def copy_step(self):
        super().copy_step()
        if self.profile:
            workspace = self.workspaces.get(self.profile.id)
            if workspace and self.si >= 0:
                workspace.step_index = self.si

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
        self.editor_status.setText(text)

        if not self.profile:
            self.progress_status.setText("วันนี้ +0 บท")
            self.goal_status.setText("ยังไม่ได้ตั้งเป้าหมาย")
            self.goal_status.setToolTip("")
            self.goal_status_bar.hide()
            return

        today = daily_chapter_count(self.profile)
        latest = getattr(self, "_latest_context_chapter", None)
        today_text = f"วันนี้ +{today} บท"
        if latest is not None:
            today_text += f"  ·  ล่าสุด {latest}"
        self.progress_status.setText(today_text)

        goal = goal_progress(self.profile)
        if goal:
            completed, target, percentage = goal
            self.goal_status.setText(f"เป้าหมาย {completed}/{target} บท · {percentage}%")
            self.goal_status_bar.setValue(percentage)
            self.goal_status_bar.show()
            self.goal_status.setToolTip(f"{self.profile.name}: {completed} จาก {target} บท")
        else:
            self.goal_status.setText("ยังไม่ได้ตั้งเป้าหมาย")
            self.goal_status_bar.hide()
            self.goal_status.setToolTip(f"{self.profile.name}: ยังไม่ได้ตั้งเป้าหมาย")

    def closeEvent(self, event):
        for workspace in self.workspaces.values():
            if not workspace.editor.save_all():
                event.ignore()
                return

        self._capture_sessions()
        self.repo.save_settings(self.settings)
        event.accept()
