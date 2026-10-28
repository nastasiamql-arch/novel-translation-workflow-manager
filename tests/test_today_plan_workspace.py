"""Today plan bar must reuse verified Planner activity without touching exports."""
from datetime import date

import pytest
from PySide6.QtWidgets import QApplication

from novel_workflow.models import NovelProfile
from novel_workflow.storage import ProjectRepository
from novel_workflow.today_plan_bar import TodayPlanBar, today_plan_labels, today_plan_snapshot
from novel_workflow.translation_planner import TranslationPlanner
from novel_workflow.translation_progress import record_translator_export


def test_today_plan_daily_and_confirmed_export(tmp_path):
    repo = ProjectRepository(tmp_path)
    profile = NovelProfile(name="Daily")
    repo.save_profile(profile)
    planner = TranslationPlanner(repo)
    today = date.today()
    planner.save(today, profile.id, "daily", target_chapters=5)
    assert today_plan_labels(today_plan_snapshot(planner, profile, today)) == (
        "วันนี้ 0 / 5 บท", "เหลือ 5 บท", "0%", 0
    )
    record_translator_export(profile, [1, 2], source_path="Translator.txt", digest="a"*64, exported_path="out.txt", event_id="one")
    repo.save_profile(profile)
    snap = today_plan_snapshot(planner, profile, today)
    assert snap["completed"] == 2
    assert today_plan_labels(snap) == ("วันนี้ 2 / 5 บท", "เหลือ 3 บท", "40%", 40)
    # Re-export the same chapters: the ledger deduplicates confirmed chapters.
    record_translator_export(profile, [1, 2], source_path="Translator.txt", digest="a"*64, exported_path="out.txt", event_id="two")
    repo.save_profile(profile)
    assert today_plan_snapshot(planner, profile, today)["completed"] == 2


@pytest.mark.parametrize("completed,target,detail,percent", [
    (359,359,"ครบเป้าหมายแล้ว",100),
    (370,359,"เกินเป้า 11 บท",100),
    (165,359,"เหลือ 194 บท",46),
])
def test_today_plan_labels_progress(completed,target,detail,percent):
    title, actual, text_percent, bar = today_plan_labels({
        "status":"active", "completed":completed, "target":target
    })
    assert title == f"วันนี้ {completed:,} / {target:,} บท"
    assert actual == detail
    assert text_percent == f"{percent}%"
    assert bar == percent


@pytest.mark.parametrize("kind,text", [
    ("empty","ยังไม่มีแผนวันนี้"),
    ("rest","วันนี้เป็นวันพัก"),
    ("error","อ่านแผนวันนี้ไม่ได้"),
])
def test_today_plan_no_fictional_progress(kind,text):
    title, _, percentage, bar = today_plan_labels({
        "status":kind, "completed":0, "target":None
    })
    assert title == text
    assert percentage == ""
    assert bar is None


def test_workspace_bar_reused_and_navigation_persistence(tmp_path):
    from novel_workflow.workspace_window import MainWindow
    app = QApplication.instance() or QApplication([])
    repo = ProjectRepository(tmp_path)
    settings = repo.load_settings()
    assert settings.navigation_collapsed
    settings.last_update_check_date = date.today().isoformat()
    repo.save_settings(settings)
    profile = NovelProfile(name="Workspace")
    repo.save_profile(profile)
    window = MainWindow(repo)
    try:
        window.show()
        app.processEvents()
        ws = window.workspaces[profile.id]
        bar = ws.today_plan_bar
        assert bar is not None
        assert bar.progress.isHidden()
        assert window.navigation.width() == 60
        assert window.shell_splitter.widget(0).width() == 60
        first_width = ws.editor_content_stack.width()
        window.navigation.brand_toggle.click()
        app.processEvents()
        assert window.navigation.width() == 196
        assert ws.editor_content_stack.width() < first_width
        ws.open_editor()
        assert ws.today_plan_bar is bar
        window.navigation.brand_toggle.click()
        window._persist_workspace_session()
        assert repo.load_settings().navigation_collapsed
        bar.open_button.click()
        assert window._active_utility_page == "story-planner"
        window.return_from_utility_page()
        assert window.workspace_stack.currentWidget() is ws
        assert ws.today_plan_bar is bar
    finally:
        window.close()
