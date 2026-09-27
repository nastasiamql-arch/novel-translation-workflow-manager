"""Context-driven translation progress tracking.

A Context chapter increase is attributed to the Context file's last-write time in
the computer's local timezone. The chapter number saved in ChapterState serves as
the durable checkpoint, so changes made while the app is closed are included.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
import os
from pathlib import Path
import re
import time

from .models import NovelGroup, NovelProfile

_CHAPTER_LINE = re.compile(r"(?im)^\s*บทที่\s*(\d+)\b")


def local_day(timestamp: float | None = None) -> str:
    """Return an ISO date using this computer's local timezone."""
    return datetime.fromtimestamp(time.time() if timestamp is None else timestamp).date().isoformat()


def latest_context_chapter(text: str) -> int | None:
    chapters = [int(match.group(1)) for match in _CHAPTER_LINE.finditer(text)]
    return chapters[-1] if chapters else None


def sync_profile_context(profile: NovelProfile) -> bool:
    """Read one profile's Context and record each newly reached chapter once.

    The first scan establishes a baseline unless an earlier chapter checkpoint
    is already present (for example, imported from Novel-Launcher).
    A Context path change or chapter rollback establishes a fresh baseline.
    """
    if not profile.context_path:
        return False
    path = Path(profile.context_path).expanduser()
    try:
        stat = path.stat()
        if not path.is_file():
            return False
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return False

    latest = latest_context_chapter(text)
    if latest is None:
        return False

    canonical_path = os.path.normcase(str(path.resolve()))
    old_path = profile.translation_checkpoint_path
    same_context = old_path is None or os.path.normcase(str(Path(old_path).expanduser().resolve())) == canonical_path
    previous = profile.chapter_state.current_chapter
    changed = False

    if old_path is not None and not same_context:
        # A different novel/context file must never inherit the old chapter delta.
        profile.chapter_state.current_chapter = latest
        profile.translation_checkpoint_path = canonical_path
        return True

    if latest < previous:
        # Context was corrected or restarted. Do not create negative activity.
        profile.chapter_state.current_chapter = latest
        profile.translation_checkpoint_path = canonical_path
        return True

    # On an uninitialized profile, chapter 1 is only a default, not history.
    can_count = old_path is not None or previous > 1
    if latest > previous and can_count:
        day = local_day(stat.st_mtime)
        seen = set(profile.translation_daily_activity.get(day, []))
        new_chapters = [chapter for chapter in range(previous + 1, latest + 1) if chapter not in seen]
        if new_chapters:
            profile.translation_daily_activity[day] = sorted(seen.union(new_chapters))
            changed = True

    if profile.chapter_state.current_chapter != latest:
        profile.chapter_state.current_chapter = latest
        changed = True
    if old_path != canonical_path:
        profile.translation_checkpoint_path = canonical_path
        changed = True
    return changed


def daily_chapter_count(profile: NovelProfile, day: str | None = None) -> int:
    return len(profile.translation_daily_activity.get(day or local_day(), []))


def goal_progress(profile: NovelProfile) -> tuple[int, int, int] | None:
    target = profile.translation_goal_target
    baseline = profile.translation_goal_baseline
    if target is None or target <= 0 or baseline is None:
        return None
    completed = max(0, profile.chapter_state.current_chapter - baseline)
    return completed, target, min(100, round(completed * 100 / target))


def reset_goal_progress(profile: NovelProfile, target: int | None = None) -> bool:
    """Start a fresh goal cycle, optionally restoring a group's shared target."""
    next_target = target if target is not None else profile.translation_goal_target
    if isinstance(next_target, bool) or not isinstance(next_target, int) or next_target <= 0:
        return False
    profile.translation_goal_target = next_target
    profile.translation_goal_baseline = profile.chapter_state.current_chapter
    return True


def apply_group_goal(group: NovelGroup, profiles: list[NovelProfile], target: int) -> list[NovelProfile]:
    """Apply a shared target to every existing profile in a group.

    Existing baselines are preserved so changing a target does not erase progress.
    Profiles without a baseline start from their latest saved chapter.
    """
    if isinstance(target, bool) or not isinstance(target, int) or target <= 0:
        raise ValueError("เป้าหมายต้องเป็นจำนวนบทที่มากกว่า 0")
    member_ids = set(group.profile_ids)
    members = [profile for profile in profiles if profile.id in member_ids]
    group.default_goal_chapters = target
    group.caught_up_profile_ids = []
    for profile in members:
        if profile.translation_goal_baseline is None:
            profile.translation_goal_baseline = profile.chapter_state.current_chapter
        profile.translation_goal_target = target
    return members


def reset_group_goal_progress(group: NovelGroup, profiles: list[NovelProfile]) -> list[NovelProfile]:
    """Reset every member to its current chapter while preserving the group target."""
    target = group.default_goal_chapters
    if isinstance(target, bool) or not isinstance(target, int) or target <= 0:
        return []
    member_ids = set(group.profile_ids)
    members = [profile for profile in profiles if profile.id in member_ids]
    for profile in members:
        reset_goal_progress(profile, target)
    group.caught_up_profile_ids = []
    group.last_goal_reset_at = datetime.now().astimezone().isoformat(timespec="seconds")
    return members


def week_start(day: date | None = None) -> date:
    current = day or datetime.now().date()
    return current - timedelta(days=current.weekday())


def profile_week_count(profile: NovelProfile, today: date | None = None) -> int:
    end = today or datetime.now().date()
    start = week_start(end)
    return sum(
        len(chapters)
        for key, chapters in profile.translation_daily_activity.items()
        if start.isoformat() <= key <= end.isoformat()
    )
