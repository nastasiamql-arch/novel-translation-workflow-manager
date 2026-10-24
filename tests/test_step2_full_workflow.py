"""STEP 2 navigation, localization and isolated completion integration."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date, datetime, timezone, timedelta
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QFrame

from novel_workflow.models import NovelProfile
from novel_workflow.storage import ProjectRepository
from novel_workflow.workspace_window import MainWindow
from novel_workflow.translation_planner import TranslationPlanner
from novel_workflow.story_planner_page import StoryPlannerPage
from novel_workflow.translation_progress import record_translator_export


def app():
    return QApplication.instance() or QApplication([])


def completed(profile, chapters, event, when):
    record_translator_export(
        profile, chapters, source_path="Translator.txt", digest="f" * 64,
        exported_path="confirmed.txt", event_id=event, completed_at=when)


def test_workspace_has_seven_novel_sections_and_five_primary_routes(tmp_path):
    app()
    repo = ProjectRepository(tmp_path)
    first, second = NovelProfile(name="นิยาย ก"), NovelProfile(name="นิยาย ข")
    repo.save_profile(first)
    repo.save_profile(second)
    window = MainWindow(repo)
    try:
        assert list(window.navigation.buttons) == [
            "today", "library", "workspace", "novel-inspector", "settings"]
        window.open_planned_novel(first.id)
        workspace = window.workspaces[first.id]
        assert [workspace.workspace_sections.tabText(i) for i in range(7)] == [
            "แปลนิยาย", "แผนการแปล", "ไฟล์และคำศัพท์",
            "แปลหลายบท", "ส่งออกไฟล์", "ความคืบหน้า", "ประวัติการเกลา"]
        workspace.workspace_sections.setCurrentIndex(1)
        assert window._utility_pages["story-planner"].profile_id == first.id
        window.return_from_utility_page()
        workspace.workspace_sections.setCurrentIndex(2)
        resources = window._utility_pages["resources:" + first.id]
        assert resources.profile_id == first.id
        window.return_from_utility_page()
        workspace.workspace_sections.setCurrentIndex(5)
        progress = window._utility_pages["novel-progress:" + first.id]
        assert progress.profile_id == first.id
        window.return_from_utility_page()
        window.open_planned_novel(second.id)
        assert window.profile.id == second.id
    finally:
        window._automatic_update_timer.stop()
        window.close()


def test_duration_recalculation_uses_only_confirmed_export_and_retains_history(tmp_path):
    repo = ProjectRepository(tmp_path)
    profile = NovelProfile(name="ทดลอง")
    repo.save_profile(profile)
    planner = TranslationPlanner(repo)
    before = datetime(2026, 10, 23, tzinfo=timezone.utc)
    first = datetime(2026, 10, 24, tzinfo=timezone.utc)
    completed(profile, list(range(1, 31)), "baseline", before)
    repo.save_profile(profile)
    planner.save_story_schedule(
        profile.id, "duration", final_chapter=120,
        start_day="2026-10-24", duration_days=3)
    assert [item["target"] for item in planner.story_day_rows(
        profile.id, "2026-10-24")["rows"]] == [30, 30, 30]
    completed(profile, list(range(31, 56)), "day-one", first)
    completed(profile, list(range(31, 56)), "duplicate", first)
    repo.save_profile(profile)
    result = planner.story_day_rows(profile.id, "2026-10-25")
    assert result["completed"] == 55
    assert result["remaining"] == 65
    assert [row["target"] for row in result["rows"][1:]] == [33, 32]
    assert len(profile.translator_export_events) == 3


def test_story_planner_custom_rest_days_and_separate_novels(tmp_path):
    app()
    repo = ProjectRepository(tmp_path)
    a, b = NovelProfile(name="ก"), NovelProfile(name="ข")
    repo.save_profile(a)
    repo.save_profile(b)
    page = StoryPlannerPage(repo, a.id)
    try:
        page.final.setValue(60)
        page.days.setValue(2)
        page.start.setDate(page.start.date().fromString("2026-10-24", Qt.ISODate))
        page.weekdays[5].setChecked(True)
        page._save()
        planner = TranslationPlanner(repo)
        schedule = planner.story_schedule(a.id)
        assert 5 in schedule["rest_weekdays"]
        assert planner.story_schedule(b.id) is None
        page.table.selectRow(0)
        page.target.setValue(0)
        page._override()
        assert planner.story_schedule(a.id)["overrides"]["2026-10-24"] == 0
        assert "ประวัติการปรับแผน" in page.history.text()
    finally:
        page.close()


def test_today_cards_show_real_counts_and_bound_ids(tmp_path):
    app()
    repo = ProjectRepository(tmp_path)
    a, b = NovelProfile(name="นิยาย A"), NovelProfile(name="นิยาย B")
    repo.save_profile(a)
    repo.save_profile(b)
    planner = TranslationPlanner(repo)
    planner.save_story_schedule(a.id, "duration", final_chapter=90,
                                start_day=date.today(), duration_days=3)
    planner.save_story_schedule(b.id, "daily", final_chapter=10,
                                start_day=date.today(), daily_target=2)
    from novel_workflow.translation_planner_page import TodayPage
    page = TodayPage(repo)
    try:
        cards = page.story_cards.findChildren(QFrame, "plannerStoryCard")
        assert {c.property("profileId") for c in cards} == {a.id, b.id}
        opened = []
        page.openNovel.connect(opened.append)
        for card in cards:
            button = card.findChild(QPushButton)
            button.click()
            assert opened[-1] == card.property("profileId")
    finally:
        page.close()
