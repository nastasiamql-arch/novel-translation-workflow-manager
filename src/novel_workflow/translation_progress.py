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

from .models import NovelProfile

_CHAPTER_LINE = re.compile(
    r"(?im)^\s*(?:"
    r"บทที่\s*(\d+)(?:\s*[-–—~至]\s*(\d+))?"
    r"|第\s*(\d+)(?:\s*[-–—~至]\s*(\d+))?\s*章"
    r"|chapter\s+(\d+)(?:(?:\s*[-–—~]\s*|\s+to\s+)(\d+))?"
    r")"
)


def local_day(timestamp: float | None = None) -> str:
    """Return an ISO date using this computer's local timezone."""
    return datetime.fromtimestamp(time.time() if timestamp is None else timestamp).date().isoformat()


def latest_context_chapter(text: str) -> int | None:
    chapters = []
    for match in _CHAPTER_LINE.finditer(text):
        groups = match.groups()
        chapter = next(
            (groups[index] for index in (0, 2, 4) if groups[index]),
            None,
        )
        end_of_range = next(
            (groups[index] for index in (1, 3, 5) if groups[index]),
            None,
        )
        if end_of_range or chapter:
            chapters.append(int(end_of_range or chapter))
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
    if restart_completed_goal_cycles(profile):
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


def reset_goal_progress(profile: NovelProfile) -> bool:
    """Start a fresh goal cycle at the profile's current Context chapter."""
    if profile.translation_goal_target is None or profile.translation_goal_baseline is None:
        return False
    profile.translation_goal_baseline = profile.chapter_state.current_chapter
    return True


def restart_completed_goal_cycles(profile: NovelProfile) -> bool:
    """Advance the baseline for completed cycles and keep any overflow progress."""
    progress = goal_progress(profile)
    if progress is None:
        return False
    completed, target, _percentage = progress
    cycles = completed // target
    if cycles < 1:
        return False
    profile.translation_goal_baseline += cycles * target
    return True


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
