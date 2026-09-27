import os
from datetime import datetime
from pathlib import Path

from novel_workflow.models import ChapterState, NovelGroup, NovelProfile
from novel_workflow.translation_progress import (
    daily_chapter_count,
    goal_progress,
    local_day,
    apply_group_goal,
    reset_goal_progress,
    reset_group_goal_progress,
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



def test_apply_group_goal_sets_all_members_and_preserves_existing_progress():
    first = NovelProfile(name="A", chapter_state=ChapterState(current_chapter=130))
    first.translation_goal_target = 8
    first.translation_goal_baseline = 125
    second = NovelProfile(name="B", chapter_state=ChapterState(current_chapter=42))
    other = NovelProfile(name="Other", chapter_state=ChapterState(current_chapter=12))
    group = NovelGroup(name="Group", profile_ids=[first.id, second.id])

    members = apply_group_goal(group, [first, second, other], 15)

    assert members == [first, second]
    assert group.default_goal_chapters == 15
    assert (first.translation_goal_target, first.translation_goal_baseline) == (15, 125)
    assert (second.translation_goal_target, second.translation_goal_baseline) == (15, 42)
    assert other.translation_goal_target is None


def test_reset_group_goal_restarts_every_member_at_current_chapter_and_keeps_daily_counts():
    first = NovelProfile(name="A", chapter_state=ChapterState(current_chapter=130))
    second = NovelProfile(name="B", chapter_state=ChapterState(current_chapter=42))
    other = NovelProfile(name="Other", chapter_state=ChapterState(current_chapter=12))
    for profile in (first, second, other):
        profile.translation_goal_target = 15
        profile.translation_goal_baseline = 10
        profile.translation_daily_activity = {"2026-09-27": [11, 12]}
    group = NovelGroup(name="Group", profile_ids=[first.id, second.id], default_goal_chapters=15)

    members = reset_group_goal_progress(group, [first, second, other])

    assert members == [first, second]
    assert first.translation_goal_baseline == 130
    assert second.translation_goal_baseline == 42
    assert first.translation_goal_target == second.translation_goal_target == 15
    assert first.translation_daily_activity == {"2026-09-27": [11, 12]}
    assert other.translation_goal_baseline == 10
    assert group.last_goal_reset_at is not None


def test_individual_reset_can_restore_group_target():
    profile = NovelProfile(name="A", chapter_state=ChapterState(current_chapter=130))
    profile.translation_goal_target = 7
    profile.translation_goal_baseline = 125

    assert reset_goal_progress(profile, target=15)
    assert profile.translation_goal_target == 15
    assert profile.translation_goal_baseline == 130


def test_group_goal_requires_a_positive_integer():
    import pytest

    profile = NovelProfile(name="A")
    group = NovelGroup(name="Group", profile_ids=[profile.id])
    with pytest.raises(ValueError):
        apply_group_goal(group, [profile], 0)
