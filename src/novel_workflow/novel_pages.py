"""Novel-bound resources and verified translation progress views.

These are views of existing working files and export ledgers, not duplicate stores.
"""
from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QListWidget, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QHeaderView,
    QAbstractItemView,
)

from .translation_planner import TranslationPlanner
from .translation_progress import completed_chapters, confirmed_daily_activity


class NovelResourcesPage(QWidget):
    """Unified entry point for one novel's context, workflow and working files."""

    def __init__(self, owner, profile_id, parent=None):
        super().__init__(parent)
        self.owner = owner
        self.profile_id = profile_id
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        self.heading = QLabel("ไฟล์และคำศัพท์")
        self.heading.setObjectName("pageTitle")
        root.addWidget(self.heading)
        actions = QHBoxLayout()
        for name, handler in (
            ("จัดการไฟล์", owner.file_manager),
            ("คลังคำศัพท์", owner.show_vocabulary_files),
            ("เลือก Context", owner.set_context_file),
            ("จัดการขั้นตอน", owner.settings_dialog),
        ):
            button = QPushButton(name)
            button.clicked.connect(
                lambda checked=False, fn=handler: self._activate(fn)
            )
            actions.addWidget(button)
        actions.addStretch()
        root.addLayout(actions)
        self.listing = QListWidget()
        self.listing.setObjectName("novelResourceList")
        root.addWidget(self.listing, 1)
        self.refresh()

    def _activate(self, handler):
        if not self.owner.profile or self.owner.profile.id != self.profile_id:
            return
        handler()

    def refresh(self):
        profile = next(
            (p for p in self.owner.repo.list_profiles() if p.id == self.profile_id), None
        )
        self.listing.clear()
        if profile is None:
            self.heading.setText("ไม่พบนิยาย")
            return
        self.heading.setText(f"ไฟล์และคำศัพท์ · {profile.name}")
        if profile.context_path:
            self.listing.addItem(f"ข้อมูลประกอบการแปล  ·  {profile.context_path}")
        for item in sorted(profile.working_files, key=lambda f: f.order):
            self.listing.addItem(f"ไฟล์ทำงาน  ·  {item.path}")
        for step in profile.workflow.steps:
            for item in step.files:
                self.listing.addItem(
                    f"{step.name}  ·  {item.label or item.path or item.dynamic_reference}"
                )
        vocabulary = profile.vocabulary_step
        if vocabulary:
            for item in vocabulary.files:
                self.listing.addItem(
                    f"คลังคำศัพท์  ·  {item.label or item.path or item.dynamic_reference}"
                )
        if not self.listing.count():
            self.listing.addItem("ยังไม่มีไฟล์ที่เชื่อมไว้กับนิยายเรื่องนี้")


class NovelProgressPage(QWidget):
    """Read-only novel-scoped completion and activity sourced from confirmed exports."""

    def __init__(self, repo, profile_id, parent=None):
        super().__init__(parent)
        self.repo, self.profile_id = repo, profile_id
        self.planner = TranslationPlanner(repo)
        root = QVBoxLayout(self)
        self.heading = QLabel("ความคืบหน้า")
        self.heading.setObjectName("pageTitle")
        root.addWidget(self.heading)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)
        self.activity = QTableWidget(0, 3)
        self.activity.setHorizontalHeaderLabels(("วันที่", "บทที่สำเร็จจริง", "เป้าหมาย"))
        self.activity.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.activity.setEditTriggers(QAbstractItemView.NoEditTriggers)
        root.addWidget(self.activity, 1)
        self.history = QLabel()
        self.history.setWordWrap(True)
        root.addWidget(self.history)
        self.refresh()

    def refresh(self):
        profile = next(
            (p for p in self.repo.list_profiles() if p.id == self.profile_id), None
        )
        if profile is None:
            self.heading.setText("ไม่พบนิยาย")
            return
        self.heading.setText(f"ความคืบหน้า · {profile.name}")
        chapters = completed_chapters(profile)
        goal = self.planner.finish_goal(profile.id) or {}
        final = goal.get("final_chapter")
        if type(final) is int and final > 0:
            completed = len({n for n in chapters if 1 <= n <= final})
            detail = f"จากทั้งหมด {final} บท · เหลือ {max(0, final - completed)} บท"
        else:
            detail = "ไม่ทราบบทสุดท้าย จึงไม่คำนวณเปอร์เซ็นต์จบเรื่อง"
        activity = confirmed_daily_activity(profile)
        today = date.today()
        today_count = len(activity.get(today.isoformat(), set()))
        week_count = sum(
            len(activity.get((today - timedelta(days=i)).isoformat(), set()))
            for i in range(7)
        )
        self.summary.setText(
            f"แปลสำเร็จ {len(chapters)} บท · {detail}\n"
            f"วันนี้ {today_count} บท · 7 วันล่าสุด {week_count} บท"
        )
        schedule = self.planner.story_day_rows(profile.id, today)
        goals = {
            row["date"]: row["target"]
            for row in (schedule or {}).get("rows", [])
        }
        days = [today - timedelta(days=offset) for offset in range(13, -1, -1)]
        self.activity.setRowCount(len(days))
        for row, day in enumerate(days):
            key = day.isoformat()
            values = (key, len(activity.get(key, set())), goals.get(key, "—"))
            for column, value in enumerate(values):
                self.activity.setItem(row, column, QTableWidgetItem(str(value)))
        self.history.setText(
            f"บันทึก Export ที่ยืนยัน {len(profile.translator_export_events)} รายการ · "
            "นับบทเดิมซ้ำเพียงครั้งเดียว"
        )
