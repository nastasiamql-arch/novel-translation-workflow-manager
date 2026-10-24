"""Thai novel-scoped story translation schedule view."""
from __future__ import annotations
from datetime import date
from PySide6.QtCore import Qt, QDate
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QSpinBox,
    QDateEdit, QFormLayout, QPushButton, QMessageBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView,
)
from .translation_planner import TranslationPlanner


class StoryPlannerPage(QWidget):
    def __init__(self, repo, profile_id, parent=None):
        super().__init__(parent)
        self.profile_id = profile_id
        self.planner = TranslationPlanner(repo)
        layout = QVBoxLayout(self)
        self.heading = QLabel("แผนการแปล")
        self.heading.setObjectName("pageTitle")
        layout.addWidget(self.heading)
        form = QFormLayout()
        self.mode = QComboBox()
        for key, label in (("duration", "แปลให้จบภายใน X วัน"), ("daily", "แปลวันละ X บท"), ("deadline", "กำหนดวันครบกำหนด")):
            self.mode.addItem(label, key)
        form.addRow("รูปแบบแผน", self.mode)
        self.final = QSpinBox()
        self.final.setRange(1, 2147483647)
        form.addRow("บทสุดท้าย", self.final)
        self.days = QSpinBox()
        self.days.setRange(1, 3650)
        form.addRow("จำนวนวันทำงาน", self.days)
        self.daily = QSpinBox()
        self.daily.setRange(1, 100000)
        form.addRow("บทต่อวัน", self.daily)
        self.start = QDateEdit()
        self.start.setCalendarPopup(True)
        self.start.setDate(QDate.currentDate())
        form.addRow("เริ่มวันที่", self.start)
        self.deadline = QDateEdit()
        self.deadline.setCalendarPopup(True)
        self.deadline.setDate(QDate.currentDate().addDays(7))
        form.addRow("วันครบกำหนด", self.deadline)
        self.rest = QComboBox()
        self.rest.addItems(("ไม่มีวันพัก", "เสาร์–อาทิตย์", "วันอาทิตย์", "วันเสาร์"))
        form.addRow("พักประจำ", self.rest)
        layout.addLayout(form)
        self.mode.currentIndexChanged.connect(self._update_mode)
        save = QPushButton("บันทึกแผน")
        save.setObjectName("primaryButton")
        save.clicked.connect(self._save)
        layout.addWidget(save)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(("วันที่", "เป้าหมาย", "สำเร็จจริง", "สถานะ"))
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.table, 1)
        controls = QHBoxLayout()
        self.target = QSpinBox()
        self.target.setRange(0, 2147483647)
        self.target.setSpecialValueText("วันพัก")
        controls.addWidget(self.target)
        edit = QPushButton("แก้เป้าหมายวันที่เลือก")
        edit.clicked.connect(self._override)
        controls.addWidget(edit)
        layout.addLayout(controls)
        self.history = QLabel()
        layout.addWidget(self.history)
        self.refresh()

    def _update_mode(self, *_):
        mode = self.mode.currentData()
        self.days.setEnabled(mode == "duration")
        self.daily.setEnabled(mode == "daily")
        self.deadline.setEnabled(mode == "deadline")

    def _save(self):
        rest = ((), (5, 6), (6,), (5,))[self.rest.currentIndex()]
        mode = self.mode.currentData()
        try:
            self.planner.save_story_schedule(
                self.profile_id, mode, final_chapter=self.final.value(),
                start_day=self.start.date().toPython(),
                duration_days=self.days.value() if mode == "duration" else None,
                daily_target=self.daily.value() if mode == "daily" else None,
                deadline=self.deadline.date().toPython() if mode == "deadline" else None,
                rest_weekdays=rest)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "บันทึกแผนไม่สำเร็จ", str(exc))
            return
        self.refresh()

    def _override(self):
        row = self.table.currentRow()
        if row < 0:
            return
        day = self.table.item(row, 0).text()
        try:
            self.planner.override_story_day(self.profile_id, day, self.target.value())
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "แก้แผนไม่สำเร็จ", str(exc))
            return
        self.refresh()

    def refresh(self):
        info = self.planner.story_day_rows(self.profile_id)
        if info is None:
            self.summary.setText("ระบุบทสุดท้าย แล้วบันทึกแผนเพื่อเริ่มใช้งาน")
            self.table.setRowCount(0)
            self._update_mode()
            return
        plan = info["schedule"]
        self.heading.setText("แผนการแปล · " + info["profile"].name)
        self.mode.setCurrentIndex(self.mode.findData(plan["mode"]))
        self.final.setValue(plan["final_chapter"])
        self.days.setValue(plan.get("duration_days") or 3)
        self.daily.setValue(plan.get("daily_target") or 20)
        self.start.setDate(QDate.fromString(plan["start_day"], Qt.ISODate))
        if plan.get("deadline"):
            self.deadline.setDate(QDate.fromString(plan["deadline"], Qt.ISODate))
        rest = tuple(plan.get("rest_weekdays", ()))
        choices = ((), (5, 6), (6,), (5,))
        self.rest.setCurrentIndex(choices.index(rest) if rest in choices else 0)
        self.summary.setText(
            f"แปลแล้ว {info['completed']} / {plan['final_chapter']} บท · "
            f"เหลือ {info['remaining']} บท · {info['percent']}%")
        self.table.setRowCount(len(info["rows"]))
        for index, item in enumerate(info["rows"]):
            for col, value in enumerate((item["date"], item["target"], item["actual"], item["status"])):
                self.table.setItem(index, col, QTableWidgetItem(str(value)))
        self.history.setText(f"ประวัติการแก้ไขแผน {len(plan.get('history', []))} รายการ")
        self._update_mode()
