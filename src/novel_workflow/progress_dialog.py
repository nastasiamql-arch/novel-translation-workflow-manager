from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QProgressBar, QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from .models import NovelProfile
from .storage import ProjectRepository
from .translation_progress import daily_chapter_count, goal_progress, profile_week_count, reset_goal_progress


class TranslationDashboardDialog(QWidget):
    """Embedded overview of chapter activity and goals for all novels."""

    def __init__(self, parent, profiles: list[NovelProfile], repo: ProjectRepository, refresh_callback):
        super().__init__(parent)
        self.profiles = profiles
        self.repo = repo
        self.refresh_callback = refresh_callback
        self.root = QVBoxLayout(self)
        self.summary = QHBoxLayout()
        self.root.addLayout(self.summary)
        self.bulk_goal_panel = QFrame()
        self.bulk_goal_panel.setObjectName("settingsCard")
        bulk_goal_layout = QHBoxLayout(self.bulk_goal_panel)
        bulk_goal_layout.addWidget(QLabel("เป้าหมายรอบใหม่ · เรื่องที่กำลังแปล"))
        self.bulk_goal_target = QSpinBox()
        self.bulk_goal_target.setRange(1, 100000)
        self.bulk_goal_target.setValue(10)
        self.bulk_goal_target.setSuffix(" บทต่อเรื่อง")
        bulk_goal_layout.addWidget(self.bulk_goal_target)
        self.bulk_goal_hint = QLabel()
        self.bulk_goal_hint.setObjectName("mutedLabel")
        bulk_goal_layout.addWidget(self.bulk_goal_hint, 1)
        self.bulk_goal_button = QPushButton("ตั้งให้ทุกเรื่องที่กำลังแปล")
        self.bulk_goal_button.clicked.connect(self._apply_goal_to_translating)
        bulk_goal_layout.addWidget(self.bulk_goal_button)
        self.clear_all_goals_button = QPushButton("ยกเลิกเป้าหมายทั้งหมด")
        self.clear_all_goals_button.setToolTip(
            "ล้างเป้าหมายทุกนิยาย โดยเก็บประวัติการแปลและความคืบหน้ารายวันไว้"
        )
        self.clear_all_goals_button.clicked.connect(self._clear_all_goals)
        bulk_goal_layout.addWidget(self.clear_all_goals_button)
        self.root.addWidget(self.bulk_goal_panel)
        self.days_panel = QFrame()
        self.days_layout = QVBoxLayout(self.days_panel)
        history_title=QLabel("ผลงานย้อนหลัง 7 วัน")
        history_title.setObjectName("sectionHeading")
        self.root.addWidget(history_title)
        self.root.addWidget(self.days_panel)

        progress_title=QLabel("ความคืบหน้ารายเรื่อง")
        progress_title.setObjectName("sectionHeading")
        self.root.addWidget(progress_title)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.rows_host = QWidget()
        self.rows = QVBoxLayout(self.rows_host)
        self.rows.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self.rows_host)
        self.root.addWidget(self.scroll, 1)

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
        card.setObjectName("metricCard")
        layout = QVBoxLayout(card)
        title_label = QLabel(title)
        title_label.setObjectName("metricLabel")
        number = QLabel(f"{value:,} บท")
        number.setObjectName("metricValue")
        note_label = QLabel(note)
        note_label.setObjectName("mutedLabel")
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
        eligible = self._eligible_translating_profiles()
        self.bulk_goal_hint.setText(
            f"ตั้งได้ {len(eligible)} เรื่องที่มีไฟล์ Context"
            if eligible else "ไม่มีเรื่องที่กำลังแปลพร้อมใช้ Context"
        )
        self.bulk_goal_button.setEnabled(bool(eligible))
        self.clear_all_goals_button.setEnabled(any(
            profile.translation_goal_target is not None for profile in self.profiles
        ))
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
            label.setObjectName("mutedLabel")
            label.setFixedWidth(56)
            bar = QProgressBar()
            bar.setRange(0, max_count)
            bar.setValue(count)
            bar.setTextVisible(False)
            count_label = QLabel(f"{count} บท")
            count_label.setObjectName("bodyLabel")
            line.addWidget(label)
            line.addWidget(bar, 1)
            line.addWidget(count_label)
            self.days_layout.addLayout(line)

        if not self.profiles:
            self.rows.addWidget(QLabel("ยังไม่มีนิยาย"))
            return
        for profile in self.profiles:
            self.rows.addWidget(self._profile_row(profile, today_key))

    def _eligible_translating_profiles(self) -> list[NovelProfile]:
        return [
            profile for profile in self.profiles
            if str(getattr(profile, "status", "translating") or "translating").strip() == "translating"
            and bool(profile.context_path and Path(profile.context_path).expanduser().is_file())
        ]

    def _apply_goal_to_translating(self):
        target = self.bulk_goal_target.value()
        eligible = self._eligible_translating_profiles()
        if not eligible:
            return
        try:
            for profile in eligible:
                if profile.translation_goal_target is None or profile.translation_goal_baseline is None:
                    profile.translation_goal_baseline = profile.chapter_state.current_chapter
                profile.translation_goal_target = target
                self.repo.save_profile(profile)
        except OSError as exc:
            QMessageBox.warning(self, "ตั้งเป้าหมายไม่สำเร็จ", str(exc))
            self.profiles = self.refresh_callback()
            self.refresh()
            return
        self.profiles = self.refresh_callback()
        self.refresh()

    def _clear_all_goals(self):
        targets = [
            profile for profile in self.profiles
            if profile.translation_goal_target is not None
        ]
        if not targets:
            return
        answer = QMessageBox.question(
            self,
            "ยกเลิกเป้าหมายทั้งหมด",
            f"ยกเลิกเป้าหมายของนิยาย {len(targets)} เรื่องใช่ไหม?\n\n"
            "ประวัติการแปลและจำนวนบทที่แปลรายวันจะยังอยู่",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        for profile in targets:
            profile.translation_goal_target = None
            try:
                self.repo.save_profile(profile)
            except OSError as exc:
                QMessageBox.warning(
                    self, "ยกเลิกเป้าหมายไม่สำเร็จ",
                    f"บันทึกการยกเลิกของ {profile.name} ไม่สำเร็จ: {exc}",
                )
                self.profiles = self.refresh_callback()
                self.refresh()
                return
        self.profiles = self.refresh_callback()
        self.refresh()

    def _profile_row(self, profile: NovelProfile, today_key: str) -> QFrame:
        row = QFrame()
        row.setObjectName("progressRow")
        layout = QVBoxLayout(row)
        header = QHBoxLayout()
        title = QLabel(profile.name)
        title.setObjectName("metricLabel")
        title.setWordWrap(True)
        latest = QLabel(f"ถึงบท {profile.chapter_state.current_chapter}" if profile.context_path else "ยังไม่ได้เชื่อม Context")
        latest.setObjectName("mutedLabel")
        header.addWidget(title, 1)
        header.addWidget(latest)
        layout.addLayout(header)

        count = daily_chapter_count(profile, today_key)
        today_label = QLabel(f"วันนี้แปลเพิ่ม {count} บท")
        today_label.setObjectName("bodyLabel")
        layout.addWidget(today_label)

        goal = goal_progress(profile)
        controls = QHBoxLayout()
        if goal:
            completed, target, percentage = goal
            goal_label = QLabel(f"เป้าหมาย {completed}/{target} บท")
            goal_label.setObjectName("bodyLabel")
            goal_bar = QProgressBar()
            goal_bar.setRange(0, 100)
            goal_bar.setValue(percentage)
            goal_bar.setTextVisible(False)
            controls.addWidget(goal_label)
            controls.addWidget(goal_bar, 1)
            percentage_label = QLabel(f"{percentage}%")
            percentage_label.setObjectName("bodyLabel")
            percentage_label.setMinimumWidth(42)
            percentage_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            controls.addWidget(percentage_label)
        else:
            hint = QLabel("ยังไม่ได้ตั้งเป้าหมาย")
            hint.setObjectName("mutedLabel")
            controls.addWidget(hint, 1)
        set_goal = QPushButton("แก้เป้าหมาย" if goal else "ตั้งเป้าหมาย")
        has_context = bool(profile.context_path and Path(profile.context_path).expanduser().is_file())
        set_goal.setEnabled(has_context)
        if not has_context:set_goal.setToolTip("เลือกไฟล์ Context ของนิยายก่อน จึงจะติดตามเป้าหมายได้")
        target_input = QSpinBox()
        target_input.setRange(1, 100000)
        target_input.setValue(profile.translation_goal_target or 10)
        target_input.setPrefix("เป้าหมาย ")
        target_input.setSuffix(" บท")
        save_goal = QPushButton("บันทึก")
        target_input.hide()
        save_goal.hide()
        set_goal.clicked.connect(
            lambda checked=False, field=target_input, save=save_goal:
                (field.show(), save.show(), set_goal.hide())
        )
        save_goal.clicked.connect(
            lambda checked=False, item=profile, field=target_input:
                self._save_goal(item, field.value())
        )
        controls.addWidget(set_goal)
        controls.addWidget(target_input)
        controls.addWidget(save_goal)
        if goal:
            reset = QPushButton("รีเซ็ตความคืบหน้า")
            reset.setToolTip("เริ่มนับเป้าหมายใหม่จากบทปัจจุบัน โดยเก็บจำนวนเป้าหมายเดิมไว้")
            reset.clicked.connect(lambda checked=False, item=profile: self._reset_goal(item))
            controls.addWidget(reset)
        layout.addLayout(controls)
        return row

    def _reset_goal(self, profile: NovelProfile):
        if not goal_progress(profile):
            return
        answer = QMessageBox.question(
            self,
            "รีเซ็ตความคืบหน้าเป้าหมาย",
            f"เริ่มเป้าหมาย {profile.translation_goal_target} บทใหม่จากบท {profile.chapter_state.current_chapter} ใช่ไหม?\n\nจำนวนบทที่แปลรายวันจะไม่ถูกลบ",
        )
        if answer != QMessageBox.Yes:
            return
        reset_goal_progress(profile)
        try:
            self.repo.save_profile(profile)
        except OSError as exc:
            QMessageBox.warning(self, "รีเซ็ตเป้าหมายไม่สำเร็จ", str(exc))
            return
        self.profiles = self.refresh_callback()
        self.refresh()

    def _save_goal(self, profile: NovelProfile, target: int):
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
