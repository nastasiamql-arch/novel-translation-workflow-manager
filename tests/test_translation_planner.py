from datetime import date, datetime, timedelta, timezone

import pytest

from novel_workflow.models import NovelProfile
from novel_workflow.storage import ProjectRepository
from novel_workflow.translation_planner import TranslationPlanner
from novel_workflow.translation_progress import (
    record_translator_export, confirm_retranslation, undo_retranslation,
)


def exported(profile, chapters, event_id, when):
    return record_translator_export(
        profile, chapters, source_path="Translator.txt", digest="a" * 64,
        exported_path="export.txt", event_id=event_id, completed_at=when)


def test_daily_plans_count_only_unique_confirmed_exports(tmp_path):
    repo = ProjectRepository(tmp_path)
    profile = NovelProfile(name="A")
    repo.save_profile(profile)
    planner = TranslationPlanner(repo)
    day = date(2026, 10, 22)
    plan = planner.save(day, profile.id, "daily", target_chapters=5)
    assert planner.summary(day)["today_count"] == 0
    stamp = datetime(2026, 10, 22, 12, tzinfo=timezone(timedelta(hours=7)))
    exported(profile, [1, 2], "e1", stamp)
    exported(profile, [1, 2], "e2", stamp)
    repo.save_profile(profile)
    result = planner.summary(day)
    assert result["today_count"] == 2
    assert result["remaining"] == 3
    exported(profile, [3, 4, 5, 6], "e3", stamp)
    repo.save_profile(profile)
    result = planner.summary(day)
    assert result["today_count"] == 6
    assert result["excess"] == 1
    assert result["percent"] == 100
    assert TranslationPlanner(repo).get(day)["id"] == plan["id"]


def test_finish_goal_tracks_gaps_and_reset_without_mutating_export_history(tmp_path):
    repo = ProjectRepository(tmp_path)
    profile = NovelProfile(name="B")
    repo.save_profile(profile)
    planner = TranslationPlanner(repo)
    day = "2026-10-22"
    planner.save(day, profile.id, "finish", final_chapter=5)
    stamp = datetime(2026, 10, 22, tzinfo=timezone.utc)
    exported(profile, [1, 3, 5], "e1", stamp)
    repo.save_profile(profile)
    assert planner.summary(day)["missing_preview"] == [2, 4]
    assert planner.summary(day)["remaining"] == 2
    reset = confirm_retranslation(profile, 3)
    repo.save_profile(profile)
    assert planner.summary(day)["missing_preview"] == [2, 3, 4, 5]
    exported(profile, [3], "e2", stamp)
    repo.save_profile(profile)
    assert planner.summary(day)["missing_preview"] == [2, 4, 5]
    assert undo_retranslation(profile, reset["reset_id"])
    repo.save_profile(profile)
    assert planner.summary(day)["missing_preview"] == [2, 4]
    assert len(profile.translator_export_events) == 2


def test_manual_weekly_plans_preserve_history_and_unknown_fields(tmp_path):
    repo = ProjectRepository(tmp_path)
    profile = NovelProfile()
    repo.save_profile(profile)
    planner = TranslationPlanner(repo)
    day = date(2026, 12, 31)
    planner.save(day, profile.id, "focus")
    planner.save(day, profile.id, "daily", target_chapters=20)
    planner.save(day + timedelta(days=1), None, "rest")
    assert len(planner.get(day)["history"]) == 1
    assert planner.get(day + timedelta(days=1))["plan_type"] == "rest"
    assert len(planner.week(day)) == 7
    assert planner.get(day)["target_chapters"] == 20


def test_missing_profile_and_unknown_end_are_safe(tmp_path):
    repo = ProjectRepository(tmp_path)
    p = NovelProfile()
    repo.save_profile(p)
    planner = TranslationPlanner(repo)
    planner.save("2026-10-22", p.id, "finish")
    assert planner.summary("2026-10-22")["percent"] is None
    planner.confirm_finished(p.id)
    assert planner.finish_goal(p.id)["confirmed_finished"]
    repo.delete_profile(p.id)
    assert planner.summary("2026-10-22")["status"] == "missing_profile"


def test_invalid_plan_rejected_without_creating_planner_file(tmp_path):
    repo = ProjectRepository(tmp_path)
    planner = TranslationPlanner(repo)
    with pytest.raises(ValueError):
        planner.save("2026-10-22", "missing", "daily", target_chapters=0)
    assert not planner.path.exists()


def test_today_page_can_save_and_navigate(tmp_path):
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from novel_workflow.translation_planner_page import TodayPage
    repo = ProjectRepository(tmp_path)
    profile = NovelProfile()
    repo.save_profile(profile)
    page = TodayPage(repo)
    try:
        page.kind.setCurrentIndex(page.kind.findData("daily"))
        page.day.setDate(page.day.date())
        page.target.setValue(20)
        page._save()
        assert page.planner.get(date.today())["target_chapters"] == 20
        assert page.open_button.isEnabled()
    finally:
        page.close()


def test_finish_goal_carries_to_next_day_without_copying_daily_plan(tmp_path):
    repo = ProjectRepository(tmp_path)
    profile = NovelProfile()
    repo.save_profile(profile)
    planner = TranslationPlanner(repo)
    planner.save("2026-10-22", profile.id, "finish", final_chapter=10)
    carried = planner.summary("2026-10-23")
    assert carried["status"] == "active"
    assert carried["plan"]["carried_from"] == "2026-10-22"
    assert planner.get("2026-10-23") is None
    planner.save("2026-10-23", None, "rest")
    assert planner.summary("2026-10-23")["status"] == "rest"
    planner.confirm_finished(profile.id)
    assert planner.summary("2026-10-24")["status"] == "empty"


def test_multi_novel_plans_rest_edit_history_and_isolation(tmp_path):
    repo = ProjectRepository(tmp_path)
    a, b = NovelProfile(name="A"), NovelProfile(name="B")
    repo.save_profile(a); repo.save_profile(b)
    planner = TranslationPlanner(repo)
    day = "2026-10-22"
    a_plan = planner.save(day, a.id, "daily", target_chapters=3)
    b_plan = planner.save(day, b.id, "daily", target_chapters=7)
    assert {p["profile_id"] for p in planner.plans_for_day(day)} == {a.id, b.id}
    assert planner.get(day, a.id)["id"] == a_plan["id"]
    assert planner.get(day, b.id)["id"] == b_plan["id"]
    planner.save(day, a.id, "rest")
    assert planner.get(day, b.id)["target_chapters"] == 7
    planner.save(day, a.id, "focus")
    assert len(planner.get(day, a.id)["history"]) == 2
    assert planner.summary(day, profile_id=b.id)["profile"].id == b.id
    assert planner.summary(day, profile_id=a.id)["profile"].id == a.id
    assert len(TranslationPlanner(repo).plans_for_day(day)) == 2


def test_legacy_planner_migrates_atomically_and_preserves_extension_fields(tmp_path):
    from novel_workflow.storage import write_json, read_json
    repo = ProjectRepository(tmp_path)
    a, b = NovelProfile(name="A"), NovelProfile(name="B")
    repo.save_profile(a); repo.save_profile(b)
    planner = TranslationPlanner(repo)
    day = "2026-10-22"
    prior = {
        "days": {day: {
            "id": "legacy-id", "profile_id": a.id, "local_date": day,
            "plan_type": "daily", "target_chapters": 4,
            "history": [{"original": True}], "extension": {"keep": [1, 2]},
        }},
        "finish_goals": {a.id: {"confirmed_finished": False, "custom": "saved"}},
        "third_party_field": [17],
    }
    write_json(planner.path, prior)
    assert planner.get(day, a.id)["extension"] == {"keep": [1, 2]}
    assert read_json(planner.path, {}) == prior
    planner.save(day, b.id, "rest")
    saved = read_json(planner.path, {})
    assert saved["schema_version"] == 2
    assert saved["third_party_field"] == [17]
    assert saved["finish_goals"] == prior["finish_goals"]
    assert saved["days"][day]["plans"][a.id] == prior["days"][day]
    assert planner.get(day, a.id)["id"] == "legacy-id"
    assert planner.get(day, b.id)["plan_type"] == "rest"


def test_finish_goal_is_novel_scoped_across_days_and_rest(tmp_path):
    repo = ProjectRepository(tmp_path)
    a, b = NovelProfile(name="A"), NovelProfile(name="B")
    repo.save_profile(a); repo.save_profile(b)
    planner = TranslationPlanner(repo)
    planner.save("2026-10-22", a.id, "finish", final_chapter=100)
    planner.save("2026-10-23", b.id, "daily", target_chapters=1)
    assert planner.summary("2026-10-23", profile_id=a.id)["plan"]["carried_from"] == "2026-10-22"
    assert planner.summary("2026-10-23", profile_id=b.id)["plan"]["plan_type"] == "daily"
    planner.save("2026-10-24", a.id, "rest")
    assert planner.summary("2026-10-24", profile_id=a.id)["status"] == "rest"
    assert planner.summary("2026-10-24", profile_id=b.id)["status"] == "empty"
    assert planner.summary("2026-10-25", profile_id=a.id)["plan"]["plan_type"] == "finish"
