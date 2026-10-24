"""Regressions for localized Gregorian storage and novel card geometry."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from datetime import date

import pytest
from PySide6.QtCore import QDate, QRect, QSize, Qt
from PySide6.QtGui import QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QListWidget, QListWidgetItem, QStyleOptionViewItem

from novel_workflow.thai_date_picker import ThaiDatePicker, THAI_MONTHS, buddhist_date_text
from novel_workflow.profile_list import ProfileItemDelegate, ReorderableProfileList
from novel_workflow.story_planner_page import StoryPlannerPage
from novel_workflow.translation_planner_page import TodayPage
from novel_workflow.storage import ProjectRepository
from novel_workflow.models import NovelProfile
from novel_workflow.translation_planner import TranslationPlanner


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("month,word", list(enumerate(THAI_MONTHS, 1)))
def test_all_month_names_and_year_are_thai(month, word):
    assert buddhist_date_text(QDate(2026, month, 24)) == f"24 {word} 2569"


def test_picker_changes_iso_only_and_calendar_selection(app):
    picker = ThaiDatePicker()
    changed = []
    picker.dateChanged.connect(lambda value: changed.append(value.toString(Qt.ISODate)))
    for source, display in [
        ("2024-02-29", "29 กุมภาพันธ์ 2567"),
        ("2026-10-24", "24 ตุลาคม 2569"),
        ("2027-01-01", "1 มกราคม 2570"),
    ]:
        picker.setDate(QDate.fromString(source, Qt.ISODate))
        assert picker.display.text() == display
        assert picker.date().toString(Qt.ISODate) == source
    assert changed == ["2024-02-29", "2026-10-24", "2027-01-01"]
    assert picker.width() <= 350 or picker.sizeHint().width() <= 350
    assert picker.display.fontMetrics().horizontalAdvance(
        "28 พฤศจิกายน 2569") <= picker.display.width() - 20
    picker.show()
    app.processEvents()
    picker.open_calendar()
    app.processEvents()
    assert picker._popup is not None
    calendar = picker._popup.findChild(__import__(
        "PySide6.QtWidgets", fromlist=["QCalendarWidget"]).QCalendarWidget)
    calendar.clicked.emit(QDate(2028, 2, 29))
    app.processEvents()
    assert picker.date().toString(Qt.ISODate) == "2028-02-29"
    assert picker._popup is None
    picker.close()


def test_planner_pages_use_localized_pickers_without_mutating_storage(app, tmp_path):
    repo = ProjectRepository(tmp_path)
    profile = NovelProfile(name="นิยายหนึ่ง")
    repo.save_profile(profile)
    story = StoryPlannerPage(repo, profile.id)
    today = TodayPage(repo)
    try:
        assert isinstance(story.start, ThaiDatePicker)
        assert isinstance(story.deadline, ThaiDatePicker)
        assert isinstance(today.day, ThaiDatePicker)
        story.final.setValue(50)
        story.days.setValue(3)
        story.start.setDate(QDate(2026, 10, 24))
        story._save()
        assert TranslationPlanner(repo).story_schedule(profile.id)["start_day"] == "2026-10-24"
        story.refresh()
        assert story.start.display.text() == "24 ตุลาคม 2569"
        today.day.setDate(QDate(2026, 10, 24))
        assert today.day.date().toPython() == date(2026, 10, 24)
    finally:
        story.close()
        today.close()


@pytest.mark.parametrize("title", [
    "ชื่อเรื่องสั้น",
    "ก"*150,
    "มหากาพย์แห่งดวงดาว"*8,
    "ภาษาไทย English 123 中文 日本語"*7,
    "ชื่อแปลก 😀🌟#~!@[]\nบทที่หนึ่ง",
])
def test_library_card_text_is_in_exclusive_rectangles(app, title):
    view = ReorderableProfileList()
    view.setObjectName("novelLibrary")
    view.setViewMode(QListWidget.IconMode)
    view.setIconSize(QSize(156, 208))
    delegate = ProfileItemDelegate(view)
    view.setItemDelegate(delegate)
    view.setGridSize(delegate.card_size())
    item = QListWidgetItem(title)
    item.setData(Qt.UserRole + 2, "กำลังแปล · สำเร็จ 30 บท")
    item.setData(Qt.UserRole, "novel-a")
    item.setData(Qt.AccessibleDescriptionRole, title)
    view.addItem(item)
    view.resize(900, 600)
    view.show()
    app.processEvents()
    rect = view.visualItemRect(item)
    assert rect.width() >= 156 and rect.height() >= delegate.card_size().height()
    areas = delegate.card_rects(rect, title_text=title)
    assert not areas["cover"].intersects(areas["title"])
    assert not areas["title"].intersects(areas["status"])
    assert rect.contains(areas["cover"]) and rect.contains(areas["title"])
    assert rect.contains(areas["status"])
    expected_lines = min(delegate.MAX_TITLE_LINES, len(
        delegate.title_lines(title, view.font(), areas["title"].width())))
    assert areas["title"].height() == expected_lines * (
        view.fontMetrics().lineSpacing() + 4)
    wrapped = delegate.title_lines(title, view.font(), areas["title"].width())
    assert wrapped
    assert item.data(Qt.AccessibleDescriptionRole) == title
    image = QPixmap(rect.size())
    image.fill(Qt.transparent)
    painter = QPainter(image)
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, rect.width(), rect.height())
    option.font = view.font()
    option.palette = view.palette()
    delegate.paint(painter, option, view.model().index(0, 0))
    painter.end()
    assert not image.isNull()
    view.close()


def test_neighboring_cards_and_order_ids_are_independent(app):
    view = ReorderableProfileList()
    view.setObjectName("novelLibrary")
    view.setViewMode(QListWidget.IconMode)
    view.setFlow(QListWidget.LeftToRight)
    view.setWrapping(True)
    view.setSpacing(18)
    view.setIconSize(QSize(156, 208))
    delegate = ProfileItemDelegate(view)
    view.setItemDelegate(delegate)
    view.setGridSize(delegate.card_size())
    for number in range(5):
        item = QListWidgetItem("เรื่องยาวไม่มีช่องว่าง"*7)
        item.setData(Qt.UserRole, f"novel-{number}")
        view.addItem(item)
    view.resize(900, 600)
    view.show()
    app.processEvents()
    rectangles = [view.visualItemRect(view.item(i)) for i in range(5)]
    assert all(not a.intersects(b) for n, a in enumerate(rectangles)
               for b in rectangles[n + 1:])
    assert [view.item(i).data(Qt.UserRole) for i in range(5)] == [
        f"novel-{i}" for i in range(5)]
    assert view.dragEnabled() and view.acceptDrops()
    view.close()
