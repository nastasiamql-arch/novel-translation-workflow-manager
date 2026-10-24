"""Capture real PySide6 offscreen Library renders on a Windows CI runner."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFontDatabase, QPainter, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from novel_workflow.main import _configure_font
from novel_workflow.models import NovelProfile
from novel_workflow.storage import ProjectRepository
from novel_workflow.workspace_window import MainWindow


NAMES = [
    "ย้อนเวลากลับมาปี 2010 คราวนี้ผมจะกุมเกมแห่งโชคชะตา",
    "มหากาพย์แห่งดวงดาวและตำนานราชันย์มังกร " * 3,
    "ชื่อเรื่องไทย 中文 日本語 English ✨ ลำดับที่ 03",
    "การผจญภัยในโลกแห่งเวทมนตร์ที่ไม่มีใครเคยรู้จักมาก่อน",
    "ก" * 145,
    "เรื่องพักแปล",
    "ชื่อเรื่องชนต้นฉบับแล้ว",
    "กำลังตรวจสอบต้นฉบับบนเว็บไซต์",
]


def create_cover(path, number):
    image = QPixmap(330, 440)
    image.fill(QColor(["#30435B", "#4B4F70", "#506B68", "#675C72"][number % 4]))
    painter = QPainter(image)
    painter.fillRect(20, 22, 290, 10, QColor("#94AFCE"))
    painter.fillRect(40, 62, 250, 4, QColor("#9CA9C7"))
    painter.setPen(QColor("#F1F5FB"))
    painter.drawText(image.rect(), Qt.AlignCenter, str(number + 1))
    painter.end()
    assert image.save(str(path))


def render_screenshot(app, window, output, name, theme, mode, width, height,
                      category=0, select_card=False):
    window.settings.appearance = theme
    window.apply_theme()
    window.resize(width, height)
    window.show_library()
    window.library_status_tabs.setCurrentIndex(category)
    button = (window.library_list_view if mode == "list"
              else window.library_gallery_view)
    button.click()
    app.processEvents()
    QTest.qWait(60)
    cards = window.profile_cards
    visible = [cards.item(i) for i in range(cards.count())
               if not cards.item(i).isHidden()]
    assert len(visible) == (5 if category == 0 else 1)
    if select_card:
        cards.setCurrentItem(visible[0])
    for item in visible:
        rect = cards.visualItemRect(item)
        regions = cards.itemDelegate().card_rects(
            rect, title_text=item.text())
        assert not regions["title"].intersects(regions["status"])
        assert not regions["status"].intersects(regions["progress"])
    tabs = window.library_status_tabs
    selected = tabs.tabRect(category)
    assert selected.width() >= tabs.tabSizeHint(category).width()
    assert tabs.tabText(category).endswith(")")
    screenshot = window.grab()
    assert not screenshot.isNull()
    assert screenshot.save(str(output / f"{name}.png"))
    print(f"rendered {name}: {screenshot.size().width()}x{screenshot.size().height()}", flush=True)


def main():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    for filename in ("segoeui.ttf", "LeelawUI.ttf", "tahoma.ttf",
                     "msyh.ttc", "YuGothR.ttc", "seguisym.ttf"):
        if (fonts / filename).exists():
            QFontDatabase.addApplicationFont(str(fonts / filename))
    _configure_font(app)
    output = Path("test-output/library-visuals")
    output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory() as directory:
        repo = ProjectRepository(Path(directory) / "data")
        settings = repo.load_settings()
        settings.last_update_check_date = date.today().isoformat()
        repo.save_settings(settings)
        for i, name in enumerate(NAMES):
            status = "translating" if i < 5 else ("paused", "caught_up", "checking_web")[i - 5]
            profile = NovelProfile(name=name, status=status)
            repo.save_profile(profile)
            if i < 4:
                cover = repo.profile_dir(profile.id) / "cover.png"
                create_cover(cover, i)
                profile.cover_image_path = "cover.png"
                repo.save_profile(profile)
        window = MainWindow(repo)
        window.show()
        jobs = [
            ("dark-gallery", "Dark", "gallery", 1440, 860),
            ("light-gallery", "Light", "gallery", 1440, 860),
            ("dark-list", "Dark", "list", 1440, 860),
            ("light-list", "Light", "list", 1440, 860),
            ("dark-narrow", "Dark", "gallery", 900, 600),
            ("light-selected", "Light", "gallery", 1280, 720, 0, True),
            ("light-narrow", "Light", "gallery", 900, 600),
            ("dark-selected-tab", "Dark", "gallery", 900, 600),
            ("dark-selected-card", "Dark", "gallery", 1280, 720, 0, True),
            ("dark-long-thai", "Dark", "gallery", 1920, 1080),
            ("dark-last-category", "Dark", "gallery", 900, 600, 3, False),
            ("light-last-category", "Light", "gallery", 900, 600, 3, False),
        ]
        for job in jobs:
            render_screenshot(app, window, output, *job)
        window.close()
    print("Qt offscreen Library screenshot capture: PASS", flush=True)


if __name__ == "__main__":
    main()
