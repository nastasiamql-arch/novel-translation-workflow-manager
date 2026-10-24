"""Modern library layout, Unicode, persistence, and filtered reorder regressions."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPointF, Qt, QSize
from PySide6.QtGui import QDropEvent, QPixmap, QPainter
from PySide6.QtWidgets import QApplication, QListWidget, QListWidgetItem, QStyleOptionViewItem

from novel_workflow.models import AppSettings
from novel_workflow.profile_list import ProfileItemDelegate, ReorderableProfileList
from novel_workflow.storage import ProjectRepository


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def make_library(count=5):
    view = ReorderableProfileList()
    view.setObjectName("novelLibrary")
    view.setItemDelegate(ProfileItemDelegate(view))
    view.setIconSize(QSize(222, 296))
    view.set_library_view("gallery")
    for i in range(count):
        item = QListWidgetItem("มหากาพย์แห่งราชวงศ์ 中文 日本語 English " * 4)
        item.setData(Qt.UserRole, str(i))
        item.setData(Qt.UserRole + 1, ("translating", "paused", "caught_up", "checking_web")[i % 4])
        item.setData(Qt.UserRole + 3, f"แปลสำเร็จ {i} บท")
        view.addItem(item)
    return view


@pytest.mark.parametrize("count", [5, 20, 50, 100])
@pytest.mark.parametrize("mode", ["gallery", "list"])
@pytest.mark.parametrize("width", [610, 900, 1280])
def test_responsive_visible_rectangles(app, count, mode, width):
    view = make_library(count)
    view.set_library_view(mode)
    view.resize(width, 600)
    view.show()
    app.processEvents()
    delegate = view.itemDelegate()
    rects = []
    for i in range(min(count, 16)):
        rectangle = view.visualItemRect(view.item(i))
        if rectangle.isEmpty() or not rectangle.intersects(view.viewport().rect()):
            continue
        regions = delegate.card_rects(
            rectangle, title_text=view.item(i).text())
        for name in ("cover", "title", "status", "progress"):
            assert rectangle.contains(regions[name]), (mode, name, rectangle, regions[name])
        for first, second in (("cover", "title"), ("title", "status"), ("status", "progress")):
            assert not regions[first].intersects(regions[second]), (first, second)
        assert rectangle.right() < view.viewport().width()
        rects.append(rectangle)
    assert all(not a.intersects(b) for j, a in enumerate(rects) for b in rects[j+1:])
    view.close()


@pytest.mark.parametrize("title", [
    "เรื่องสั้น", "ก" * 50, "มหากาพย์แห่งราชวงศ์" * 10,
    "ราชันย์อสูร" * 20, "ไทย English 123 中文 日本語" * 8,
    "เทพยุทธ์ 😀🌟 特殊文字", "คำไกลมากโดยไม่เว้นวรรค" * 14,
    "บทที่ 1\nบทที่ 2",
])
@pytest.mark.parametrize("mode", ["gallery", "list"])
def test_unicode_title_only_painted_inside_its_region(app, title, mode):
    view = make_library(1)
    view.set_library_view(mode)
    view.item(0).setText(title)
    view.item(0).setData(Qt.AccessibleDescriptionRole, title)
    view.resize(900, 600)
    view.show()
    app.processEvents()
    rect = view.visualItemRect(view.item(0))
    areas = view.itemDelegate().card_rects(rect, title_text=title)
    assert areas["title"].bottom() < areas["status"].top()
    assert areas["status"].bottom() < areas["progress"].top()
    assert view.item(0).data(Qt.AccessibleDescriptionRole) == title
    image = QPixmap(rect.size())
    image.fill(Qt.transparent)
    painter = QPainter(image)
    option = QStyleOptionViewItem()
    option.rect = image.rect()
    option.font = view.font()
    option.palette = view.palette()
    view.itemDelegate().paint(painter, option, view.model().index(0, 0))
    painter.end()
    assert not image.isNull()
    view.close()


def test_gallery_list_switch_does_not_replace_items_or_ids(app):
    view = make_library(20)
    identities = [view.item(i) for i in range(view.count())]
    for mode in ("list", "gallery", "list"):
        view.set_library_view(mode)
        assert [view.item(i) for i in range(view.count())] == identities
        assert [view.item(i).data(Qt.UserRole) for i in range(view.count())] == [
            str(i) for i in range(20)]
    view.close()


def test_reorder_filtered_view_keeps_hidden_profile_slots(app):
    view = make_library(5)
    view.resize(900, 600)
    view.item(1).setHidden(True)
    view.item(3).setHidden(True)
    view.show()
    app.processEvents()
    view.setCurrentRow(0)
    view._drag_profile_id = "0"
    last = view.item(4)
    rect = view.visualItemRect(last)
    event = QDropEvent(QPointF(rect.bottomRight()), Qt.MoveAction,
                       view.mimeData([view.item(0)]), Qt.LeftButton, Qt.NoModifier)
    emitted = []
    view.orderChanged.connect(emitted.append)
    view.dropEvent(event)
    assert event.isAccepted()
    ids = [view.item(i).data(Qt.UserRole) for i in range(view.count())]
    assert ids == ["2", "1", "4", "3", "0"], ids
    assert emitted == [ids]
    view.close()


def test_library_view_preference_roundtrip_in_legacy_settings(tmp_path):
    repo = ProjectRepository(tmp_path)
    original = repo.load_settings()
    assert original.library_view_mode == "gallery"
    original.library_view_mode = "list"
    repo.save_settings(original)
    assert repo.load_settings().library_view_mode == "list"
    assert AppSettings().library_view_mode == "gallery"


def test_no_fabricated_fraction_when_unknown_total(app):
    view = make_library(1)
    card = view.item(0)
    card.setData(Qt.UserRole + 3, "แปลสำเร็จ 350 บท")
    card.setData(Qt.UserRole + 4, None)
    regions = view.itemDelegate().card_rects(
        __import__("PySide6.QtCore", fromlist=["QRect"]).QRect(
            0, 0, view.itemDelegate().card_size().width(),
            view.itemDelegate().card_size().height()))
    assert not regions["bar"].intersects(regions["progress"])
    assert card.data(Qt.UserRole + 4) is None
    view.close()


@pytest.mark.parametrize("title", [
    "สั้น", "ก" * 120, "ไร้ช่องว่างภาษาไทย" * 9,
    "ไทย English 2026 中文 日本語 😊 #[]!" * 3,
])
def test_compact_gallery_metadata_follows_visible_title(app, title):
    view = make_library(1)
    view.item(0).setText(title)
    view.resize(900, 620)
    view.show()
    app.processEvents()
    delegate = view.itemDelegate()
    rect = view.visualItemRect(view.item(0))
    regions = delegate.card_rects(rect, title_text=title)
    assert rect.contains(regions["card"])
    assert regions["card"].contains(regions["progress"])
    assert regions["card"].contains(regions["bar"])
    assert regions["title"].bottom() < regions["status"].top()
    assert 0 < regions["status"].top() - regions["title"].bottom() <= 10
    assert 0 < regions["progress"].top() - regions["status"].bottom() <= 9
    assert regions["card"].bottom() - regions["bar"].bottom() >= 10
    assert len(delegate.title_lines(title, view.font(), regions["title"].width())) >= 1
    view.close()


def test_gallery_title_is_one_line_and_metadata_aligns_for_every_card(app):
    view = make_library(3)
    titles = [
        "เรื่องสั้น",
        "ย้อนเวลากลับมาปี 2010 คราวนี้ผมจะกุมเกมเศรษฐกิจโลก",
        "มหากาพย์แห่งดวงดาว" * 12,
    ]
    for item, title in zip((view.item(i) for i in range(3)), titles):
        item.setText(title)
        item.setToolTip(title)
    view.resize(1500, 700)
    view.show()
    app.processEvents()

    delegate = view.itemDelegate()
    assert delegate.MAX_TITLE_LINES == 1
    assert delegate.card_size().width() == 320
    regions = [delegate.card_rects(view.visualItemRect(view.item(i)), title_text=titles[i])
               for i in range(3)]
    line_height = view.fontMetrics().lineSpacing() + 4
    assert all(region["title"].height() == line_height for region in regions)
    assert len({region["title"].top() for region in regions}) == 1
    assert len({region["status"].top() for region in regions}) == 1
    assert len({region["progress"].top() for region in regions}) == 1
    assert len(delegate.title_lines(titles[2], view.font(), regions[2]["title"].width())) > 1
    assert view.item(2).toolTip() == titles[2]
    view.close()


def test_gallery_cells_have_real_gutters_and_resize_without_overflow(app):
    view = make_library(20)
    for width in (610, 900, 1280):
        view.resize(width, 720)
        view.show()
        app.processEvents()
        assert view.gridSize().width() == (
            view.itemDelegate().card_size().width() + view.itemDelegate().CELL_GAP)
        visible = [(view.visualItemRect(view.item(i)),
                    view.itemDelegate().card_rects(
                        view.visualItemRect(view.item(i)),
                        title_text=view.item(i).text())["card"])
                   for i in range(view.count())]
        visible = [(cell, card) for cell, card in visible
                   if cell.intersects(view.viewport().rect())]
        for index, (cell, card) in enumerate(visible):
            assert cell.contains(card)
            assert card.right() < view.viewport().width()
            for other_cell, other_card in visible[index + 1:]:
                if cell.top() == other_cell.top():
                    assert abs(card.left() - other_card.right()) >= 16 or (
                        abs(other_card.left() - card.right()) >= 16)
                assert not card.intersects(other_card)
    view.close()


def test_status_tab_selected_label_never_elides_and_filters_keep_keys(app):
    from PySide6.QtGui import QFont, QFontMetrics
    from PySide6.QtWidgets import QTabBar
    from novel_workflow.library_page import CompactLibraryTabBar
    from novel_workflow.theme import application_stylesheet
    bar = CompactLibraryTabBar()
    bar.setObjectName("libraryStatusTabs")
    bar.setStyleSheet(application_stylesheet("Dark"))
    bar.setExpanding(False)
    bar.setUsesScrollButtons(True)
    bar.setElideMode(Qt.ElideNone)
    names = [
        ("translating", "กำลังแปล (5)"),
        ("paused", "พักแปล (12)"),
        ("caught_up", "ชนต้นฉบับแล้ว (123)"),
        ("checking_web", "กำลังเช็กกับเว็บ (0)"),
    ]
    for key, label in names:
        index = bar.addTab(label)
        bar.setTabData(index, key)
    for width in (330, 580, 1050):
        bar.resize(width, 60)
        bar.show()
        app.processEvents()
        for i, (key, label) in enumerate(names):
            font = QFont(bar.font())
            font.setBold(True)
            assert bar.tabSizeHint(i).width() >= (
                QFontMetrics(font).horizontalAdvance(label) + 48)
            assert bar.tabText(i) == label
            assert bar.tabData(i) == key
            bar.setCurrentIndex(i)
            app.processEvents()
            assert bar.tabRect(i).width() >= bar.tabSizeHint(i).width()
            assert not bar.tabRect(i).isEmpty()
    bar.close()
