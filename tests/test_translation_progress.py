import os
from datetime import datetime
from pathlib import Path

from novel_workflow.models import ChapterState, NovelProfile
from novel_workflow.translation_progress import (
    daily_chapter_count,
    goal_progress,
    local_day,
    reset_goal_progress,
    sync_profile_context,
)


def make_profile(path: Path, chapter: int = 125) -> NovelProfile:
    return NovelProfile(
        name="เรื่องทดสอบ",
        context_path=str(path),
        chapter_state=ChapterState(current_chapter=chapter),
        translation_checkpoint_path=str(path.resolve()),
    )


def write_context(path: Path, chapter: int, modified: datetime) -> str:
    path.write_text(f"บทนำ\nบทที่ {chapter}\n", encoding="utf-8")
    timestamp = modified.timestamp()
    os.utime(path, (timestamp, timestamp))
    return local_day(timestamp)


def test_context_125_to_130_counts_five_on_file_modified_day(tmp_path):
    context = tmp_path / "StoryContext.md"
    profile = make_profile(context)
    changed_day = write_context(context, 130, datetime(2026, 8, 12, 14, 30))

    assert sync_profile_context(profile)
    assert profile.chapter_state.current_chapter == 130
    assert profile.translation_daily_activity[changed_day] == [126, 127, 128, 129, 130]
    assert daily_chapter_count(profile, changed_day) == 5


def test_existing_chapter_state_is_a_migration_checkpoint(tmp_path):
    context = tmp_path / "StoryContext.md"
    profile = make_profile(context, chapter=125)
    profile.translation_checkpoint_path = None
    changed_day = write_context(context, 130, datetime(2026, 8, 12, 14, 30))

    sync_profile_context(profile)

    assert profile.translation_daily_activity[changed_day] == [126, 127, 128, 129, 130]
    assert daily_chapter_count(profile, changed_day) == 5


def test_repeated_scan_does_not_double_count(tmp_path):
    context = tmp_path / "StoryContext.md"
    profile = make_profile(context)
    changed_day = write_context(context, 130, datetime(2026, 8, 12, 14, 30))

    sync_profile_context(profile)
    assert not sync_profile_context(profile)
    assert daily_chapter_count(profile, changed_day) == 5


def test_first_scan_does_not_count_existing_history(tmp_path):
    context = tmp_path / "StoryContext.md"
    profile = make_profile(context, chapter=1)
    profile.translation_checkpoint_path = None
    changed_day = write_context(context, 130, datetime(2026, 8, 12, 14, 30))

    sync_profile_context(profile)

    assert profile.translation_daily_activity == {}
    assert profile.chapter_state.current_chapter == 130
    assert daily_chapter_count(profile, changed_day) == 0


def test_switching_context_or_chapter_rollback_rebaselines_without_count(tmp_path):
    first = tmp_path / "first.md"
    second = tmp_path / "second.md"
    profile = make_profile(first, chapter=130)
    profile.translation_daily_activity = {}
    write_context(second, 80, datetime(2026, 8, 12, 14, 30))
    profile.context_path = str(second)

    assert sync_profile_context(profile)
    assert profile.chapter_state.current_chapter == 80
    assert profile.translation_daily_activity == {}

    write_context(second, 70, datetime(2026, 8, 13, 14, 30))
    assert sync_profile_context(profile)
    assert profile.chapter_state.current_chapter == 70
    assert profile.translation_daily_activity == {}


def test_goal_progress_uses_profile_baseline_and_caps_visual_percentage(tmp_path):
    profile = NovelProfile(name="เรื่องทดสอบ")
    profile.translation_goal_baseline = 125
    profile.translation_goal_target = 5
    profile.chapter_state.current_chapter = 130

    assert goal_progress(profile) == (5, 5, 100)
    profile.chapter_state.current_chapter = 132
    assert goal_progress(profile) == (7, 5, 100)


def test_reset_goal_progress_keeps_target_and_daily_activity():
    profile = NovelProfile(name="เรื่องทดสอบ")
    profile.translation_goal_baseline = 125
    profile.translation_goal_target = 10
    profile.chapter_state.current_chapter = 132
    profile.translation_daily_activity = {"2026-09-27": [126, 127, 128, 129, 130, 131, 132]}

    assert reset_goal_progress(profile)
    assert profile.translation_goal_baseline == 132
    assert profile.translation_goal_target == 10
    assert goal_progress(profile) == (0, 10, 0)
    assert daily_chapter_count(profile, "2026-09-27") == 7
