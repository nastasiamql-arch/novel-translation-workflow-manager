from datetime import date, datetime, timezone
import pytest
from novel_workflow.models import NovelProfile
from novel_workflow.storage import ProjectRepository
from novel_workflow.translation_planner import TranslationPlanner
from novel_workflow.translation_progress import record_translator_export


def test_duration_schedule_and_verified_recalculation(tmp_path):
    repo = ProjectRepository(tmp_path)
    novel = NovelProfile(name="เรื่อง A")
    repo.save_profile(novel)
    planner = TranslationPlanner(repo)
    planner.save_story_schedule(novel.id, "duration", final_chapter=120,
                                start_day="2026-10-24", duration_days=3)
    original = planner.story_day_rows(novel.id, "2026-10-24")
    assert [r["target"] for r in original["rows"]] == [40, 40, 40]
    record_translator_export(novel, list(range(1, 26)),
                             source_path="Translator.txt", digest="a" * 64,
                             exported_path="a.txt", event_id="event-1",
                             completed_at=datetime(2026, 10, 24, 5, tzinfo=timezone.utc))
    repo.save_profile(novel)
    updated = planner.story_day_rows(novel.id, "2026-10-25")
    assert updated["completed"] == 25
    assert updated["remaining"] == 95
    assert [r["target"] for r in updated["rows"][1:]] == [48, 47]


def test_per_novel_isolation_rest_days_and_history(tmp_path):
    repo = ProjectRepository(tmp_path)
    a, b = NovelProfile(name="A"), NovelProfile(name="B")
    repo.save_profile(a)
    repo.save_profile(b)
    planner = TranslationPlanner(repo)
    planner.save_story_schedule(a.id, "duration", final_chapter=90,
                                start_day="2026-10-24", duration_days=2,
                                rest_weekdays=(6,))
    planner.save_story_schedule(b.id, "daily", final_chapter=10,
                                start_day="2026-10-24", daily_target=2)
    planner.override_story_day(a.id, "2026-10-24", 0)
    assert planner.story_day_rows(a.id)["rows"][0]["rest"]
    assert planner.story_schedule(b.id)["overrides"] == {}
    assert len(planner.story_schedule(a.id)["history"]) == 1
    with pytest.raises(ValueError):
        planner.override_story_day(b.id, "2026-01-01", 0)


def test_invalid_schedule_does_not_write(tmp_path):
    repo = ProjectRepository(tmp_path)
    p = NovelProfile()
    repo.save_profile(p)
    planner = TranslationPlanner(repo)
    with pytest.raises(ValueError):
        planner.save_story_schedule(p.id, "deadline", final_chapter=10,
                                    start_day="2026-10-26", deadline="2026-10-25")
    assert planner.story_schedule(p.id) is None
