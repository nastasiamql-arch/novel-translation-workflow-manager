import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from novel_workflow.models import NovelProfile
from novel_workflow.progress_dialog import TranslationDashboardDialog
from novel_workflow.storage import ProjectRepository


def app():
    return QApplication.instance() or QApplication([])


def test_clear_all_goals_clears_every_profile_but_keeps_progress_data(tmp_path, monkeypatch):
    app()
    repo = ProjectRepository(tmp_path / "data")
    translating = NovelProfile(
        name="กำลังแปล", status="translating", translation_goal_target=10,
        translation_goal_baseline=100,
        translation_daily_activity={"2026-10-03": [101, 102]},
    )
    paused = NovelProfile(
        name="พักแปล", status="paused", translation_goal_target=25,
        translation_goal_baseline=300,
        translation_daily_activity={"2026-10-02": [301]},
    )
    no_goal = NovelProfile(name="ยังไม่ตั้ง")
    for profile in (translating, paused, no_goal):
        repo.save_profile(profile)
    answers = []
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *_args: answers.append(_args) or QMessageBox.Yes,
    )
    dashboard = TranslationDashboardDialog(None, repo.list_profiles(), repo, repo.list_profiles)

    dashboard.clear_all_goals_button.click()

    saved = {profile.name: profile for profile in repo.list_profiles()}
    assert {name: profile.translation_goal_target for name, profile in saved.items()} == {
        "กำลังแปล": None, "พักแปล": None, "ยังไม่ตั้ง": None,
    }
    assert saved["กำลังแปล"].translation_goal_baseline == 100
    assert saved["พักแปล"].translation_goal_baseline == 300
    assert saved["กำลังแปล"].translation_daily_activity == {"2026-10-03": [101, 102]}
    assert saved["พักแปล"].translation_daily_activity == {"2026-10-02": [301]}
    assert len(answers) == 1
    assert not dashboard.clear_all_goals_button.isEnabled()


def test_clear_all_goals_can_be_cancelled_without_changing_profiles(tmp_path, monkeypatch):
    app()
    repo = ProjectRepository(tmp_path / "data")
    profile = NovelProfile(name="เรื่องมีเป้าหมาย", translation_goal_target=12,
                           translation_goal_baseline=50)
    repo.save_profile(profile)
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.No)
    dashboard = TranslationDashboardDialog(None, repo.list_profiles(), repo, repo.list_profiles)

    dashboard.clear_all_goals_button.click()

    restored = repo.list_profiles()[0]
    assert restored.translation_goal_target == 12
    assert restored.translation_goal_baseline == 50


def test_progress_cards_keep_covers_and_hide_verified_and_summary_notes(tmp_path):
    from PySide6.QtWidgets import QLabel
    from PySide6.QtGui import QImage
    app()
    repo = ProjectRepository(tmp_path / "data")
    profile = NovelProfile(name="นิยายตัวอย่าง", translation_goal_target=5,
                           translator_goal_baseline=0)
    folder = repo.profile_dir(profile.id)
    folder.mkdir(parents=True, exist_ok=True)
    cover = folder / "cover.png"
    assert QImage(60, 90, QImage.Format_RGB32).save(str(cover))
    profile.cover_image_path = "cover.png"
    profile.verified_goal_target = 10
    profile.verified_goal_count = 2
    repo.save_profile(profile)
    dashboard = TranslationDashboardDialog(None, repo.list_profiles(), repo, repo.list_profiles)
    assert dashboard.summary.count() == 2
    cards = dashboard.rows_host.findChildren(QLabel)
    visible_text = " ".join(label.text() for label in cards if not label.isHidden())
    assert "verified" not in visible_text.casefold()
    assert "วันนี้แปลเพิ่ม" not in visible_text
    assert "จาก 1 เรื่อง" not in visible_text
    assert "นับตั้งแต่วันจันทร์" not in visible_text
    cover_widget = dashboard.rows_host.findChild(QLabel, "progressCover")
    assert cover_widget is not None and not cover_widget.pixmap().isNull()
    assert any(label.text() == profile.name for label in cards)
    dashboard.refresh()
    assert dashboard.summary.count() == 2


def test_compact_progress_grid_reflows_without_recreating_cards(tmp_path):
    from PySide6.QtWidgets import QFrame
    application = app()
    repo = ProjectRepository(tmp_path / "data")
    for index in range(9):
        repo.save_profile(NovelProfile(name=f"นิยายที่ {index + 1}"))
    dashboard = TranslationDashboardDialog(None, repo.list_profiles(), repo, repo.list_profiles)
    dashboard.resize(1350, 800)
    dashboard.show()
    application.processEvents()
    cards = dashboard.rows_host.findChildren(QFrame, "progressRow")
    assert len(cards) == 9
    assert dashboard.scroll is dashboard.overview_scroll
    assert dashboard._columns >= 2
    assert dashboard.rows.itemAtPosition(0, 1).widget() in cards
    original_ids = {id(card) for card in cards}
    dashboard.resize(560, 700)
    application.processEvents()
    assert dashboard._columns == 1
    assert {id(card) for card in dashboard._cards} == original_ids
    assert dashboard.rows.itemAtPosition(8, 0).widget() in cards
    dashboard.close()


def test_progress_card_goal_and_history_controls_remain_available(tmp_path):
    from PySide6.QtWidgets import QLabel, QPushButton
    app()
    repo = ProjectRepository(tmp_path / "data")
    profile = NovelProfile(
        name="เรื่องตัวอย่าง", translation_goal_target=7,
        translator_goal_baseline=10,
        translation_daily_activity={"2026-10-19": [11, 12]},
    )
    repo.save_profile(profile)
    dashboard = TranslationDashboardDialog(None, repo.list_profiles(), repo, repo.list_profiles)
    card = dashboard._cards[0]
    assert card.findChild(QLabel, "progressStoryTitle").text() == profile.name
    assert any(button.text().startswith("Context") for button in card.findChildren(QPushButton))
    assert any(button.text() in ("แก้เป้า", "ตั้งเป้า") for button in card.findChildren(QPushButton))
    assert dashboard._columns >= 1
