"""Today dashboard for manually selected translation work."""
from __future__ import annotations
from datetime import date, timedelta
from PySide6.QtCore import Qt, Signal, QDate
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QSpinBox, QDateEdit, QProgressBar, QFormLayout, QGroupBox, QMessageBox)
from .translation_planner import TranslationPlanner


class TodayPage(QWidget):
    openNovel = Signal(str)
    def __init__(self, repo, parent=None):
        super().__init__(parent)
        self.planner = TranslationPlanner(repo)
        self.repo = repo
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        self.heading = QLabel()
        self.heading.setObjectName("pageTitle")
        layout.addWidget(self.heading)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setObjectName("sectionHeading")
        layout.addWidget(self.summary)
        self.progress = QProgressBar()
        self.progress.setTextVisible(True)
        layout.addWidget(self.progress)
        actions = QHBoxLayout()
        self.open_button = QPushButton("เริ่มแปลต่อ")
        self.open_button.clicked.connect(self._open)
        actions.addWidget(self.open_button)
        self.edit_button = QPushButton("สร้างหรือแก้แผน")
        self.edit_button.clicked.connect(self._toggle_editor)
        actions.addWidget(self.edit_button)
        actions.addStretch()
        layout.addLayout(actions)
        self.editor = QGroupBox("แผนการแปล")
        form = QFormLayout(self.editor)
        self.day = QDateEdit()
        self.day.setCalendarPopup(True)
        self.day.setDate(QDate.currentDate())
        self.day.dateChanged.connect(self._load_day)
        form.addRow("วันที่", self.day)
        self.profile_combo = QComboBox()
        form.addRow("นิยาย", self.profile_combo)
        self.kind = QComboBox()
        for key, label in (("focus", "โฟกัสวันนี้"), ("daily", "เป้าหมายรายวัน"), ("finish", "แปลจนจบเรื่อง"), ("rest", "วันพัก")):
            self.kind.addItem(label, key)
        self.kind.currentIndexChanged.connect(self._update_fields)
        form.addRow("ประเภทแผน", self.kind)
        self.target = QSpinBox()
        self.target.setRange(1, 100000)
        self.target.setValue(20)
        form.addRow("เป้าหมาย (บท)", self.target)
        self.final = QSpinBox()
        self.final.setRange(0, 2147483647)
        self.final.setSpecialValueText("ยังไม่ทราบ")
        form.addRow("บทสุดท้าย", self.final)
        self.save_button = QPushButton("บันทึกแผน")
        self.save_button.clicked.connect(self._save)
        form.addRow(self.save_button)
        layout.addWidget(self.editor)
        self.editor.hide()
        self.weekly = QLabel()
        self.weekly.setWordWrap(True)
        layout.addWidget(self.weekly)
        layout.addStretch()
        self._selected_profile_id = None
        self.refresh()

    def _toggle_editor(self):
        self.editor.setVisible(not self.editor.isVisible())
        if self.editor.isVisible():
            self._load_day()

    def _update_fields(self):
        mode = self.kind.currentData()
        self.target.setEnabled(mode == "daily")
        self.final.setEnabled(mode == "finish")
        self.profile_combo.setEnabled(mode != "rest")

    def _load_day(self, *_):
        plan = self.planner.get(self.day.date().toPython())
        if not plan:
            return
        self.kind.setCurrentIndex(max(0, self.kind.findData(plan.get("plan_type"))))
        idx = self.profile_combo.findData(plan.get("profile_id"))
        if idx >= 0:
            self.profile_combo.setCurrentIndex(idx)
        if type(plan.get("target_chapters")) is int:
            self.target.setValue(plan["target_chapters"])
        if plan.get("plan_type") == "finish":
            goal = self.planner.finish_goal(plan.get("profile_id")) or {}
            self.final.setValue(goal.get("final_chapter") or 0)

    def _save(self):
        try:
            self.planner.save(
                self.day.date().toPython(), self.profile_combo.currentData(),
                self.kind.currentData(), target_chapters=self.target.value(),
                final_chapter=self.final.value() or None)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "บันทึกแผนไม่ได้", str(exc))
            return
        self.editor.hide()
        self.refresh()

    def _open(self):
        if self._selected_profile_id:
            self.openNovel.emit(self._selected_profile_id)

    def refresh(self):
        profiles = self.repo.list_profiles()
        selected = self.profile_combo.currentData()
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for profile in profiles:
            self.profile_combo.addItem(profile.name, profile.id)
        idx = self.profile_combo.findData(selected)
        if idx >= 0:
            self.profile_combo.setCurrentIndex(idx)
        self.profile_combo.blockSignals(False)
        today = date.today()
        # Refresh the editable date when local midnight passes, but leave a
        # user-selected future date alone while the editor is open.
        if not self.editor.isVisible():
            self.day.setDate(QDate.currentDate())
        self.heading.setText(f"วันนี้ — {today.strftime('%d/%m/%Y')}")
        info = self.planner.summary(today, profiles)
        self._selected_profile_id = None
        self.progress.hide()
        status = info["status"]
        if status == "empty":
            self.summary.setText("ยังไม่มีแผนสำหรับวันนี้ กดสร้างหรือแก้แผนเพื่อเริ่มต้น")
        elif status == "rest":
            self.summary.setText("วันนี้เป็นวันพัก")
        elif status == "missing_profile":
            self.summary.setText("ไม่พบนิยายของแผนวันนี้ กรุณาเลือกนิยายใหม่")
        else:
            profile, plan = info["profile"], info["plan"]
            self._selected_profile_id = profile.id
            mode = plan["plan_type"]
            if mode == "daily":
                target = plan["target_chapters"]
                text = f"{profile.name}\nแปลแล้ว {info['today_count']}/{target} บท · เหลือ {info['remaining']} บท"
                if info.get("excess"):
                    text += f" · เกินเป้า {info['excess']} บท"
            elif mode == "finish":
                text = f"{profile.name}\nแปลสำเร็จปัจจุบัน {info['completed_total']} บท"
                if "final_chapter" in info:
                    text += f" · ค้าง {info['remaining']} บทจากทั้งหมด {info['final_chapter']}"
                else:
                    text += " · ยังไม่ระบุบทสุดท้าย"
            else:
                text = f"{profile.name}\nโฟกัสวันนี้ · แปลใหม่ {info['today_count']} บท"
            self.summary.setText(text)
            if info["percent"] is not None:
                self.progress.setValue(info["percent"])
                self.progress.show()
        self.open_button.setEnabled(self._selected_profile_id is not None)
        rows = []
        for day, plan in self.planner.week(today + timedelta(days=1)):
            if plan:
                name = next((p.name for p in profiles if p.id == plan.get("profile_id")), "ไม่พบนิยาย")
                if plan["plan_type"] == "rest":
                    name = "วันพัก"
                rows.append(f"{day}  ·  {name}")
        self.weekly.setText("แผน 7 วันถัดไป\n" + ("\n".join(rows) if rows else "ยังไม่มีแผนล่วงหน้า"))
        self._update_fields()
