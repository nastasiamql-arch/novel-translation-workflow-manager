"""Editable recurring schedules, kept alongside the existing planner."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QSpinBox, QVBoxLayout, QWidget)

from .translation_planner import TranslationPlanner


class ScheduleRow(QFrame):
    def __init__(self, planner, profile, schedule=None):
        super().__init__()
        self.planner = planner
        self.profile_id = profile.id
        self.setProperty('profileId', profile.id)
        self.setObjectName('weeklyScheduleRow')
        schedule = schedule or {}
        layout = QVBoxLayout(self)
        title = QLabel(profile.name)
        title.setWordWrap(True)
        title.setObjectName('sectionHeading')
        layout.addWidget(title)
        options = QHBoxLayout()
        self.enabled = QCheckBox('เปิดใช้ตาราง')
        self.enabled.setChecked(schedule.get('enabled', False))
        self.caught = QCheckBox('ชนต้นฉบับแล้ว')
        self.caught.setChecked(schedule.get('caught_up', False))
        options.addWidget(self.enabled)
        options.addWidget(self.caught)
        options.addStretch()
        layout.addLayout(options)
        self.goal_row = QWidget()
        goal = QHBoxLayout(self.goal_row)
        goal.setContentsMargins(0, 0, 0, 0)
        goal.addWidget(QLabel('เป้าหมายต่อวัน'))
        self.target = QSpinBox()
        self.target.setRange(0, 2147483647)
        self.target.setSpecialValueText('ระบุจำนวนบท')
        self.target.setValue(schedule.get('target_chapters') or 0)
        self.target.setKeyboardTracking(False)
        goal.addWidget(self.target)
        goal.addWidget(QLabel('บท'))
        goal.addStretch()
        layout.addWidget(self.goal_row)
        self.goal_row.setVisible(not self.caught.isChecked())
        layout.addWidget(QLabel('วันที่แปล'))
        days = QGridLayout()
        self.weekdays = []
        for day, label in enumerate(('จ.', 'อ.', 'พ.', 'พฤ.', 'ศ.', 'ส.', 'อา.')):
            button = QPushButton(label)
            button.setObjectName('libraryViewButton')
            button.setCheckable(True)
            button.setChecked(day in schedule.get('weekdays', []))
            button.setAccessibleName('วัน' + label)
            button.clicked.connect(self._day_changed)
            days.addWidget(button, day // 4, day % 4)
            self.weekdays.append(button)
        layout.addLayout(days)
        self.error = QLabel()
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        self.error.hide()
        self.enabled.clicked.connect(self.save)
        self.caught.clicked.connect(self._catch_changed)
        self.target.editingFinished.connect(self._goal_changed)

    def _catch_changed(self):
        self.goal_row.setVisible(not self.caught.isChecked())
        if self.caught.isChecked():
            self.enabled.setChecked(True)
        elif not self.target.value():
            self.enabled.setChecked(False)
        self.save()
        if not self.caught.isChecked() and not self.target.value() and self.error.isHidden():
            self.error.setText('ระบุจำนวนบทเพื่อเปิดใช้ตารางแบบมีเป้าหมาย')
            self.error.show()

    def _day_changed(self):
        if self.caught.isChecked() or self.target.value() > 0:
            self.enabled.setChecked(True)
        self.save()
        if not self.caught.isChecked() and not self.target.value() and self.error.isHidden():
            self.error.setText('ระบุจำนวนบทเพื่อเปิดใช้ตารางแบบมีเป้าหมาย')
            self.error.show()

    def _goal_changed(self):
        if self.target.value() and any(button.isChecked() for button in self.weekdays):
            self.enabled.setChecked(True)
        self.save()

    def save(self, *_):
        try:
            self.planner.save_weekly_schedule(
                self.profile_id, weekdays=[i for i, b in enumerate(self.weekdays) if b.isChecked()],
                target_chapters=self.target.value() or None, caught_up=self.caught.isChecked(),
                enabled=self.enabled.isChecked())
        except (OSError, ValueError, TypeError) as exc:
            self.error.setText('บันทึกไม่ได้: กรุณาตรวจเป้าหมายหรือพื้นที่จัดเก็บ (' + str(exc) + ')')
            self.error.show()
        else:
            self.error.hide()


class WeeklySchedulerPage(QWidget):
    back = Signal()

    def __init__(self, repo):
        super().__init__()
        self.repo = repo
        self.planner = TranslationPlanner(repo)
        self.rows = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        head = QHBoxLayout()
        button = QPushButton('← กลับ')
        button.clicked.connect(self.back.emit)
        head.addWidget(button)
        title = QLabel('ตารางแปลนิยาย')
        title.setObjectName('pageTitle')
        head.addWidget(title, 1)
        root.addLayout(head)
        root.addWidget(QLabel('กำหนดวันแปลและเป้าหมายของแต่ละเรื่อง'))
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.content = QWidget()
        self.list_layout = QVBoxLayout(self.content)
        self.scroll.setWidget(self.content)
        root.addWidget(self.scroll, 1)

    def refresh(self):
        profiles = self.repo.list_profiles()
        ids = {p.id for p in profiles}
        data = self.planner._load().get('weekly_schedules', {})
        if not isinstance(data, dict):
            raise ValueError('Invalid weekly schedules')
        for pid in list(self.rows):
            if pid not in ids:
                row = self.rows.pop(pid)
                self.list_layout.removeWidget(row)
                row.deleteLater()
        for index, profile in enumerate(profiles):
            row = self.rows.get(profile.id)
            if row is None:
                row = ScheduleRow(self.planner, profile, data.get(profile.id))
                self.rows[profile.id] = row
            row.findChild(QLabel).setText(profile.name)
            self.list_layout.insertWidget(index, row)
        if not self.list_layout.count() or self.list_layout.itemAt(self.list_layout.count() - 1).widget():
            self.list_layout.addStretch()
