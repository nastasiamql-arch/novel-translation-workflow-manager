from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QMessageBox,
    QPushButton, QProgressBar, QScrollArea, QVBoxLayout, QWidget,
)

from .models import NovelGroup, NovelProfile
from .storage import ProjectRepository
from .translation_progress import (
    apply_group_goal, daily_chapter_count, goal_progress, profile_week_count,
    reset_goal_progress, reset_group_goal_progress, sync_profile_context,
)


class TranslationDashboardDialog(QDialog):
    """Compact overview of chapter activity and goals for all novel profiles."""

    def __init__(self, parent, profiles: list[NovelProfile], repo: ProjectRepository, refresh_callback):
        super().__init__(parent)
        self.profiles = profiles
        self.repo = repo
        self.refresh_callback = refresh_callback
        self.groups = repo.load_groups()
        self.setWindowTitle("ความคืบหน้าการแปล")
        self.resize(760, 760)

        self.root = QVBoxLayout(self)
        self.summary = QHBoxLayout()
        self.root.addLayout(self.summary)
        self.days_panel = QFrame()
        self.days_layout = QVBoxLayout(self.days_panel)
        history_title=QLabel("ผลงานย้อนหลัง 7 วัน")
        history_title.setObjectName("sectionHeading")
        self.root.addWidget(history_title)
        self.root.addWidget(self.days_panel)

        progress_title=QLabel("เป้าหมายกลุ่มและความคืบหน้ารายเรื่อง")
        progress_title.setObjectName("sectionHeading")
        self.root.addWidget(progress_title)
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
        self.groups = self.repo.load_groups()
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
        self.groups = self.repo.load_groups()
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
            label.setObjectName("mutedLabel")
            label.setFixedWidth(56)
            bar = QProgressBar()
            bar.setRange(0, max_count)
            bar.setValue(count)
            bar.setFormat(f"{count} บท")
            bar.setTextVisible(True)
            line.addWidget(label)
            line.addWidget(bar, 1)
            self.days_layout.addLayout(line)

        if self.groups:
            group_heading = QLabel("เป้าหมายรายกลุ่ม")
            group_heading.setObjectName("sectionHeading")
            self.rows.addWidget(group_heading)
            for group in sorted(self.groups, key=lambda item: (item.order, item.name.casefold())):
                self.rows.addWidget(self._group_row(group))
        if not self.profiles:
            self.rows.addWidget(QLabel("ยังไม่มีนิยาย"))
            return
        for profile in self.profiles:
            self.rows.addWidget(self._profile_row(profile, today_key))

    def _group_members(self, group: NovelGroup) -> list[NovelProfile]:
        member_ids = set(group.profile_ids)
        return [profile for profile in self.profiles if profile.id in member_ids]

    def _group_for_profile(self, profile: NovelProfile) -> NovelGroup | None:
        matches = [
            group for group in self.groups
            if profile.id in group.profile_ids
            and isinstance(group.default_goal_chapters, int)
            and not isinstance(group.default_goal_chapters, bool)
            and group.default_goal_chapters > 0
        ]
        return min(matches, key=lambda item: (item.order, item.name.casefold())) if matches else None

    def _group_row(self, group: NovelGroup) -> QFrame:
        members = self._group_members(group)
        row = QFrame()
        row.setObjectName("progressRow")
        layout = QHBoxLayout(row)
        info = QVBoxLayout()
        title = QLabel(group.name)
        title.setObjectName("metricLabel")
        count = QLabel(f"{len(members)} เรื่องในกลุ่ม")
        count.setObjectName("mutedLabel")
        goal = group.default_goal_chapters
        has_goal = isinstance(goal, int) and not isinstance(goal, bool) and goal > 0
        summary = QLabel(
            f"เป้ากลุ่ม {goal} บทต่อเรื่อง" if has_goal
            else "ยังไม่ได้ตั้งเป้ากลุ่ม"
        )
        summary.setObjectName("bodyLabel" if has_goal else "mutedLabel")
        info.addWidget(title)
        info.addWidget(count)
        info.addWidget(summary)
        layout.addLayout(info, 1)

        set_button = QPushButton("ตั้งเป้าทั้งกลุ่ม" if not has_goal else "แก้เป้ากลุ่ม")
        set_button.clicked.connect(lambda checked=False, group_id=group.id: self._set_group_goal(group_id))
        layout.addWidget(set_button)
        if has_goal and members:
            reset_button = QPushButton("รีเซ็ตทั้งกลุ่ม")
            reset_button.setToolTip("เริ่มนับใหม่จากบทปัจจุบันของแต่ละเรื่อง โดยคงเป้ากลุ่มไว้")
            reset_button.clicked.connect(lambda checked=False, group_id=group.id: self._reset_group_goal(group_id))
            layout.addWidget(reset_button)
        return row

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
            goal_bar.setFormat(f"{percentage}%")
            controls.addWidget(goal_label)
            controls.addWidget(goal_bar, 1)
        else:
            hint = QLabel("ยังไม่ได้ตั้งเป้าหมาย")
            hint.setObjectName("mutedLabel")
            controls.addWidget(hint, 1)
        set_goal = QPushButton("แก้เป้าหมาย" if goal else "ตั้งเป้าหมาย")
        has_context = bool(profile.context_path and Path(profile.context_path).expanduser().is_file())
        set_goal.setEnabled(has_context)
        if not has_context:set_goal.setToolTip("เลือกไฟล์ Context ของนิยายก่อน จึงจะติดตามเป้าหมายได้")
        set_goal.clicked.connect(lambda checked=False, item=profile: self._set_goal(item))
        controls.addWidget(set_goal)
        if goal:
            reset = QPushButton("รีเซ็ตเรื่องนี้")
            group = self._group_for_profile(profile)
            if group:
                reset.setToolTip(f"เริ่มนับใหม่จากบทปัจจุบัน และใช้เป้ากลุ่ม “{group.name}”")
            else:
                reset.setToolTip("เริ่มนับเป้าหมายใหม่จากบทปัจจุบัน")
            reset.clicked.connect(lambda checked=False, item=profile: self._reset_goal(item))
            controls.addWidget(reset)
        layout.addLayout(controls)
        return row

    def _commit_group_change(
        self, group: NovelGroup, members: list[NovelProfile],
        previous_profiles: dict[str, NovelProfile], previous_groups: list[NovelGroup],
    ) -> bool:
        try:
            for profile in members:
                self.repo.save_profile(profile)
            self.repo.save_groups(self.groups)
        except Exception as exc:
            rollback_errors = []
            for profile_id, original in previous_profiles.items():
                try:
                    self.repo.save_profile(original)
                except Exception as rollback_exc:
                    rollback_errors.append(str(rollback_exc))
            self.groups = previous_groups
            try:
                self.repo.save_groups(previous_groups)
            except Exception as rollback_exc:
                rollback_errors.append(str(rollback_exc))
            detail = f"บันทึกเป้าหมายไม่สำเร็จ: {exc}"
            if rollback_errors:
                detail += "\nกู้คืนข้อมูลบางส่วนไม่สำเร็จ: " + "; ".join(rollback_errors)
            QMessageBox.warning(self, "บันทึกเป้าหมายไม่สำเร็จ", detail)
            self.profiles = self.refresh_callback()
            self.refresh()
            return False
        self.profiles = self.refresh_callback()
        self.groups = self.repo.load_groups()
        self.refresh()
        return True

    def _set_group_goal(self, group_id: str):
        group = next((item for item in self.groups if item.id == group_id), None)
        if group is None:
            return
        members = self._group_members(group)
        target, accepted = QInputDialog.getInt(
            self, "ตั้งเป้าหมายทั้งกลุ่ม",
            f"เป้าหมายกี่บทต่อเรื่องสำหรับกลุ่ม “{group.name}”?",
            value=(
                group.default_goal_chapters
                if isinstance(group.default_goal_chapters, int)
                and not isinstance(group.default_goal_chapters, bool)
                and group.default_goal_chapters > 0 else 10
            ), min=1, max=100000,
        )
        if not accepted:
            return
        for profile in members:
            sync_profile_context(profile)
        previous_profiles = {profile.id: deepcopy(profile) for profile in members}
        previous_groups = deepcopy(self.groups)
        try:
            apply_group_goal(group, members, target)
        except ValueError as exc:
            QMessageBox.warning(self, "ตั้งเป้ากลุ่มไม่สำเร็จ", str(exc))
            return
        if self._commit_group_change(group, members, previous_profiles, previous_groups):
            QMessageBox.information(self, "ตั้งเป้ากลุ่มแล้ว", f"ตั้งเป้า {target} บทต่อเรื่องให้ {len(members)} เรื่องในกลุ่ม “{group.name}” แล้ว")

    def _reset_group_goal(self, group_id: str):
        group = next((item for item in self.groups if item.id == group_id), None)
        if (
            group is None or not isinstance(group.default_goal_chapters, int)
            or isinstance(group.default_goal_chapters, bool) or group.default_goal_chapters <= 0
        ):
            return
        members = self._group_members(group)
        if not members:
            return
        answer = QMessageBox.question(
            self, "รีเซ็ตเป้าหมายทั้งกลุ่ม",
            f"เริ่มนับเป้าหมาย {group.default_goal_chapters} บทใหม่ให้ {len(members)} เรื่อง "
            "จากบทปัจจุบันของแต่ละเรื่องหรือไม่?\n\nสถิติรายวันจะไม่ถูกลบ",
        )
        if answer != QMessageBox.Yes:
            return
        for profile in members:
            sync_profile_context(profile)
        previous_profiles = {profile.id: deepcopy(profile) for profile in members}
        previous_groups = deepcopy(self.groups)
        reset_group_goal_progress(group, members)
        if self._commit_group_change(group, members, previous_profiles, previous_groups):
            QMessageBox.information(self, "รีเซ็ตกลุ่มแล้ว", f"รีเซ็ตความคืบหน้า {len(members)} เรื่องแล้ว โดยคงเป้ากลุ่มไว้")

    def _reset_goal(self, profile: NovelProfile):
        group = self._group_for_profile(profile)
        group_target = group.default_goal_chapters if group else None
        if isinstance(group_target, bool) or not isinstance(group_target, int) or group_target <= 0:
            group_target = None
        target = group_target if group_target else profile.translation_goal_target
        if target is None:
            return
        answer = QMessageBox.question(
            self,
            "รีเซ็ตความคืบหน้าเป้าหมาย",
            f"เริ่มเป้าหมาย {target} บทใหม่จากบท {profile.chapter_state.current_chapter} ใช่ไหม?\n\nจำนวนบทที่แปลรายวันจะไม่ถูกลบ",
        )
        if answer != QMessageBox.Yes:
            return
        if group_target:
            profile.translation_goal_target = group_target
        reset_goal_progress(profile, target)
        try:
            self.repo.save_profile(profile)
        except OSError as exc:
            QMessageBox.warning(self, "รีเซ็ตเป้าหมายไม่สำเร็จ", str(exc))
            return
        self.profiles = self.refresh_callback()
        self.groups = self.repo.load_groups()
        self.refresh()

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
