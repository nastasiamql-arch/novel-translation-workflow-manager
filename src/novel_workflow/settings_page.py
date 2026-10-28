"""Settings UI construction, reusing the shell's existing management actions."""
from PySide6.QtCore import Qt, QEvent, QTimer
from PySide6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QFrame, QLabel,
    QGridLayout, QPushButton, QScrollArea, QListWidget, QAbstractItemView, QSpinBox,
    QLineEdit, QSizePolicy, QComboBox, QCheckBox, QLayout, QGroupBox)
from .shell_components import ElidingLabel


class SettingsSidebar(QFrame):
    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._activate_layout)

    def _activate_layout(self):
        if self.layout():
            self.layout().activate()


class AttachmentList(QListWidget):
    """Show up to eight whole rows; let the surrounding page scroll."""
    def __init__(self):
        super().__init__()
        self.setWordWrap(False)
        self.setTextElideMode(Qt.ElideRight)
        self._height_timer = QTimer(self)
        self._height_timer.setSingleShot(True)
        self._height_timer.timeout.connect(self._fit_rows)
        for signal in (self.model().rowsInserted, self.model().rowsRemoved,
                       self.model().modelReset, self.model().dataChanged):
            signal.connect(self._schedule_fit)
        self._schedule_fit()

    def _schedule_fit(self, *_args):
        self._height_timer.start(0)

    def _fit_rows(self):
        self.ensurePolished()
        rows = min(8, max(2, self.count()))
        row_height = max([self.fontMetrics().height() + 12] +
                         [self.sizeHintForRow(i) for i in range(self.count())])
        # Leave enough room for the platform style's actual item margins and
        # viewport frame so the final requested row is not clipped.
        height = rows * (row_height + 2 * self.spacing()) + 2 * self.frameWidth() + 20
        self.setMinimumHeight(height)
        self.setMaximumHeight(height)
        self.updateGeometry()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.FontChange, QEvent.StyleChange) and hasattr(self, '_height_timer'):
            self._schedule_fit()


class SettingsPage(QWidget):
    @classmethod
    def build(cls, owner, profile_list_type):
        original_lists = (owner.profiles, owner.steps, owner.files)
        previous_profile_id = owner.profile.id if owner.profile else None
        active_step = owner.step()
        active_step_id = active_step.id if active_step else None
        active_workspace = owner.workspaces.get(previous_profile_id) if previous_profile_id else None
        active_vocabulary_mode = bool(active_workspace and active_workspace.vocabulary_mode)
        page = cls(owner)
        root = QHBoxLayout(page)
        root.setContentsMargins(12, 8, 12, 8)
        root.setSpacing(12)

        owner.profiles = profile_list_type()
        owner.profiles.orderChanged.connect(owner._persist_profile_order)
        owner.profiles.setWordWrap(True)
        owner.profiles.setTextElideMode(Qt.ElideNone)
        owner.profiles.setSpacing(6)
        owner.profiles.setCursor(Qt.ArrowCursor)
        owner.profiles.setAccessibleName("รายการนิยาย")
        owner.profiles.setObjectName("settingsNovelList")
        owner.profiles.setMinimumHeight(0)
        owner.profiles.setMinimumSize(0, 0)
        owner.profiles.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
        owner.profiles.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        def select_profile_from_sidebar(index):
            owner.select_profile(index)
            page.select_category("Novel")
        owner.profiles.selectionCommitted.connect(select_profile_from_sidebar)
        owner.steps = AttachmentList()
        owner.steps.setSpacing(1)
        owner.steps.setCursor(Qt.PointingHandCursor)
        owner.steps.setAccessibleName("ขั้นตอนงาน")
        owner.steps.setSelectionMode(QAbstractItemView.SingleSelection)
        owner.steps.currentRowChanged.connect(owner.select_step)
        owner.files = AttachmentList()
        owner.files.setSelectionMode(QAbstractItemView.ExtendedSelection)
        owner.files.setSpacing(1)
        owner.files.setCursor(Qt.PointingHandCursor)
        owner.files.setAccessibleName("ไฟล์ของขั้นตอน")
        owner.files.itemChanged.connect(owner.toggle_file)

        profile_panel = QFrame()
        profile_panel.setObjectName("settingsCard")
        profile_layout = QVBoxLayout(profile_panel)
        profile_layout.setContentsMargins(8, 8, 8, 8)
        profile_layout.setSpacing(4)
        profile_layout.setSizeConstraint(QLayout.SetNoConstraint)
        profile_layout.addWidget(QLabel("นิยายของฉัน"))
        profile_layout.addWidget(owner.profiles, 1)
        profile_actions = QGridLayout()
        profile_actions.setContentsMargins(0, 0, 0, 0)
        profile_actions.setHorizontalSpacing(6)
        profile_actions.setVerticalSpacing(4)
        for index, (label, callback) in enumerate((
            ("＋ เพิ่มนิยาย", owner.new_profile), ("ทำสำเนา", owner.duplicate_profile),
            ("เลื่อนขึ้น", lambda: owner.move_profile(-1)), ("เลื่อนลง", lambda: owner.move_profile(1)),
        )):
            button = QPushButton(label)
            button.clicked.connect(callback)
            profile_actions.addWidget(button, index // 2, index % 2)
        profile_layout.addLayout(profile_actions)
        profile_panel.setMinimumWidth(0)
        profile_panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        sidebar = SettingsSidebar()
        sidebar.setObjectName("preferencesSidebar")
        sidebar.setFixedWidth(310)
        sidebar.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSizeConstraint(QLayout.SetNoConstraint)
        categories = AttachmentList()
        categories.setObjectName("preferencesCategory")
        categories.setAccessibleName("หมวดการตั้งค่า")
        categories.addItems(["ข้อมูลนิยาย", "ไฟล์และโฟลเดอร์", "ขั้นตอนการแปล", "แท็บทำงาน",
                             "ส่งออก TXT", "ทั่วไป", "อัปเดตโปรแกรม"])
        categories.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        categories.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        categories.setFocusPolicy(Qt.StrongFocus)
        categories.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        sidebar_layout.addWidget(categories)
        owner.profiles.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        profile_panel.setMinimumWidth(0)
        sidebar_layout.addWidget(profile_panel, 1)
        root.addWidget(sidebar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        detail_page = QWidget()
        detail = QVBoxLayout(detail_page)
        detail.setContentsMargins(4, 4, 4, 4)
        owner.settings_profile_heading = ElidingLabel("เลือกนิยายเพื่อจัดการการตั้งค่า")
        owner.settings_profile_heading.setObjectName("sectionHeading")
        detail.addWidget(owner.settings_profile_heading)
        info_frame = QFrame()
        info_frame.setObjectName("settingsCard")
        info_layout = QHBoxLayout(info_frame)
        owner.settings_context_hint = QLabel("ยังไม่ได้เลือกไฟล์ Context")
        owner.settings_context_hint.setObjectName("mutedLabel")
        info_layout.addWidget(owner.settings_context_hint, 1)
        info_layout.addWidget(QLabel("เป้าหมายบท/รอบ"))
        owner.settings_goal_target = QSpinBox()
        owner.settings_goal_target.setRange(0, 100000)
        owner.settings_goal_target.setSpecialValueText("ยังไม่ตั้ง")
        info_layout.addWidget(owner.settings_goal_target)
        save_goal = QPushButton("บันทึกเป้าหมาย")
        save_goal.clicked.connect(owner.save_settings_goal_target)
        info_layout.addWidget(save_goal)
        detail.addWidget(info_frame)

        story_actions = QGridLayout()
        for index, (label, callback) in enumerate((
            ("เปลี่ยนชื่อ", owner.rename_profile), ("ตั้งรูปปก", owner.set_cover),
            ("เอารูปปกออก", owner.remove_cover), ("เลือก Context", owner.set_context_file),
        )):
            button = QPushButton(label)
            button.clicked.connect(callback)
            story_actions.addWidget(button, index // 2, index % 2)
        story_frame = QWidget()
        story_frame.setLayout(story_actions)
        detail.addWidget(story_frame)

        advanced_frame = QGroupBox("จัดการขั้นสูง")
        advanced_frame.setCheckable(True)
        advanced_frame.setChecked(False)
        advanced_layout = QVBoxLayout(advanced_frame)
        delete_profile = QPushButton("ลบนิยาย…")
        delete_profile.clicked.connect(owner.delete_profile)
        advanced_layout.addWidget(delete_profile)
        detail.addWidget(advanced_frame)

        launcher_frame = QFrame()
        launcher_frame.setObjectName("settingsCard")
        launcher_layout = QVBoxLayout(launcher_frame)
        launcher_layout.addWidget(QLabel("โฟลเดอร์และรายการที่เปิดพร้อมเรื่องนี้"))
        folder_row = QHBoxLayout()
        owner.settings_main_folder = QLineEdit()
        owner.settings_main_folder.setPlaceholderText("โฟลเดอร์หลักของนิยาย (ถ้ามี)")
        folder_row.addWidget(owner.settings_main_folder, 1)
        choose_folder = QPushButton("เลือกโฟลเดอร์")
        choose_folder.clicked.connect(owner.choose_settings_main_folder)
        folder_row.addWidget(choose_folder)
        smart_files = QPushButton("ตั้งค่าไฟล์ทั้งหมด")
        smart_files.setObjectName("smartFolderSetup")
        smart_files.setToolTip("สแกนโฟลเดอร์และตรวจสอบไฟล์ที่แนะนำก่อนบันทึก")
        smart_files.clicked.connect(owner.configure_smart_files)
        folder_row.addWidget(smart_files)
        save_folder = QPushButton("บันทึกโฟลเดอร์")
        save_folder.clicked.connect(owner.save_settings_main_folder)
        folder_row.addWidget(save_folder)
        launcher_layout.addLayout(folder_row)
        owner.settings_launch_targets = QListWidget()
        owner.settings_launch_targets.setSelectionMode(QAbstractItemView.ExtendedSelection)
        owner.settings_launch_targets.setWordWrap(True)
        owner.settings_launch_targets.setTextElideMode(Qt.ElideNone)
        target_font = owner.settings_launch_targets.font()
        target_font.setPointSize(max(11, target_font.pointSize()))
        owner.settings_launch_targets.setFont(target_font)
        owner.settings_launch_targets.setMinimumHeight(260)
        owner.settings_launch_targets.itemChanged.connect(owner.save_settings_launch_target_state)
        launcher_layout.addWidget(owner.settings_launch_targets)
        launch_actions = QHBoxLayout()
        for label, kind in (("＋ App", "application"), ("＋ ไฟล์", "file"),
                            ("＋ โฟลเดอร์", "folder"), ("＋ Website", "website")):
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, value=kind: owner.add_settings_launch_target(value))
            launch_actions.addWidget(button)
        remove_target = QPushButton("เอารายการที่เลือกออก")
        remove_target.clicked.connect(owner.remove_settings_launch_target)
        launch_actions.addWidget(remove_target)
        launcher_layout.addLayout(launch_actions)
        detail.addWidget(launcher_frame)

        def workflow_step_action(callback):
            def run(*_args):
                if owner._management_vocabulary_mode:
                    owner.statusBar().showMessage(
                        "หาศัพท์แยกจากขั้นตอนแปล จัดการไฟล์ได้จากรายการไฟล์ด้านขวา", 3500
                    )
                    return
                callback()
            return run
        workflow_frame = QFrame()
        workflow_frame.setObjectName("settingsCard")
        workflow_layout = QVBoxLayout(workflow_frame)
        history_row = QHBoxLayout()
        history_row.addWidget(QLabel('Novel Polish'))
        owner.settings_history_step = QComboBox()
        owner.settings_history_step.setAccessibleName('ขั้นตอนที่เปิดใช้ Novel Polish')
        owner.settings_history_step.currentIndexChanged.connect(owner.save_settings_history_step)
        history_row.addWidget(owner.settings_history_step, 1)
        workflow_layout.addLayout(history_row)
        advanced_options = QGroupBox("ตัวเลือกขั้นสูง · ตรวจเลขบทต้นฉบับ")
        advanced_options.setCheckable(True)
        advanced_options.setChecked(False)
        advanced_body = QWidget()
        advanced_body.setVisible(False)
        advanced_body_layout = QVBoxLayout(advanced_body)
        advanced_body_layout.setContentsMargins(0, 0, 0, 0)
        owner.settings_auto_review_enabled = QCheckBox("เปิดระบบตรวจเลขบทต้นฉบับ (แยกแต่ละนิยาย)")
        owner.settings_auto_review_enabled.setObjectName("autoChapterReviewEnabled")
        owner.settings_auto_review_enabled.setToolTip(
            "เมื่อบันทึกไฟล์ต้นฉบับที่เปิดอยู่ จะตรวจเลขหัวบทอัตโนมัติและแจ้งปัญหา"
        )
        advanced_body_layout.addWidget(owner.settings_auto_review_enabled)
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("เมื่อเปิดใช้"))
        owner.settings_auto_chapter_number_mode = QComboBox()
        owner.settings_auto_chapter_number_mode.setObjectName("autoChapterNumberMode")
        owner.settings_auto_chapter_number_mode.addItem("ตรวจและแก้ด้วยตัวเอง · เตือนหลังวางบท", "check")
        owner.settings_auto_chapter_number_mode.addItem("ตรวจและแก้เลขบทอัตโนมัติ · วางต่อท้ายทีละบท", "fix")
        mode_row.addWidget(owner.settings_auto_chapter_number_mode, 1)
        advanced_body_layout.addLayout(mode_row)
        auto_review_hint = QLabel(
            "หลังวางต้นฉบับและ Auto Save ระบบอ่านบทล่าสุดจาก Translator ของนิยายนี้ (+1) "
            "เลือกได้ 2 โหมด: ทำเอง (มีตัวเตือนค้างจนกดยืนยันว่าตรวจแล้ว) "
            "หรือแก้อัตโนมัติ (แก้เฉพาะบทที่เพิ่งต่อท้าย แม้วางทีละบท) "
            "ระบบอ่านเลขเริ่มจาก Translator รักษาตัวเลขจีน ชื่อบทและข้อความทุกบรรทัด "
            "ตรวจสอบประวัติการแก้เดิมก่อนเปลี่ยนเลขบทใหม่ "
            "หากไม่มีหลักฐานว่าบทเก่าแก้แล้วหรือพบเลขกระโดดจริง จะเตือนให้ตรวจเอง "
            "ไม่เกี่ยวกับ Export/Backup หรือการตรวจคำแปลด้วย AI"
        )
        auto_review_hint.setObjectName("mutedLabel")
        auto_review_hint.setWordWrap(True)
        advanced_body_layout.addWidget(auto_review_hint)
        advanced_options.toggled.connect(advanced_body.setVisible)
        advanced_outer = QVBoxLayout(advanced_options)
        advanced_outer.addWidget(advanced_body)
        workflow_layout.addWidget(advanced_options)
        owner.settings_auto_review_enabled.toggled.connect(owner.save_settings_auto_chapter_review)
        owner.settings_auto_chapter_number_mode.currentIndexChanged.connect(owner.save_settings_auto_chapter_review)
        workflow_columns = QHBoxLayout()
        steps_panel = QWidget()
        steps_column = QVBoxLayout(steps_panel)
        steps_column.setContentsMargins(0, 0, 0, 0)
        steps_column.addWidget(QLabel("เลือกขั้นตอน"))
        owner.steps.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        steps_column.addWidget(owner.steps, 1)
        step_actions_panel = QWidget()
        step_actions = QGridLayout(step_actions_panel)
        step_actions.setContentsMargins(0, 0, 0, 0)
        for index, (label, callback) in enumerate((
            ("เพิ่มขั้นตอน", owner.add_step),
            ("เปลี่ยนชื่อ", workflow_step_action(owner.rename_step)),
            ("ทำสำเนา", workflow_step_action(owner.duplicate_step)),
            ("ลบขั้นตอน", workflow_step_action(owner.delete_step)),
            ("ขึ้น", workflow_step_action(lambda: owner.move_step(-1))),
            ("ลง", workflow_step_action(lambda: owner.move_step(1))),
            ("บันทึกแม่แบบ", workflow_step_action(owner.save_template)),
        )):
            button = QPushButton(label)
            button.clicked.connect(callback)
            step_actions.addWidget(button, index // 2, index % 2)
        steps_column.addSpacing(12)
        steps_column.addWidget(step_actions_panel)
        steps_column.addStretch(1)
        workflow_columns.addWidget(steps_panel, 1)

        files_panel = QWidget()
        files_column = QVBoxLayout(files_panel)
        files_column.setContentsMargins(0, 0, 0, 0)
        files_header = QHBoxLayout()
        files_header.addWidget(QLabel("ไฟล์แนบของขั้นตอนที่เลือก"), 1)
        owner.settings_step_hint = QLabel("เลือกขั้นตอนเพื่อจัดการไฟล์")
        owner.settings_step_hint.setObjectName("mutedLabel")
        files_header.addWidget(owner.settings_step_hint)
        files_column.addLayout(files_header)
        owner.files.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        files_column.addWidget(owner.files, 1)
        file_actions = QGridLayout()
        for index, (label, callback) in enumerate((
            ("＋ เพิ่มหลายไฟล์", owner.add_file), ("ไฟล์บทปัจจุบัน", owner.add_dynamic),
            ("เอาออก", owner.remove_file), ("ขึ้น", lambda: owner.move_file(-1)),
            ("ลง", lambda: owner.move_file(1)), ("เปลี่ยนชื่อแสดง", owner.rename_file_label),
            ("จัดการไฟล์", owner.file_manager), ("ดูตัวอย่าง", owner.preview),
        )):
            button = QPushButton(label)
            button.clicked.connect(callback)
            file_actions.addWidget(button, index // 2, index % 2)
        files_column.addSpacing(12)
        files_column.addLayout(file_actions)
        files_column.addStretch(1)
        workflow_columns.addWidget(files_panel, 2)
        workflow_layout.addLayout(workflow_columns)
        detail.addWidget(workflow_frame, 1)

        work_frame = QFrame()
        work_frame.setObjectName("settingsCard")
        work_layout = QVBoxLayout(work_frame)
        work_layout.setContentsMargins(16, 16, 16, 16)
        work_header = QHBoxLayout()
        work_header.addWidget(QLabel("แท็บทำงาน · ไฟล์สำหรับเปิดทำงาน"), 1)
        owner.working_files_hint = QLabel("เลือกไฟล์ที่ต้องการเปิดเป็นแท็บ โดยไม่ผูกกับขั้นตอน")
        owner.working_files_hint.setObjectName("mutedLabel")
        work_header.addWidget(owner.working_files_hint)
        work_layout.addLayout(work_header)
        owner.working_files = QListWidget()
        owner.working_files.setSelectionMode(QAbstractItemView.ExtendedSelection)
        owner.working_files.itemDoubleClicked.connect(owner.open_selected_working_file)
        work_layout.addWidget(owner.working_files)
        owner.auto_open_working_tabs = QCheckBox("เปิดไฟล์ทำงานเป็นแท็บเมื่อเปิดนิยายนี้")
        owner.auto_open_working_tabs.setObjectName("autoOpenWorkingTabs")
        owner.auto_open_working_tabs.setChecked(bool(owner.profile and owner.profile.open_working_tabs_on_open))
        owner.auto_open_working_tabs.toggled.connect(owner.save_working_tabs_open_setting)
        work_layout.addWidget(owner.auto_open_working_tabs)
        work_actions = QHBoxLayout()
        for label, callback, name in (
            ("＋ เลือกหลายไฟล์", owner.add_working_files, "addWorkingFiles"),
            ("เปิดไฟล์ที่เลือก", owner.open_selected_working_file, "openWorkingFiles"),
            ("↑", lambda: owner.move_working_file(-1), "moveWorkingFileUp"),
            ("↓", lambda: owner.move_working_file(1), "moveWorkingFileDown"),
            ("เอาออกจากรายการ", owner.remove_working_file, "removeWorkingFiles"),
        ):
            button = QPushButton(label)
            button.setObjectName(name)
            button.clicked.connect(callback)
            work_actions.addWidget(button)
        work_layout.addLayout(work_actions)
        detail.addWidget(work_frame)

        general = QFrame()
        general.setObjectName("settingsCard")
        general_layout = QVBoxLayout(general)
        general_layout.addWidget(QLabel("ทั่วไป · รูปลักษณ์และการคัดลอก"))
        appearance = QComboBox()
        for title, value in (("โหมดสว่าง", "Light"), ("โหมดมืด", "Dark"), ("ตามระบบ", "System")):
            appearance.addItem(title, value)
        appearance.setObjectName("preferencesAppearance")
        appearance.setCurrentIndex(max(0, appearance.findData(owner.settings.appearance)))
        general_layout.addWidget(appearance)
        zip_mode = QCheckBox("คัดลอกขั้นตอน Workflow เป็น ZIP")
        zip_mode.setObjectName("copyFilesAsZip")
        zip_mode.setChecked(owner.settings.copy_files_as_zip)
        general_layout.addWidget(zip_mode)
        zip_hint = QLabel("ใช้กับปุ่มขั้นตอนแปลเท่านั้น · ZIP ของหน้า Novel Polish ตั้งค่าแยกในหน้านั้น")
        zip_hint.setWordWrap(True)
        general_layout.addWidget(zip_hint)
        general_layout.addWidget(QLabel("ตัวคั่นเนื้อหา · ใช้ {FILE_NAME} แทนชื่อไฟล์"))
        separator = QLineEdit(owner.settings.separator)
        separator.setObjectName("assemblySeparator")
        general_layout.addWidget(separator)
        checks = [(zip_mode, "copy_files_as_zip")]
        for label, attr in (("แสดงชื่อไฟล์ในเนื้อหาที่ประกอบ", "show_filename_heading"),
                            ("ยืนยันก่อนลบไฟล์", "confirm_before_deleting"),
                            ("เปิดนิยายล่าสุดเมื่อเริ่มโปรแกรม", "open_last_profile")):
            check = QCheckBox(label)
            check.setObjectName(attr)
            check.setChecked(getattr(owner.settings, attr))
            general_layout.addWidget(check)
            checks.append((check, attr))
        def save_general(*_args):
            theme_changed = owner.settings.appearance != appearance.currentData()
            zip_changed = owner.settings.copy_files_as_zip != zip_mode.isChecked()
            owner.settings.appearance = appearance.currentData()
            owner.settings.separator = separator.text()
            for check, attr in checks:
                setattr(owner.settings, attr, check.isChecked())
            owner.repo.save_settings(owner.settings)
            if zip_changed:
                owner.update_copy_mode_labels()
            if theme_changed:
                owner.apply_theme()
            owner.statusBar().showMessage("บันทึกการตั้งค่าแล้ว", 2000)
        appearance.currentTextChanged.connect(save_general)
        separator.editingFinished.connect(save_general)
        for check, _attr in checks:
            check.toggled.connect(save_general)
        detail.addWidget(general)

        export_preferences = QFrame()
        export_preferences.setObjectName("settingsCard")
        export_layout = QVBoxLayout(export_preferences)
        export_layout.addWidget(QLabel("ส่งออก TXT · ตั้งค่าแยกตามนิยาย"))
        export_layout.addWidget(QLabel("Prefix, เลขไฟล์, ช่วงเลข, ปลายทาง, Draft และประวัติ จำแยกตามเรื่อง"))
        open_export = QPushButton("เปิด TXT Export ของเรื่องนี้")
        open_export.setObjectName("openNovelTxtExport")
        def show_export():
            profile_id = owner.profile.id if owner.profile else None
            owner.navigate("workspace")
            workspace = owner.workspaces.get(profile_id)
            if workspace:
                workspace.editor.tabs.setCurrentWidget(workspace.editor.export_tab)
        open_export.clicked.connect(show_export)
        export_layout.addWidget(open_export)
        detail.addWidget(export_preferences)

        updates = QFrame()
        updates.setObjectName("settingsCard")
        updates_layout = QVBoxLayout(updates)
        updates_layout.addWidget(QLabel("อัปเดตโปรแกรม · GitHub Releases"))
        update = QPushButton("ตรวจสอบอัปเดตโปรแกรม")
        update.clicked.connect(lambda: owner.check_updates(manual=True))
        updates_layout.addWidget(update)
        detail.addWidget(updates)
        sections = {
            "Novel Info": [info_frame, story_frame, advanced_frame],
            "Files and Folders": [launcher_frame],
            "Workflow": [workflow_frame],
            "Working Tabs": [work_frame],
            "TXT Export": [export_preferences],
            "General": [general],
            "Program Updates": [updates],
        }
        category_labels = {"Novel Info": "ข้อมูลนิยาย", "Files and Folders": "ไฟล์และโฟลเดอร์",
            "Workflow": "ขั้นตอนการแปล", "Working Tabs": "แท็บทำงาน", "TXT Export": "ส่งออก TXT",
            "General": "ทั่วไป", "Program Updates": "อัปเดตโปรแกรม"}
        category_ids = {value: key for key, value in category_labels.items()}
        def select_category(name):
            name = category_ids.get(name, name)
            # Keep old entry points working while presenting all story settings together.
            if name == "Novel":
                name = "Novel Info"
            shown = sections[name]
            for widget in {w for group in sections.values() for w in group}:
                widget.setVisible(widget in shown)
            profile_panel.setVisible(name not in ("General", "Program Updates"))
            owner.settings_profile_heading.setVisible(name not in ("General", "Program Updates"))
            files_panel.setVisible(name == "Workflow")
            step_actions_panel.setVisible(name == "Workflow")
        def select_named_category(name):
            if name == "Novel":
                name = "Novel Info"
            elif name == "Workflow Files":
                # Preserve the old automation/test entry point for workflow attachments.
                name = "Workflow"
            for index in range(categories.count()):
                if categories.item(index).text() == category_labels.get(name, name):
                    categories.setCurrentRow(index)
                    return
        page.select_category = select_named_category
        categories.currentTextChanged.connect(select_category)
        initial_category = "Novel Info" if owner.profile else "General"
        initial_index = next(i for i in range(categories.count()) if categories.item(i).text() == category_labels[initial_category])
        categories.setCurrentRow(initial_index)
        select_category(initial_category)
        detail.addStretch(1)
        scroll.setWidget(detail_page)
        root.addWidget(scroll, 4)

        owner._settings_open = True
        owner._management_vocabulary_mode = False
        owner._settings_page_state = {
            "page": page, "original_lists": original_lists,
            "profile_id": previous_profile_id, "step_id": active_step_id,
            "vocabulary_mode": active_vocabulary_mode,
        }
        owner.steps.itemDoubleClicked.connect(owner._open_selected_step_files)
        owner.refresh_profiles(previous_profile_id)

        return page
