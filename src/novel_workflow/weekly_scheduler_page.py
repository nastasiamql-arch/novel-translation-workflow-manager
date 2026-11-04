"""Editable recurring schedules, kept alongside the existing planner."""
from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QImageReader, QPixmap
from PySide6.QtWidgets import (QBoxLayout, QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QScrollArea, QSizePolicy, QSpinBox,
                               QVBoxLayout, QWidget)

from .translation_planner import TranslationPlanner


class ScheduleRow(QFrame):
    def __init__(self, planner, profile, schedule=None):
        super().__init__()
        self.planner = planner
        self.profile_id = profile.id
        self.setProperty('profileId', profile.id)
        self.setObjectName('weeklyScheduleRow')
        self._cover_key = None
        self._retry_resume = False
        self._retry_pause = False
        self._paused = bool(schedule is not None and not schedule.get('enabled', False)
                            and schedule.get('weekdays')
                            and (schedule.get('caught_up') or schedule.get('target_chapters')))
        schedule = schedule or {}
        outer = QHBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(10)
        self.cover = QLabel('▤')
        self.cover.setObjectName('weeklyScheduleCover')
        self.cover.setFixedSize(48, 64)
        self.cover.setAlignment(Qt.AlignCenter)
        outer.addWidget(self.cover, 0, Qt.AlignTop)
        body = QVBoxLayout()
        body.setSpacing(5)
        outer.addLayout(body, 1)
        heading = QHBoxLayout()
        self.title = QLabel()
        self.title.setObjectName('sectionHeading')
        self.title.setMinimumWidth(0)
        self.title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        heading.addWidget(self.title, 1)
        self.caught = QCheckBox('ชนต้นฉบับแล้ว')
        self.caught.setChecked(schedule.get('caught_up', False))
        heading.addWidget(self.caught)
        self.pause = QPushButton('พักตาราง')
        self.pause.setVisible(bool(schedule.get('enabled', False)))
        self.pause.clicked.connect(self._pause)
        heading.addWidget(self.pause)
        body.addLayout(heading)
        self.controls = QBoxLayout(QBoxLayout.LeftToRight)
        self.controls.setSpacing(5)
        controls = self.controls
        self.goal_row = QWidget()
        goal = QHBoxLayout(self.goal_row)
        goal.setContentsMargins(0, 0, 0, 0)
        goal.setSpacing(4)
        goal.addWidget(QLabel('เป้า'))
        self.target = QSpinBox()
        self.target.setRange(0, 2147483647)
        self.target.setSpecialValueText('—')
        self.target.setValue(schedule.get('target_chapters') or 0)
        self.target.setKeyboardTracking(False)
        self.target.setMaximumWidth(105)
        goal.addWidget(self.target)
        goal.addWidget(QLabel('บท'))
        controls.addWidget(self.goal_row)
        self.goal_row.setVisible(not self.caught.isChecked())
        days_widget = QWidget()
        days = QHBoxLayout(days_widget)
        days.setContentsMargins(0, 0, 0, 0)
        days.setSpacing(5)
        self.weekdays = []
        for day, label in enumerate(('จ.', 'อ.', 'พ.', 'พฤ.', 'ศ.', 'ส.', 'อา.')):
            button = QPushButton(label)
            button.setObjectName('libraryViewButton')
            button.setCheckable(True)
            button.setChecked(day in schedule.get('weekdays', []))
            button.setAccessibleName('วัน' + label)
            button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
            button.setMinimumWidth(max(38, button.fontMetrics().horizontalAdvance(label) + 16))
            button.clicked.connect(self._day_changed)
            days.addWidget(button)
            self.weekdays.append(button)
        days.addStretch()
        controls.addWidget(days_widget)
        controls.addStretch()
        body.addLayout(controls)
        self.resume = QPushButton('ตารางพักอยู่ · เปิดใช้งาน')
        self.resume.setVisible(self._paused)
        self.resume.clicked.connect(self._resume)
        body.addWidget(self.resume, 0, Qt.AlignLeft)
        self.error = QLabel()
        self.error.setWordWrap(True)
        body.addWidget(self.error)
        self.error.hide()
        self.retry = QPushButton('ลองบันทึกอีกครั้ง')
        self.retry.hide()
        self.retry.clicked.connect(self._retry_save)
        body.addWidget(self.retry, 0, Qt.AlignLeft)
        self.caught.clicked.connect(self._catch_changed)
        self.target.editingFinished.connect(self._goal_changed)
        self.update_profile(profile)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        direction = (QBoxLayout.TopToBottom if self.width() < 620
                     else QBoxLayout.LeftToRight)
        if self.controls.direction() != direction:
            self.controls.setDirection(direction)

    def update_profile(self, profile):
        self.title.setText(profile.name)
        self.title.setToolTip(profile.name)
        self.title.setAccessibleName(profile.name)
        path = None
        try:
            if profile.cover_image_path:
                path = self.planner.repo.resolve_project_path(profile.id, profile.cover_image_path)
                stat = path.stat()
                key = (str(path), stat.st_mtime_ns, stat.st_size)
            else:
                key = None
        except (OSError, ValueError, TypeError):
            key = None
            path = None
        if key == self._cover_key and self.cover.text() != '▤':
            return
        self._cover_key = key
        self.cover.clear()
        if path is not None:
            reader = QImageReader(str(path))
            reader.setAutoTransform(True)
            size = reader.size()
            if size.isValid():
                size.scale(QSize(48, 64), Qt.KeepAspectRatio)
                reader.setScaledSize(size)
            image = reader.read()
            if not image.isNull():
                self.cover.setPixmap(QPixmap.fromImage(image))
                return
        self.cover.setText('▤')

    def _pause(self):
        self._retry_pause = True
        self._paused = True
        if self.save():
            self.resume.show()
            self.pause.hide()
        else:
            self._paused = False

    def _resume(self):
        if not self.caught.isChecked() and not self.target.value():
            self.error.setText('ระบุจำนวนบทเพื่อเปิดใช้ตารางแบบมีเป้าหมาย')
            self.error.show()
            return
        if not any(b.isChecked() for b in self.weekdays):
            self.error.setText('เลือกวันแปลอย่างน้อยหนึ่งวัน')
            self.error.show()
            return
        self._paused = False
        self._retry_resume = True
        if not self.save():
            self._paused = True
        self.resume.setVisible(self._paused)
        self.pause.setVisible(not self._paused)

    def _retry_save(self):
        if self._retry_resume:
            self._resume()
        elif self._retry_pause:
            self._pause()
        else:
            self.save()

    def _catch_changed(self):
        self.goal_row.setVisible(not self.caught.isChecked())
        self.save()

    def _day_changed(self):
        self.save()

    def _goal_changed(self):
        self.save()

    def save(self, *_):
        days = [i for i, button in enumerate(self.weekdays) if button.isChecked()]
        valid = self.caught.isChecked() or self.target.value() > 0
        enabled = bool(days and valid and not self._paused)
        try:
            self.planner.save_weekly_schedule(
                self.profile_id, weekdays=days, target_chapters=self.target.value() or None,
                caught_up=self.caught.isChecked(), enabled=enabled)
        except (OSError, ValueError, TypeError) as exc:
            self.error.setText('บันทึกไม่ได้: กรุณาตรวจเป้าหมายหรือพื้นที่จัดเก็บ (' + str(exc) + ')')
            self.error.show()
            self.retry.show()
            return False
        self.retry.hide()
        self._retry_resume = False
        self._retry_pause = False
        self.pause.setVisible(enabled)
        if days and not valid:
            self.error.setText('ระบุจำนวนบทเพื่อเปิดใช้ตารางแบบมีเป้าหมาย')
            self.error.show()
        else:
            self.error.hide()
        return True


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
        self.search = QLineEdit()
        self.search.setPlaceholderText('ค้นหานิยาย...')
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        root.addWidget(self.search)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.content = QWidget()
        self.list_layout = QVBoxLayout(self.content)
        self.list_layout.setSpacing(8)
        self.scroll.setWidget(self.content)
        root.addWidget(self.scroll, 1)

    def _filter(self, text):
        query = text.casefold().strip()
        for row in self.rows.values():
            row.setVisible(query in row.title.text().casefold())

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
            else:
                row.update_profile(profile)
            self.list_layout.insertWidget(index, row)
        if not self.list_layout.count() or self.list_layout.itemAt(self.list_layout.count() - 1).widget():
            self.list_layout.addStretch()
        self._filter(self.search.text())
