from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import QDir, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QFileSystemModel, QFrame, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox,
    QProgressBar, QPushButton, QSizePolicy, QSplitter, QStackedWidget,
    QTabBar, QToolButton, QTreeView, QVBoxLayout, QWidget, QInputDialog,
)

from .models import migrate_legacy_basic_workflow
from .translation_progress import (
    daily_chapter_count, goal_progress, latest_context_chapter,
    sync_profile_context,
)
from .ui import MainWindow as LegacyMainWindow
from .workspace_browser import BrowserTabs
from .workspace_editor import EditorTabs


class ProfileWorkspace(QWidget):
    """One independent workspace for one novel profile."""

    def __init__(self, owner: "MainWindow", profile):
        super().__init__(owner)
        self.owner = owner
        self.profile_id = profile.id
        self.step_index = 0

        self.mode_tabs = QTabBar()
        self.mode_tabs.setObjectName("workspaceModeTabs")
        self.mode_tabs.setExpanding(False)
        for label in ("งานแปล", "ไฟล์", "Browser", "ความคืบหน้า"):
            self.mode_tabs.addTab(label)
        self.mode_tabs.currentChanged.connect(self.set_mode)

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

        self.explorer_panel = QFrame()
        self.explorer_panel.setObjectName("explorerPanel")
        explorer_layout = QVBoxLayout(self.explorer_panel)
        explorer_layout.setContentsMargins(8, 8, 8, 8)
        explorer_layout.setSpacing(6)
        heading = QLabel("EXPLORER")
        heading.setObjectName("sectionHeading")
        explorer_layout.addWidget(heading)
        explorer_layout.addWidget(self.file_tree, 1)

        actions = QGridLayout()
        for index, (label, callback) in enumerate((
            ("ไฟล์ใหม่", self.new_file),
            ("โฟลเดอร์ใหม่", self.new_folder),
            ("เปลี่ยนชื่อ", self.rename_selected),
            ("ลบ", self.delete_selected),
        )):
            button = QPushButton(label)
            button.clicked.connect(callback)
            actions.addWidget(button, index // 2, index % 2)
        explorer_layout.addLayout(actions)

        self.editor = EditorTabs()
        self.editor_panel = QFrame()
        self.editor_panel.setObjectName("editorPanel")
        editor_layout = QVBoxLayout(self.editor_panel)
        editor_layout.setContentsMargins(8, 8, 8, 8)
        editor_layout.setSpacing(6)
        editor_heading = QLabel("EDITOR")
        editor_heading.setObjectName("sectionHeading")
        editor_layout.addWidget(editor_heading)
        editor_layout.addWidget(self.editor, 1)

        self.files_splitter = QSplitter()
        self.files_splitter.setChildrenCollapsible(False)
        self.files_splitter.addWidget(self.explorer_panel)
        self.files_splitter.addWidget(self.editor_panel)
        self.files_splitter.setStretchFactor(0, 1)
        self.files_splitter.setStretchFactor(1, 4)
        self.files_splitter.setSizes([280, 1050])

        self.files_page = QWidget()
        files_page_layout = QVBoxLayout(self.files_page)
        files_page_layout.setContentsMargins(0, 0, 0, 0)
        files_page_layout.addWidget(self.files_splitter)

        self.browser = BrowserTabs(storage_root=self.owner.repo.root / "browser")
        self.browser_page = QWidget()
        browser_page_layout = QVBoxLayout(self.browser_page)
        browser_page_layout.setContentsMargins(0, 0, 0, 0)
        browser_page_layout.addWidget(self.browser)

        self.steps = QListWidget()
        self.steps.setSelectionMode(QAbstractItemView.SingleSelection)
        self.files = QListWidget()

        step_box = QGroupBox("ขั้นตอนการแปล")
        step_layout = QVBoxLayout(step_box)
        step_layout.addWidget(self.steps)

        files_box = QGroupBox("ไฟล์ของขั้นตอนปัจจุบัน")
        files_layout = QVBoxLayout(files_box)
        files_layout.addWidget(self.files)

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

        workflow_splitter = QSplitter()
        workflow_splitter.setChildrenCollapsible(False)
        workflow_splitter.addWidget(step_box)
        workflow_splitter.addWidget(files_box)
        workflow_splitter.addWidget(self.goal_panel)
        workflow_splitter.setStretchFactor(0, 1)
        workflow_splitter.setStretchFactor(1, 2)
        workflow_splitter.setStretchFactor(2, 1)
        workflow_splitter.setSizes([320, 650, 360])

        self.workflow_page = QWidget()
        workflow_layout = QVBoxLayout(self.workflow_page)
        workflow_layout.setContentsMargins(0, 0, 0, 0)
        workflow_layout.addWidget(workflow_splitter)

        self.progress_today = QLabel("วันนี้ +0 บท")
        self.progress_today.setObjectName("metricValue")
        self.progress_latest = QLabel("บทล่าสุด —")
        self.progress_latest.setObjectName("metricLabel")
        self.progress_goal = QLabel("ยังไม่ได้ตั้งเป้าหมาย")
        self.progress_goal.setObjectName("bodyLabel")

        dashboard_button = QPushButton("เปิดแดชบอร์ดความคืบหน้า")
        dashboard_button.clicked.connect(owner.translation_dashboard)

        self.progress_page = QWidget()
        progress_layout = QVBoxLayout(self.progress_page)
        progress_layout.setContentsMargins(24, 24, 24, 24)
        progress_layout.addWidget(QLabel("ความคืบหน้าของเรื่องนี้"))
        progress_layout.addWidget(self.progress_today)
        progress_layout.addWidget(self.progress_latest)
        progress_layout.addWidget(self.progress_goal)
        progress_layout.addWidget(dashboard_button)
        progress_layout.addStretch(1)

        self.content_stack = QStackedWidget()
        self.content_stack.addWidget(self.workflow_page)
        self.content_stack.addWidget(self.files_page)
        self.content_stack.addWidget(self.browser_page)
        self.content_stack.addWidget(self.progress_page)

        mode_strip = QFrame()
        mode_strip.setObjectName("modeStrip")
        mode_layout = QHBoxLayout(mode_strip)
        mode_layout.setContentsMargins(8, 5, 8, 5)
        mode_layout.setSpacing(0)
        mode_layout.addStretch(1)
        mode_layout.addWidget(self.mode_tabs)
        mode_layout.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(mode_strip)
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

    def set_mode(self, index):
        if 0 <= index < self.content_stack.count():
            self.content_stack.setCurrentIndex(index)

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
            self.editor.open_file(path)

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
    """Novel tabs + embedded file explorer/editor/browser workspace."""

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
            ("เปิดรายการของเรื่อง", self.launch_profile),
            ("กลุ่มนิยาย", self.groups_dialog),
            ("นำเข้าข้อมูลเดิม", self.import_launcher_config),
            ("สถิติ", self.translation_dashboard),
            ("ตั้งค่า", self.settings_dialog),
        ):
            action = QAction(label, self)
            action.triggered.connect(callback)
            bar.addAction(action)

        root = QWidget()
        root.setObjectName("appShell")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(10, 10, 10, 8)
        root_layout.setSpacing(8)

        story_strip = QFrame()
        story_strip.setObjectName("storyStrip")
        story_row = QHBoxLayout(story_strip)
        story_row.setContentsMargins(8, 5, 8, 5)
        story_row.setSpacing(4)
        self.story_tabs = QTabBar()
        self.story_tabs.setObjectName("storyTabs")
        self.story_tabs.setExpanding(False)
        self.story_tabs.setUsesScrollButtons(True)
        self.story_tabs.setDrawBase(False)
        self.story_tabs.currentChanged.connect(self.select_profile)
        story_row.addWidget(self.story_tabs, 1)

        add_story = QToolButton()
        add_story.setText("+")
        add_story.setToolTip("เพิ่มนิยาย")
        add_story.clicked.connect(self.new_profile)
        story_row.addWidget(add_story)
        root_layout.addWidget(story_strip)

        self.workspace_stack = QStackedWidget()
        self.empty_page = QLabel("ยังไม่มีนิยาย\nกด + เพื่อเพิ่มนิยาย")
        self.empty_page.setAlignment(Qt.AlignCenter)
        self.empty_page.setObjectName("mutedLabel")
        self.workspace_stack.addWidget(self.empty_page)
        root_layout.addWidget(self.workspace_stack, 1)

        self.copy_button = QPushButton("⧉  COPY STEP")
        self.copy_button.setObjectName("primaryButton")
        self.copy_button.setMinimumHeight(40)
        self.copy_button.setMinimumWidth(220)
        self.copy_button.setMaximumWidth(320)
        self.copy_button.clicked.connect(self.copy_step)

        bottom_bar = QFrame()
        bottom_bar.setObjectName("bottomBar")
        bottom_layout = QHBoxLayout(bottom_bar)
        bottom_layout.setContentsMargins(10, 7, 10, 7)
        bottom_layout.addStretch(1)
        bottom_layout.addWidget(self.copy_button)
        bottom_layout.addStretch(1)
        root_layout.addWidget(bottom_bar)

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
        self.shortcut("Ctrl+Shift+C", self.copy_step)
        self.shortcut("Ctrl+P", self.preview)
        self.shortcut("Ctrl+R", self.refresh)
        self.shortcut("Ctrl+S", self.save_active_document)

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

        self.story_tabs.blockSignals(True)
        while self.story_tabs.count():
            self.story_tabs.removeTab(0)

        placeholder = Path(__file__).resolve().parent / "resources" / "novelworkflow.png"
        for profile in self.ps_list:
            icon = QIcon(str(placeholder)) if placeholder.is_file() else QIcon()
            if profile.cover_image_path:
                try:
                    candidate = self.repo.resolve_project_path(
                        profile.id, profile.cover_image_path
                    )
                    if candidate.is_file():
                        icon = QIcon(str(candidate))
                except ValueError:
                    pass
            self.story_tabs.addTab(icon, profile.name)
            self.story_tabs.setTabToolTip(
                self.story_tabs.count() - 1, profile.name
            )
        self.story_tabs.blockSignals(False)

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
            self.copy_button.setEnabled(False)

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

            workspace.browser.restore(
                self.settings.browser_tabs.get(profile.id, ["about:blank"]),
                self.settings.browser_active_tabs.get(profile.id, 0),
            )
            workspace.editor.restore_paths(
                self.settings.editor_tabs.get(profile.id, []),
                self.settings.editor_active_tabs.get(profile.id, 0),
            )
        else:
            workspace.configure(profile)
        return workspace

    def select_profile(self, index):
        if getattr(self, "_settings_open", False):
            return super().select_profile(index)
        if index < 0 or index >= len(getattr(self, "ps_list", [])):
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

        self.story_tabs.blockSignals(True)
        self.story_tabs.setCurrentIndex(index)
        self.story_tabs.blockSignals(False)

        self.workspace_stack.setCurrentWidget(workspace)
        self.copy_button.setEnabled(bool(self.profile.workflow.steps))
        self.refresh_steps()
        if self.si >= 0:
            self.steps.setCurrentRow(self.si)
        self.refresh_goal_indicator()
        self._update_progress_page(workspace)
        self.statusBar().showMessage(
            f"กำลังทำงาน: {self.profile.name}", 2500
        )

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
            self.si = max(
                0, min(desired, len(self.profile.workflow.steps) - 1)
            )
            self.steps.setCurrentRow(self.si)
        else:
            self.si = -1
        self.refresh_files()

    def _step_changed(self, profile_id, row):
        if not self.profile or self.profile.id != profile_id or row < 0:
            return
        workspace = self.workspaces.get(profile_id)
        if workspace:
            workspace.step_index = row
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

    def copy_step(self):
        super().copy_step()
        if self.profile:
            workspace = self.workspaces.get(self.profile.id)
            if workspace and self.si >= 0:
                workspace.step_index = self.si

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
                if entry.kind == "website":
                    workspace.browser.open_url(
                        entry.target, title=entry.label or None, new_tab=True
                    )
                    succeeded += 1
                elif entry.kind == "file":
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

        today = daily_chapter_count(self.profile)
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

        goal = goal_progress(self.profile)
        workspace.progress_today.setText(f"วันนี้ +{today} บท")
        workspace.progress_latest.setText(
            f"บทล่าสุด {latest}" if latest is not None else "บทล่าสุด —"
        )
        if goal:
            completed, target, percentage = goal
            workspace.progress_goal.setText(
                f"เป้าหมาย {completed}/{target} บท · {percentage}%"
            )
        else:
            workspace.progress_goal.setText("ยังไม่ได้ตั้งเป้าหมาย")

    def _capture_sessions(self):
        for profile_id, workspace in self.workspaces.items():
            self.settings.browser_tabs[profile_id] = workspace.browser.urls()
            self.settings.browser_active_tabs[profile_id] = (
                workspace.browser.tabs.currentIndex()
            )
            self.settings.editor_tabs[profile_id] = (
                workspace.editor.open_paths()
            )
            self.settings.editor_active_tabs[profile_id] = (
                workspace.editor.tabs.currentIndex()
            )

    def save(self):
        self._capture_sessions()
        super().save()

    def closeEvent(self, event):
        for workspace in self.workspaces.values():
            if not workspace.editor.save_all():
                event.ignore()
                return

        self._capture_sessions()
        self.repo.save_settings(self.settings)
        event.accept()
