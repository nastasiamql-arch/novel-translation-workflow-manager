from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from PySide6.QtCore import Qt, QSize, QEvent
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QProgressBar, QScrollArea, QSpinBox, QVBoxLayout, QWidget, QGridLayout, QLayout, QSizePolicy,
)

from .models import NovelProfile
from .storage import ProjectRepository
from .translation_progress import daily_chapter_count, goal_progress, profile_week_count, reset_goal_progress, completed_chapter_count, completion_label, completion_tooltip


class StatisticsPage(QWidget):
    """Embedded overview of chapter activity and goals for all novels."""

    def __init__(self, parent, profiles: list[NovelProfile], repo: ProjectRepository, refresh_callback):
        super().__init__(parent)
        self.profiles = profiles
        self.repo = repo
        self.refresh_callback = refresh_callback
        self._cover_cache = {}
        self._cards = []
        self._columns = 0
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.overview_scroll = QScrollArea(); self.overview_scroll.setWidgetResizable(True)
        self.overview_scroll.setObjectName('statisticsScroll')
        self.overview_scroll.setFrameShape(QFrame.NoFrame)
        self.body = QWidget()
        self.root = QVBoxLayout(self.body)
        self.root.setContentsMargins(18, 14, 18, 20)
        self.root.setSpacing(10)
        self.root.setSizeConstraint(QLayout.SetMinimumSize)
        self.overview_scroll.setWidget(self.body)
        outer.addWidget(self.overview_scroll)
        self.summary = QHBoxLayout()
        self.summary.setSpacing(10)
        self.root.addLayout(self.summary)
        self.bulk_goal_panel = QFrame()
        self.bulk_goal_panel.setObjectName("settingsCard")
        bulk_goal_layout = QGridLayout(self.bulk_goal_panel)
        bulk_goal_layout.addWidget(QLabel("เป้าหมายรอบใหม่ · เรื่องที่กำลังแปล"), 0, 0, 1, 2)
        self.bulk_goal_target = QSpinBox()
        self.bulk_goal_target.setRange(1, 100000)
        self.bulk_goal_target.setValue(10)
        self.bulk_goal_target.setSuffix(" บทต่อเรื่อง")
        bulk_goal_layout.addWidget(self.bulk_goal_target, 1, 0)
        self.bulk_goal_hint = QLabel()
        self.bulk_goal_hint.setObjectName("mutedLabel")
        self.bulk_goal_hint.setWordWrap(True)
        bulk_goal_layout.addWidget(self.bulk_goal_hint, 1, 1)
        self.bulk_goal_button = QPushButton("ตั้งให้ทุกเรื่องที่กำลังแปล")
        self.bulk_goal_button.clicked.connect(self._apply_goal_to_translating)
        bulk_goal_layout.addWidget(self.bulk_goal_button, 2, 0)
        self.clear_all_goals_button = QPushButton("ยกเลิกเป้าหมายทั้งหมด")
        self.clear_all_goals_button.setToolTip(
            "ล้างเป้าหมายทุกนิยาย โดยเก็บประวัติการแปลและความคืบหน้ารายวันไว้"
        )
        self.clear_all_goals_button.clicked.connect(self._clear_all_goals)
        bulk_goal_layout.addWidget(self.clear_all_goals_button, 2, 1)
        controls = QHBoxLayout()
        controls.setSpacing(10)
        self.goal_disclosure = QPushButton("จัดการเป้าหมาย ▾")
        self.goal_disclosure.setObjectName("statisticsDisclosure")
        self.goal_disclosure.setCheckable(True)
        self.goal_disclosure.toggled.connect(self.bulk_goal_panel.setVisible)
        controls.addWidget(self.goal_disclosure)
        self.days_panel = QFrame()
        self.days_layout = QVBoxLayout(self.days_panel)
        history_title = QPushButton("ย้อนหลัง 7 วัน ▾")
        history_title.setObjectName("statisticsDisclosure")
        history_title.setCheckable(True)
        history_title.toggled.connect(self.days_panel.setVisible)
        controls.addWidget(history_title)
        controls.addStretch(1)
        self.root.addLayout(controls)
        self.root.addWidget(self.bulk_goal_panel)
        self.bulk_goal_panel.hide()
        self.root.addWidget(self.days_panel)
        self.days_panel.hide()

        section = QHBoxLayout()
        progress_title = QLabel("ความคืบหน้ารายเรื่อง")
        progress_title.setObjectName("sectionHeading")
        section.addWidget(progress_title)
        section.addStretch(1)
        self.story_count = QLabel()
        self.story_count.setObjectName("mutedLabel")
        section.addWidget(self.story_count)
        self.root.addLayout(section)
        # Only the outer page scrolls: no nested scroll or oversized full-width rows.
        self.rows_host = QWidget()
        self.rows_host.setObjectName("progressCardsHost")
        self.rows = QGridLayout(self.rows_host)
        self.rows.setContentsMargins(0, 0, 0, 0)
        self.rows.setHorizontalSpacing(12)
        self.rows.setVerticalSpacing(12)
        self.rows.setAlignment(Qt.AlignTop)
        self.root.addWidget(self.rows_host)
        self.root.addStretch(1)
        self.scroll = self.overview_scroll  # compatibility for callers using scroll
        self.overview_scroll.viewport().installEventFilter(self)
        self.refresh()

    def set_profiles(self, profiles: list[NovelProfile]):
        self.profiles = profiles
        self.refresh()

    def eventFilter(self, watched, event):
        if watched is self.overview_scroll.viewport() and event.type() == QEvent.Resize:
            self._reflow_cards()
        return super().eventFilter(watched, event)

    def _reflow_cards(self):
        """Relayout existing widgets; resizing never recreates cards or reads files."""
        if not hasattr(self, "rows"):
            return
        margins = self.root.contentsMargins()
        width = max(0, self.overview_scroll.viewport().width() - margins.left() - margins.right())
        columns = max(1, min(4, (width + 12) // 352))
        if columns == self._columns:
            return
        self._columns = columns
        while self.rows.count():
            self.rows.takeAt(0)
        for index, card in enumerate(self._cards):
            self.rows.addWidget(card, index // columns, index % columns)
        for column in range(4):
            self.rows.setColumnStretch(column, 1 if column < columns else 0)

    def _clear(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
            elif item.layout():
                self._clear(item.layout())

    def _metric(self, title: str, value: int, unit="บท"):
        card = QFrame()
        card.setObjectName("metricCard")
        layout = QVBoxLayout(card)
        title_label = QLabel(title)
        title_label.setObjectName("metricLabel")
        number = QLabel(f"{value:,} {unit}")
        number.setObjectName("metricValue")
        layout.addWidget(title_label)
        layout.addWidget(number)
        self.summary.addWidget(card)

    def refresh(self):
        self._clear(self.summary)
        self._clear(self.days_layout)
        self._clear(self.rows)
        self._cards = []
        self._columns = 0
        self.story_count.setText(f"{len(self.profiles)} เรื่อง")
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
        self._metric("วันนี้", today_total)
        self._metric("สัปดาห์นี้", week_total)

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
            label.setMinimumHeight(label.fontMetrics().height() + 8)
            count_label = QLabel(f"{count} บท")
            count_label.setObjectName("bodyLabel")
            line.addWidget(label)
            line.addWidget(bar, 1)
            line.addWidget(count_label)
            self.days_layout.addLayout(line)

        if not self.profiles:
            self._cards.append(QLabel("ยังไม่มีนิยาย"))
        else:
            self._cards = [self._profile_row(profile, today_key) for profile in self.profiles]
        self._reflow_cards()

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
                if profile.translation_goal_target is None or profile.translator_goal_baseline is None:
                    profile.translator_goal_baseline = completed_chapter_count(profile)
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

    def _cover(self, profile: NovelProfile) -> QLabel:
        """Small cached covers: one image decode per unchanged source."""
        cover = QLabel()
        cover.setObjectName("progressCover")
        cover.setFixedSize(64, 88)
        cover.setAlignment(Qt.AlignCenter)
        path = Path(__file__).resolve().parent / "resources" / "novelworkflow.png"
        if profile.cover_image_path:
            try:
                candidate = self.repo.resolve_project_path(profile.id, profile.cover_image_path)
                if candidate.is_file():
                    path = candidate
            except (OSError, ValueError, TypeError):
                pass
        try:
            stat = path.stat()
            signature = (str(path), stat.st_mtime_ns, stat.st_size)
            pixmap = self._cover_cache.get(signature)
            if pixmap is None:
                original = QPixmap(str(path))
                if original.isNull():
                    return cover
                scaled = original.scaled(64, 88, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                pixmap = scaled.copy((scaled.width() - 64) // 2,
                                     (scaled.height() - 88) // 2, 64, 88)
                if len(self._cover_cache) >= 64:
                    self._cover_cache.clear()
                self._cover_cache[signature] = pixmap
            cover.setPixmap(pixmap)
        except (OSError, ValueError):
            pass
        return cover

    def _profile_row(self, profile: NovelProfile, today_key: str) -> QFrame:
        card = QFrame()
        card.setObjectName("progressRow")
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        root = QVBoxLayout(card)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(6)
        layout = QHBoxLayout()
        layout.setSpacing(11)
        layout.addWidget(self._cover(profile), 0, Qt.AlignTop)
        content = QVBoxLayout()
        content.setSpacing(4)

        title = QLabel(profile.name)
        title.setObjectName("progressStoryTitle")
        title.setWordWrap(True)
        title.setMaximumHeight(40)
        title.setToolTip(profile.name)
        content.addWidget(title)

        latest = QLabel(completion_label(profile))
        latest.setObjectName("progressExport")
        latest.setWordWrap(True)
        latest.setMaximumHeight(32)
        latest.setToolTip(completion_tooltip(profile))
        content.addWidget(latest)

        goal = goal_progress(profile)
        if goal:
            completed, target, percentage = goal
            count = QLabel(f"แปลสำเร็จ {completed}/{target} บท{' ✓' if completed >= target else ''}")
            count.setObjectName("progressGoalCount")
            content.addWidget(count)
            bar = QProgressBar()
            bar.setObjectName("progressGoalBar")
            bar.setRange(0, 100)
            bar.setValue(min(100, percentage))
            bar.setTextVisible(False)
            content.addWidget(bar)
        else:
            hint = QLabel("ยังไม่ได้ตั้งเป้าหมาย")
            hint.setObjectName("mutedLabel")
            content.addWidget(hint)

        content.addStretch(1)
        actions = QHBoxLayout()
        actions.setSpacing(4)
        set_goal = QPushButton("แก้เป้า" if goal else "ตั้งเป้า")
        set_goal.setObjectName("progressAction")
        has_context = bool(profile.context_path and Path(profile.context_path).expanduser().is_file())
        set_goal.setEnabled(has_context)
        if not has_context:
            set_goal.setToolTip("เลือกไฟล์ Context ของนิยายก่อน จึงจะติดตามเป้าหมายได้")
        target_input = QSpinBox()
        target_input.setRange(1, 100000)
        target_input.setValue(profile.translation_goal_target or 10)
        target_input.setPrefix("เป้า ")
        target_input.setSuffix(" บท")
        target_input.setMaximumWidth(118)
        save_goal = QPushButton("บันทึก")
        save_goal.setObjectName("progressAction")
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
        actions.addWidget(set_goal)
        actions.addWidget(target_input)
        actions.addWidget(save_goal)
        if goal:
            reset = QPushButton("รีเซ็ต")
            reset.setObjectName("progressAction")
            reset.setToolTip("เริ่มนับบทใหม่จาก Translator Export ถัดไป โดยเก็บประวัติเดิมไว้")
            reset.clicked.connect(lambda checked=False, item=profile: self._reset_goal(item))
            actions.addWidget(reset)

        details_text = None
        if profile.translation_daily_activity:
            details = QPushButton("Context ▾")
            details.setObjectName("progressAction")
            details.setCheckable(True)
            details.setToolTip("แสดงหรือซ่อนรายละเอียด Context เดิม")
            details_text = QLabel("\n".join(
                f"{day} · {len(chapters)} บท (Context)"
                for day, chapters in sorted(profile.translation_daily_activity.items())
            ))
            details_text.setObjectName("mutedLabel")
            details_text.setWordWrap(True)
            details_text.hide()
            details.toggled.connect(details_text.setVisible)
            details.toggled.connect(lambda shown, button=details:
                                    button.setText("Context ▴" if shown else "Context ▾"))
            actions.addWidget(details)
        actions.addStretch(1)
        content.addLayout(actions)
        layout.addLayout(content, 1)
        root.addLayout(layout)
        if details_text is not None:
            root.addWidget(details_text)
        return card

    def _reset_goal(self, profile: NovelProfile):
        if not goal_progress(profile):
            return
        answer = QMessageBox.question(
            self,
            "รีเซ็ตความคืบหน้าเป้าหมาย",
            f"เริ่มเป้าหมาย {profile.translation_goal_target} บทใหม่จาก Translator Export ถัดไป ใช่ไหม?\n\nจำนวนบทที่แปลรายวันจะไม่ถูกลบ",
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
        if profile.translation_goal_target is None or profile.translator_goal_baseline is None:
            profile.translator_goal_baseline = completed_chapter_count(profile)
        profile.translation_goal_target = target
        try:
            self.repo.save_profile(profile)
        except OSError as exc:
            QMessageBox.warning(self, "บันทึกเป้าหมายไม่สำเร็จ", str(exc))
            return
        self.profiles = self.refresh_callback()
        self.refresh()


TranslationDashboardDialog = StatisticsPage
