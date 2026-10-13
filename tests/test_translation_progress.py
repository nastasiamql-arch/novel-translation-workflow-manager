import os
from datetime import datetime
from pathlib import Path

from novel_workflow.models import ChapterState, NovelProfile
from novel_workflow.translation_progress import (
    daily_chapter_count,
    goal_progress,
    local_day,
    latest_context_chapter,
    reset_goal_progress,
    sync_profile_context, record_translator_export,
)



def confirmed(profile, chapters, event_id='test', day=None):
    return record_translator_export(profile,chapters,source_path='Translator.txt',digest='a'*64,
        exported_path='Export.txt',event_id=event_id,completed_at=day)


def make_profile(path: Path, chapter: int = 125) -> NovelProfile:
    return NovelProfile(
        name="เรื่องทดสอบ",
        context_path=str(path),
        chapter_state=ChapterState(current_chapter=chapter),
        translation_checkpoint_path=str(path.resolve()),
    )


def test_context_chapter_headings_support_thai_chinese_and_english():
    assert latest_context_chapter("บทที่ 12 ชื่อเรื่อง") == 12
    assert latest_context_chapter("第 176 章 标题") == 176
    assert latest_context_chapter("Chapter 42: Title") == 42
    assert latest_context_chapter("บทที่ 157-159") == 159
    assert latest_context_chapter("第 157–159 章") == 159
    assert latest_context_chapter("Chapter 157 to 159") == 159


def test_context_uses_final_valid_heading():
    assert latest_context_chapter("Chapter 999\ntext\nChapter 120") == 120
    assert latest_context_chapter("บทที่ 120-125") == 125
    assert latest_context_chapter("ไม่มีหัวข้อบท") is None


def write_context(path: Path, chapter: int, modified: datetime) -> str:
    path.write_text(f"บทนำ\nบทที่ {chapter}\n", encoding="utf-8")
    timestamp = modified.timestamp()
    os.utime(path, (timestamp, timestamp))
    return local_day(timestamp)


def test_context_125_to_130_updates_checkpoint_without_completed_activity(tmp_path):
    context = tmp_path / "StoryContext.md"
    profile = make_profile(context)
    changed_day = write_context(context, 130, datetime(2026, 8, 12, 14, 30))

    assert sync_profile_context(profile)
    assert profile.chapter_state.current_chapter == 130
    assert profile.translation_daily_activity == {}
    assert daily_chapter_count(profile, changed_day) == 0


def test_context_range_updates_context_only_never_daily_or_goal_counts(tmp_path):
    context = tmp_path / "StoryContext.md"
    context.write_text("บทที่ 156\n", encoding="utf-8")
    profile = make_profile(context, chapter=156)
    profile.translation_goal_baseline = 156
    profile.translation_goal_target = 10
    sync_profile_context(profile)

    context.write_text("บทที่ 157-159\n", encoding="utf-8")

    assert sync_profile_context(profile)
    today = local_day(context.stat().st_mtime)
    assert profile.chapter_state.current_chapter == 159
    assert profile.translation_daily_activity == {}
    assert daily_chapter_count(profile, today) == 0
    assert goal_progress(profile) == (0, 10, 0)


def test_existing_chapter_state_is_a_migration_checkpoint(tmp_path):
    context = tmp_path / "StoryContext.md"
    profile = make_profile(context, chapter=125)
    profile.translation_checkpoint_path = None
    changed_day = write_context(context, 130, datetime(2026, 8, 12, 14, 30))

    sync_profile_context(profile)

    assert profile.translation_daily_activity == {}
    assert daily_chapter_count(profile, changed_day) == 0


def test_repeated_scan_does_not_double_count(tmp_path):
    context = tmp_path / "StoryContext.md"
    profile = make_profile(context)
    changed_day = write_context(context, 130, datetime(2026, 8, 12, 14, 30))

    sync_profile_context(profile)
    assert not sync_profile_context(profile)
    assert daily_chapter_count(profile, changed_day) == 0


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

    confirmed(profile, list(range(1,6)))
    assert goal_progress(profile) == (5, 5, 100)
    profile.chapter_state.current_chapter = 132
    confirmed(profile, [6,7], event_id="extra")
    assert goal_progress(profile) == (7, 5, 100)


def test_reset_goal_progress_keeps_target_and_daily_activity():
    profile = NovelProfile(name="เรื่องทดสอบ")
    profile.translation_goal_baseline = 125
    profile.translation_goal_target = 10
    profile.chapter_state.current_chapter = 132
    profile.translation_daily_activity = {"2026-09-27": [126, 127, 128, 129, 130, 131, 132]}

    confirmed(profile,list(range(126,133)),day=datetime(2026,9,27,14,30))
    assert reset_goal_progress(profile)
    assert profile.translation_goal_baseline == 125
    assert profile.translator_goal_baseline == 7
    assert profile.translation_goal_target == 10
    assert goal_progress(profile) == (0, 10, 0)
    assert daily_chapter_count(profile, "2026-09-27") == 7


def test_completed_goal_never_restarts_automatically_and_keeps_daily_activity(tmp_path):
    context = tmp_path / "StoryContext.md"
    profile = make_profile(context, chapter=125)
    profile.translation_goal_baseline = 125
    profile.translation_goal_target = 10
    profile.translation_daily_activity = {"2026-09-27": list(range(126, 136))}
    confirmed(profile,list(range(126,136)),day=datetime(2026,9,27,14,30))
    write_context(context, 135, datetime(2026, 9, 27, 14, 30))

    assert sync_profile_context(profile)
    assert profile.chapter_state.current_chapter == 135
    assert profile.translation_goal_baseline == 125
    assert goal_progress(profile) == (10, 10, 100)
    assert daily_chapter_count(profile, "2026-09-27") == 10


def test_goal_keeps_uncapped_overflow_until_explicit_reset(tmp_path):
    context = tmp_path / "StoryContext.md"
    profile = make_profile(context, chapter=125)
    profile.translation_goal_baseline = 125
    profile.translation_goal_target = 5
    confirmed(profile,list(range(126,138)),day=datetime(2026,9,27,14,30))
    write_context(context, 137, datetime(2026, 9, 27, 14, 30))

    assert sync_profile_context(profile)
    assert profile.translation_goal_baseline == 125
    assert goal_progress(profile) == (12, 5, 100)
