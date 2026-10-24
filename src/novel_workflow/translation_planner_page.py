"""Today dashboard for manually selected translation work."""
from __future__ import annotations
from datetime import date, timedelta
from PySide6.QtCore import Qt, Signal, QDate
from PySide6.QtGui import QPixmap
from pathlib import Path
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QSpinBox, QDateEdit, QProgressBar, QFormLayout, QGroupBox, QMessageBox, QScrollArea, QFrame)
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
        self.cover = QLabel()
        self.cover.setFixedSize(86, 116)
        self.cover.setAlignment(Qt.AlignCenter)
        self.cover.setAccessibleName('ปกนิยายหลักวันนี้')
        self.cover.hide()
        layout.addWidget(self.cover)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setObjectName("sectionHeading")
        layout.addWidget(self.summary)
        self.day_plans = QLabel()
        self.day_plans.setWordWrap(True)
        layout.addWidget(self.day_plans)
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
        self.finish_button = QPushButton("ยืนยันจบเรื่อง")
        self.finish_button.clicked.connect(self._toggle_finish)
        self.finish_button.hide()
        actions.addWidget(self.finish_button)
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
        self.profile_combo.currentIndexChanged.connect(self._change_profile)
        self.save_button = QPushButton("บันทึกแผน")
        self.save_button.clicked.connect(self._save)
        form.addRow(self.save_button)
        layout.addWidget(self.editor)
        self.editor.hide()
        self.weekly = QLabel()
        self.weekly.setWordWrap(True)
        layout.addWidget(self.weekly)
        self.story_cards = QWidget()
        self.story_cards_layout = QVBoxLayout(self.story_cards)
        self.story_scroll = QScrollArea()
        self.story_scroll.setWidgetResizable(True)
        self.story_scroll.setWidget(self.story_cards)
        layout.addWidget(self.story_scroll, 1)
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
        self.profile_combo.setEnabled(True)

    def _change_profile(self, *_):
        self._load_day()
        self.refresh()

    def _load_day(self, *_):
        plan = self.planner.get(self.day.date().toPython(), self.profile_combo.currentData())
        if not plan:
            self.kind.setCurrentIndex(self.kind.findData("focus"))
            self.target.setValue(20)
            self.final.setValue(0)
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

    def _toggle_finish(self):
        profile_id = self._selected_profile_id
        if not profile_id:
            return
        goal = self.planner.finish_goal(profile_id) or {}
        finished = goal.get("confirmed_finished") is True
        if not finished:
            answer = QMessageBox.question(
                self, "ยืนยันจบเรื่อง",
                "ยืนยันว่าการแปลเรื่องนี้จบแล้วหรือไม่? ระบบจะไม่เปลี่ยนไฟล์หรือประวัติ Export")
            if answer != QMessageBox.Yes:
                return
        try:
            self.planner.confirm_finished(profile_id, not finished)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "บันทึกสถานะไม่สำเร็จ", str(exc))
            return
        self.refresh()

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
        selected_profile = self.profile_combo.currentData()
        info = self.planner.summary(today, profiles, profile_id=selected_profile)
        names = {profile.id: profile.name for profile in profiles}
        descriptions = [f"{names.get(plan.get('profile_id'), 'ทุกเรื่อง')} · {'วันพัก' if plan.get('plan_type') == 'rest' else 'แผนการแปล'}" for plan in self.planner.plans_for_day(today)]
        self.day_plans.setText("แผนวันนี้ทุกเรื่อง: " + ("  |  ".join(descriptions) if descriptions else "ยังไม่มีแผน"))
        self._selected_profile_id = None
        self.progress.hide()
        self.finish_button.hide()
        self.cover.hide()
        self.cover.clear()
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
            if profile.cover_image_path:
                try:
                    cover_path = self.repo.resolve_project_path(profile.id, profile.cover_image_path)
                    if cover_path.is_file():
                        picture = QPixmap(str(cover_path))
                        if not picture.isNull():
                            self.cover.setPixmap(picture.scaled(self.cover.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
                            self.cover.show()
                except (OSError, ValueError):
                    pass
            mode = plan["plan_type"]
            if mode == "finish":
                self.finish_button.setText(
                    "ยกเลิกยืนยันจบเรื่อง" if info.get("confirmed_finished")
                    else "ยืนยันจบเรื่อง")
                self.finish_button.show()
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
        for day, plans in self.planner.week_all(today + timedelta(days=1)):
            for plan in plans:
                name = names.get(plan.get("profile_id"), "ทุกเรื่อง")
                if plan["plan_type"] == "rest":
                    name += " · วันพัก"
                rows.append(f"{day}  ·  {name}")
        self.weekly.setText("แผน 7 วันถัดไป\n" + ("\n".join(rows) if rows else "ยังไม่มีแผนล่วงหน้า"))
        self._refresh_cards(profiles, today)
        self._update_fields()

    def _refresh_cards(self, profiles, today):
        while self.story_cards_layout.count():
            item = self.story_cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        total_target = total_done = count = 0
        for profile in profiles:
            scheduled = self.planner.story_day_rows(profile.id, today)
            if scheduled:
                day = next((row for row in scheduled["rows"] if row["date"] == today.isoformat()), None)
                target = day["target"] if day else 0
                actual = day["actual"] if day else 0
                status = day["status"] if day else "ไม่มีแผนวันนี้"
            else:
                info = self.planner.summary(today, profiles, profile_id=profile.id)
                if info["status"] == "empty":
                    continue
                target = info["plan"].get("target_chapters") or 0
                actual = info.get("today_count", 0)
                status = "วันพัก" if info["status"] == "rest" else ("ตามแผน" if actual >= target and target else "กำลังแปล")
            count += 1
            total_target += target
            total_done += actual
            card = QFrame()
            card.setObjectName("plannerStoryCard")
            card.setProperty("profileId", profile.id)
            inner = QHBoxLayout(card)
            cover = QLabel("▤")
            cover.setFixedSize(48, 64)
            cover.setAlignment(Qt.AlignCenter)
            if profile.cover_image_path:
                try:
                    cover_path = self.repo.resolve_project_path(profile.id, profile.cover_image_path)
                    pixmap = QPixmap(str(cover_path))
                    if not pixmap.isNull():
                        cover.setPixmap(pixmap.scaled(cover.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
                except (OSError, ValueError):
                    pass
            inner.addWidget(cover)
            details = QVBoxLayout()
            name = QLabel(profile.name)
            name.setWordWrap(True)
            name.setObjectName("sectionHeading")
            details.addWidget(name)
            info_label = QLabel(f"เป้าหมาย {target} · สำเร็จจริง {actual} · เหลือ {max(0, target - actual)} บท · {status}")
            info_label.setWordWrap(True)
            details.addWidget(info_label)
            if target:
                bar = QProgressBar()
                bar.setValue(min(100, round(100 * actual / target)))
                details.addWidget(bar)
            inner.addLayout(details, 1)
            button = QPushButton("เปิดนิยาย")
            button.setProperty("profileId", profile.id)
            button.clicked.connect(lambda _checked=False, pid=profile.id: self.openNovel.emit(pid))
            inner.addWidget(button)
            self.story_cards_layout.addWidget(card)
        if not count:
            self.story_cards_layout.addWidget(QLabel("ยังไม่มีแผนของนิยาย"))
        self.story_cards_layout.addStretch()
        self.heading.setText(f"วันนี้ — {today.strftime('%d/%m/%Y')} · {count} เรื่อง · เป้า {total_target} บท · สำเร็จ {total_done} บท")
