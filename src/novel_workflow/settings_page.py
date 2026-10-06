"""Settings UI construction, reusing the shell's existing management actions."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QFrame, QLabel,
    QGridLayout, QPushButton, QScrollArea, QListWidget, QAbstractItemView, QSpinBox,
    QLineEdit, QSizePolicy)
from .shell_components import ElidingLabel


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
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        owner.profiles = profile_list_type()
        owner.profiles.orderChanged.connect(owner._persist_profile_order)
        owner.profiles.setSpacing(1)
        owner.profiles.setCursor(Qt.ArrowCursor)
        owner.profiles.setAccessibleName("รายการนิยาย")
        owner.profiles.selectionCommitted.connect(owner.select_profile)
        owner.steps = QListWidget()
        owner.steps.setSpacing(1)
        owner.steps.setCursor(Qt.PointingHandCursor)
        owner.steps.setAccessibleName("ขั้นตอนงาน")
        owner.steps.setSelectionMode(QAbstractItemView.SingleSelection)
        owner.steps.currentRowChanged.connect(owner.select_step)
        owner.files = QListWidget()
        owner.files.setSpacing(1)
        owner.files.setCursor(Qt.PointingHandCursor)
        owner.files.setAccessibleName("ไฟล์ของขั้นตอน")
        owner.files.itemChanged.connect(owner.toggle_file)

        profile_panel = QFrame()
        profile_panel.setObjectName("settingsCard")
        profile_layout = QVBoxLayout(profile_panel)
        profile_layout.addWidget(QLabel("นิยายของฉัน"))
        profile_layout.addWidget(owner.profiles, 1)
        profile_actions = QGridLayout()
        for index, (label, callback) in enumerate((
            ("＋ เพิ่มนิยาย", owner.new_profile), ("ทำสำเนา", owner.duplicate_profile),
            ("เลื่อนขึ้น", lambda: owner.move_profile(-1)), ("เลื่อนลง", lambda: owner.move_profile(1)),
        )):
            button = QPushButton(label)
            button.clicked.connect(callback)
            profile_actions.addWidget(button, index // 2, index % 2)
        profile_layout.addLayout(profile_actions)
        profile_panel.setMinimumWidth(230)
        root.addWidget(profile_panel, 1)

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

        story_actions = QHBoxLayout()
        for label, callback in (
            ("เปลี่ยนชื่อ", owner.rename_profile), ("ตั้งรูปปก", owner.set_cover),
            ("เอารูปปกออก", owner.remove_cover), ("เลือก Context", owner.set_context_file),
            ("ลบนิยาย", owner.delete_profile),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            story_actions.addWidget(button)
        detail.addLayout(story_actions)

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
        save_folder = QPushButton("บันทึกโฟลเดอร์")
        save_folder.clicked.connect(owner.save_settings_main_folder)
        folder_row.addWidget(save_folder)
        launcher_layout.addLayout(folder_row)
        owner.settings_launch_targets = QListWidget()
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
        workflow_frame.setMinimumHeight(470)
        workflow_layout = QVBoxLayout(workflow_frame)
        workflow_layout.addWidget(QLabel("ขั้นตอนและไฟล์แนบ"))
        workflow_columns = QHBoxLayout()
        steps_column = QVBoxLayout()
        steps_column.addWidget(QLabel("เลือกขั้นตอน"))
        owner.steps.setMinimumHeight(250)
        owner.steps.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        steps_column.addWidget(owner.steps, 1)
        step_actions = QGridLayout()
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
        steps_column.addLayout(step_actions)
        workflow_columns.addLayout(steps_column, 1)

        files_column = QVBoxLayout()
        files_header = QHBoxLayout()
        files_header.addWidget(QLabel("ไฟล์แนบของขั้นตอนที่เลือก"), 1)
        owner.settings_step_hint = QLabel("เลือกขั้นตอนเพื่อจัดการไฟล์")
        owner.settings_step_hint.setObjectName("mutedLabel")
        files_header.addWidget(owner.settings_step_hint)
        files_column.addLayout(files_header)
        owner.files.setMinimumHeight(250)
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
        files_column.addLayout(file_actions)
        workflow_columns.addLayout(files_column, 2)
        workflow_layout.addLayout(workflow_columns)
        detail.addWidget(workflow_frame, 1)

        work_frame = QFrame()
        work_frame.setObjectName("settingsCard")
        work_layout = QVBoxLayout(work_frame)
        work_header = QHBoxLayout()
        work_header.addWidget(QLabel("ไฟล์สำหรับเปิดทำงาน"), 1)
        owner.working_files_hint = QLabel("เลือกไฟล์ที่ต้องการเปิดเป็นแท็บ โดยไม่ผูกกับขั้นตอน")
        owner.working_files_hint.setObjectName("mutedLabel")
        work_header.addWidget(owner.working_files_hint)
        work_layout.addLayout(work_header)
        owner.working_files = QListWidget()
        owner.working_files.setSelectionMode(QAbstractItemView.SingleSelection)
        owner.working_files.itemDoubleClicked.connect(owner.open_selected_working_file)
        work_layout.addWidget(owner.working_files)
        work_actions = QHBoxLayout()
        for label, callback in (
            ("＋ เลือกหลายไฟล์", owner.add_working_files),
            ("เปิดไฟล์ที่เลือก", owner.open_selected_working_file),
            ("เอาออกจากรายการ", owner.remove_working_file),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            work_actions.addWidget(button)
        work_layout.addLayout(work_actions)
        detail.addWidget(work_frame)

        program_settings = QPushButton("ตั้งค่าโปรแกรม")
        program_settings.clicked.connect(owner.program_settings_dialog)
        detail.addWidget(program_settings, alignment=Qt.AlignRight)
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
