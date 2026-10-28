"""Read-only, novel-scoped compact summary of the existing TranslationPlanner."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QProgressBar, QSizePolicy, QToolButton,
    QVBoxLayout,
)

from .theme import theme_colors
from .translation_planner import TranslationPlanner


def today_plan_snapshot(planner, profile, day=None):
    """Use the same precedence as TodayPage: story schedule, then daily plan.

    Actual counts always come from the planner's confirmed Translator exports.
    No plan or activity is ever written by this view.
    """
    local_day = day or date.today()
    key = local_day.isoformat()
    scheduled = planner.story_schedule(profile.id)
    if scheduled is not None:
        info = planner.story_day_rows(profile.id, local_day)
        if info is None:
            raise ValueError("Missing profile for translation schedule")
        row = next((item for item in info["rows"] if item["date"] == key), None)
        if row is not None:
            if row["rest"]:
                return {"status": "rest", "completed": row["actual"], "target": None}
            if row["target"] > 0:
                return {"status": "active", "completed": row["actual"],
                        "target": row["target"]}
            # A zero-target day outside the rest calendar is not a fictitious goal.
            return {"status": "focus", "completed": row["actual"], "target": None}
    summary = planner.summary(local_day, [profile], profile_id=profile.id)
    status = summary["status"]
    if status == "rest":
        return {"status": "rest", "completed": 0, "target": None}
    if status == "empty":
        return {"status": "empty", "completed": 0, "target": None}
    if status != "active" or summary["profile"].id != profile.id:
        raise ValueError("Planner profile or state does not match the workspace")
    plan_type = summary["plan"]["plan_type"]
    target = summary["plan"].get("target_chapters") if plan_type == "daily" else None
    if target is not None and (type(target) is not int or target <= 0):
        raise ValueError("Invalid daily target")
    return {"status": "active" if target is not None else "focus",
            "completed": summary["today_count"], "target": target}


def today_plan_labels(snapshot):
    """Return text and bar value without inventing percentages or clipping excess."""
    status = snapshot["status"]
    if status == "error":
        return "อ่านแผนวันนี้ไม่ได้", "ตรวจสอบข้อมูลแผน", "", None
    if status == "empty":
        return "ยังไม่มีแผนวันนี้", "ตั้งแผนเพื่อเริ่มต้น", "", None
    if status == "rest":
        return "วันนี้เป็นวันพัก", "", "", None
    completed = snapshot["completed"]
    target = snapshot["target"]
    if target is None:
        return f"วันนี้แปลสำเร็จ {completed:,} บท", "โฟกัสวันนี้", "", None
    remaining = max(0, target - completed)
    percent = min(100, round(completed * 100 / target))
    excess = max(0, completed - target)
    detail = (f"เกินเป้า {excess:,} บท" if excess
              else "ครบเป้าหมายแล้ว" if not remaining
              else f"เหลือ {remaining:,} บท")
    return (f"วันนี้ {completed:,} / {target:,} บท",
            detail, f"{percent}%", percent)


class TodayPlanBar(QFrame):
    """One widget per WorkspacePage, shared by Editor, Vocabulary and Translation."""

    def __init__(self, repo, profile_id, open_plan, parent=None):
        super().__init__(parent)
        self.repo = repo
        self.profile_id = profile_id
        self.planner = TranslationPlanner(repo)
        self.setObjectName("todayPlanBar")
        self.snapshot = {"status": "empty", "completed": 0, "target": None}
        self._last_day = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(5)
        line = QHBoxLayout()
        line.setSpacing(9)
        self.title = QLabel()
        self.title.setObjectName("todayPlanTitle")
        self.title.setMinimumWidth(0)
        self.title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.detail = QLabel()
        self.detail.setObjectName("todayPlanRemaining")
        self.percent = QLabel()
        self.percent.setObjectName("todayPlanPercent")
        self.open_button = QToolButton(self)
        self.open_button.setObjectName("todayPlanOpen")
        self.open_button.setCursor(Qt.PointingHandCursor)
        self.open_button.clicked.connect(open_plan)
        line.addWidget(self.title, 1)
        line.addWidget(self.detail)
        line.addWidget(self.percent)
        line.addWidget(self.open_button)
        layout.addLayout(line)
        self.progress = QProgressBar()
        self.progress.setObjectName("todayPlanProgress")
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 100)
        self.progress.setFixedHeight(7)
        layout.addWidget(self.progress)
        self.apply_appearance("Light")
        self._display()

    def apply_appearance(self, appearance):
        c = theme_colors(appearance)
        self.setStyleSheet(
            "QFrame#todayPlanBar {"
            f"background: {c['surface']}; border: 1px solid {c['border']};"
            "border-radius: 5px; }"
            "QFrame#todayPlanBar QLabel { border: none; background: transparent; }"
            f"QLabel#todayPlanTitle {{ color: {c['text']}; font-weight: 600; }}"
            f"QLabel#todayPlanRemaining, QLabel#todayPlanPercent {{ color: {c['secondary']}; }}"
            f"QToolButton#todayPlanOpen {{ color: {c['accent']}; border: none; padding: 2px 5px; }}"
            f"QProgressBar#todayPlanProgress {{ background: {c['surface2']};"
            "border: none; border-radius: 3px; }"
            "QProgressBar#todayPlanProgress::chunk { background: #80ADFF;"
            "border-radius: 3px; }"
        )

    def refresh(self, profile, day=None):
        if profile.id != self.profile_id:
            return
        self._last_day = day or date.today()
        try:
            self.snapshot = today_plan_snapshot(self.planner, profile, self._last_day)
        except (OSError, ValueError, TypeError, KeyError, OverflowError) as exc:
            self.snapshot = {"status": "error", "completed": 0, "target": None}
            self.setToolTip(f"ไม่สามารถอ่านข้อมูล Planner: {exc}")
        else:
            self.setToolTip("")
        self._display()

    def _display(self):
        title, detail, percent, progress = today_plan_labels(self.snapshot)
        self.title.setText(title)
        self.title.setToolTip(title)
        self.detail.setText(detail)
        self.detail.setToolTip(detail)
        self.percent.setText(percent)
        self.progress.setVisible(progress is not None)
        if progress is not None:
            self.progress.setValue(progress)
        empty = self.snapshot["status"] == "empty"
        self.open_button.setText("ตั้งแผน ›" if empty else "ดูแผน ›")
        self.open_button.setAccessibleName("ตั้งแผนการแปล" if empty else "ดูแผนการแปล")
        self._fit_width()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_width()

    def _fit_width(self):
        narrow = self.width() < 540
        self.detail.setVisible(bool(self.detail.text()) and not narrow)
        self.percent.setVisible(bool(self.percent.text()) and not narrow)
        if narrow:
            title, detail, percent, _ = today_plan_labels(self.snapshot)
            self.title.setToolTip(" · ".join(part for part in (title, detail, percent) if part))
