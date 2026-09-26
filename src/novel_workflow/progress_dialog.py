from __future__ import annotations

from datetime import date, datetime, timedelta

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QMessageBox,
    QPushButton, QProgressBar, QScrollArea, QVBoxLayout, QWidget,
)

from .models import NovelProfile
from .storage import ProjectRepository
from .translation_progress import daily_chapter_count, goal_progress, profile_week_count


class TranslationDashboardDialog(QDialog):
    """Compact overview of chapter activity and goals for all novel profiles."""

    def __init__(self, parent, profiles: list[NovelProfile], repo: ProjectRepository, refresh_callback):
        super().__init__(parent)
        self.profiles = profiles
        self.repo = repo
        self.refresh_callback = refresh_callback
        self.setWindowTitle("ความคืบหน้าการแปล")
        self.resize(760, 760)

        self.root = QVBoxLayout(self)
        self.summary = QHBoxLayout()
        self.root.addLayout(self.summary)
        self.days_panel = QFrame()
        self.days_layout = QVBoxLayout(self.days_panel)
        self.root.addWidget(QLabel("ผลงานย้อนหลัง 7 วัน"))
        self.root.addWidget(self.days_panel)

        self.root.addWidget(QLabel("ความคืบหน้ารายเรื่อง"))
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.rows_host = QWidget()
        self.rows = QVBoxLayout(self.rows_host)
        self.rows.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self.rows_host)
        self.root.addWidget(self.scroll, 1)

        close = QPushButton("ปิด")
        close.clicked.connect(self.accept)
        self.root.addWidget(close, alignment=Qt.AlignRight)
        self.refresh()

    def set_profiles(self, profiles: list[NovelProfile]):
        self.profiles = profiles
        self.refresh()

    def _clear(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
            elif item.layout():
                self._clear(item.layout())

    def _metric(self, title: str, value: int, note: str):
        card = QFrame()
        card.setStyleSheet("QFrame { background:#ffffff; border:1px solid #e7e7ed; border-radius:14px; }")
        layout = QVBoxLayout(card)
        title_label = QLabel(title)
        title_label.setStyleSheet("color:#777780;font-size:9pt;font-weight:600;border:0")
        number = QLabel(f"{value:,} บท")
        number.setStyleSheet("color:#1c1c1e;font-size:22pt;font-weight:700;border:0")
        note_label = QLabel(note)
        note_label.setStyleSheet("color:#777780;font-size:9pt;border:0")
        layout.addWidget(title_label)
        layout.addWidget(number)
        layout.addWidget(note_label)
        self.summary.addWidget(card)

    def refresh(self):
        self._clear(self.summary)
        self._clear(self.days_layout)
        self._clear(self.rows)
        today = date.today()
        today_key = today.isoformat()
        today_total = sum(daily_chapter_count(profile, today_key) for profile in self.profiles)
        week_total = sum(profile_week_count(profile, today) for profile in self.profiles)
        active = sum(1 for profile in self.profiles if daily_chapter_count(profile, today_key) > 0)
        self._metric("วันนี้", today_total, f"จาก {active} เรื่อง")
        self._metric("สัปดาห์นี้", week_total, "นับตั้งแต่วันจันทร์")
        self._metric("นิยายทั้งหมด", len(self.profiles), "เป้าหมายแยกแต่ละเรื่อง")

        recent = [today - timedelta(days=offset) for offset in range(6, -1, -1)]
        max_count = max((sum(daily_chapter_count(profile, day.isoformat()) for profile in self.profiles) for day in recent), default=0)
        max_count = max(max_count, 1)
        for day in recent:
            count = sum(daily_chapter_count(profile, day.isoformat()) for profile in self.profiles)
            line = QHBoxLayout()
            label = QLabel(day.strftime("%d/%m"))
            label.setFixedWidth(56)
            bar = QProgressBar()
            bar.setRange(0, max_count)
            bar.setValue(count)
            bar.setFormat(f"{count} บท")
            bar.setTextVisible(True)
            line.addWidget(label)
            line.addWidget(bar, 1)
            self.days_layout.addLayout(line)

        if not self.profiles:
            self.rows.addWidget(QLabel("ยังไม่มีนิยาย"))
            return
        for profile in self.profiles:
            self.rows.addWidget(self._profile_row(profile, today_key))

    def _profile_row(self, profile: NovelProfile, today_key: str) -> QFrame:
        row = QFrame()
        row.setStyleSheet("QFrame { background:#ffffff; border:1px solid #e7e7ed; border-radius:14px; }")
        layout = QVBoxLayout(row)
        header = QHBoxLayout()
        title = QLabel(profile.name)
        title.setStyleSheet("font-size:12pt;font-weight:700;border:0")
        latest = QLabel(f"ถึงบท {profile.chapter_state.current_chapter}")
        latest.setStyleSheet("color:#777780;border:0")
        header.addWidget(title, 1)
        header.addWidget(latest)
        layout.addLayout(header)

        count = daily_chapter_count(profile, today_key)
        today_label = QLabel(f"วันนี้แปลเพิ่ม {count} บท")
        today_label.setStyleSheet("color:#3a3a3c;border:0")
        layout.addWidget(today_label)

        goal = goal_progress(profile)
        controls = QHBoxLayout()
        if goal:
            completed, target, percentage = goal
            goal_label = QLabel(f"เป้าหมาย {completed}/{target} บท")
            goal_label.setStyleSheet("color:#3a3a3c;border:0")
            goal_bar = QProgressBar()
            goal_bar.setRange(0, 100)
            goal_bar.setValue(percentage)
            goal_bar.setFormat(f"{percentage}%")
            controls.addWidget(goal_label)
            controls.addWidget(goal_bar, 1)
        else:
            hint = QLabel("ยังไม่ได้ตั้งเป้าหมาย")
            hint.setStyleSheet("color:#777780;border:0")
            controls.addWidget(hint, 1)
        set_goal = QPushButton("แก้เป้าหมาย" if goal else "ตั้งเป้าหมาย")
        set_goal.clicked.connect(lambda checked=False, item=profile: self._set_goal(item))
        controls.addWidget(set_goal)
        layout.addLayout(controls)
        return row

    def _set_goal(self, profile: NovelProfile):
        current_goal = profile.translation_goal_target
        target, accepted = QInputDialog.getInt(
            self,
            "ตั้งเป้าหมายการแปล",
            f"ต้องการแปลเพิ่มกี่บทสำหรับ “{profile.name}”?",
            value=current_goal or 10,
            min=1,
            max=100000,
        )
        if not accepted:
            return
        if profile.translation_goal_target is None or profile.translation_goal_baseline is None:
            profile.translation_goal_baseline = profile.chapter_state.current_chapter
        profile.translation_goal_target = target
        try:
            self.repo.save_profile(profile)
        except OSError as exc:
            QMessageBox.warning(self, "บันทึกเป้าหมายไม่สำเร็จ", str(exc))
            return
        self.profiles = self.refresh_callback()
        self.refresh()
