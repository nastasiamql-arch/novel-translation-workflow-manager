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
