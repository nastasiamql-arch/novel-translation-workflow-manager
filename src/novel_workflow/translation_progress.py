"""Confirmed Translator Export activity; Context scanning is informational only."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from functools import lru_cache
import os
from pathlib import Path
import re
import time
import uuid

from .models import NovelProfile

_CHAPTER_LINE = re.compile(
    r"(?im)^[ \t]*(?:#{1,6}[ \t]+)?(?:"
    r"บทที่\s*(\d+)(?:\s*[-–—~至]\s*(\d+))?"
    r"|第\s*(\d+)(?:\s*[-–—~至]\s*(\d+))?\s*章"
    r"|chapter\s+(\d+)(?:(?:\s*[-–—~]\s*|\s+to\s+)(\d+))?"
    r")"
)


def local_day(timestamp: float | None = None) -> str:
    """Return an ISO date using this computer's local timezone."""
    return datetime.fromtimestamp(time.time() if timestamp is None else timestamp).date().isoformat()


def latest_context_chapter(text: str) -> int | None:
    sections = list(re.finditer(
        r"(?im)^[ \t]*(?:#{1,6}[ \t]+)?(?:chapter[ \t]+progress|translation[ \t]+progress|ความคืบหน้า(?:การแปล)?|ความคืบหน้าบท|进度|章節進度|章节进度)[ \t]*[:：]?[ \t]*", text))
    if sections:
        text = text[sections[-1].end():]
        next_section = re.search(r'(?im)^#{1,6}[ \t]+(?!บทที่\s*\d|Chapter\s+\d|第\s*\d)', text)
        if next_section:
            text = text[:next_section.start()]
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
            start, end = int(chapter), int(end_of_range or chapter)
            if 0 < start <= end <= 2_147_483_647:
                chapters.append(end)
    return chapters[-1] if chapters else None


@lru_cache(maxsize=128)
def _context_chapter_snapshot(path, mtime_ns, ctime_ns, size, inode):
    # Retain only the parsed chapter, never entire Context documents.
    return latest_context_chapter(Path(path).read_text(encoding="utf-8-sig", errors="replace"))


def read_context_chapter(path, stat=None):
    """Reuse parsing while file identity/size/timestamps remain unchanged."""
    path = Path(path).expanduser().absolute()
    stat = stat or path.stat()
    return _context_chapter_snapshot(str(path), stat.st_mtime_ns,
                                    stat.st_ctime_ns, stat.st_size, stat.st_ino)


def sync_profile_context(profile: NovelProfile) -> bool:
    """Update informational Context chapter state; never completed activity."""
    if not profile.context_path:
        return False
    path = Path(profile.context_path).expanduser()
    try:
        stat = path.stat()
        if not path.is_file():
            return False
        latest = read_context_chapter(path, stat)
    except OSError:
        return False

    if latest is None:
        return False

    canonical_path = os.path.normcase(str(path.resolve()))
    changed = (profile.chapter_state.current_chapter != latest
               or profile.translation_checkpoint_path != canonical_path)
    profile.chapter_state.current_chapter = latest
    profile.translation_checkpoint_path = canonical_path
    return changed


def migrate_translation_progress(profile):
    if profile.translation_progress_version >= 2: return False
    from copy import deepcopy
    profile.legacy_translation_progress = {
        **profile.legacy_translation_progress,
        'source': 'context_scan',
        'daily_activity': deepcopy(profile.translation_daily_activity),
        'goal_target': profile.translation_goal_target,
        'goal_baseline': profile.translation_goal_baseline,
        'checkpoint_path': profile.translation_checkpoint_path,
    }
    profile.translation_progress_version = 2
    if profile.translation_goal_target is not None and profile.translator_goal_baseline is None:
        profile.translator_goal_baseline = completed_chapter_count(profile)
    return True


def confirmed_events(profile):
    """Yield effective chapters without altering immutable Export audit entries.

    Each confirmed reset masks only the Export entries existing at the moment
    the user confirmed it. A subsequent Export can therefore complete a
    previously masked chapter, even if older Export events span that chapter.
    """
    resets = [
        reset for reset in getattr(profile, 'translation_retranslation_resets', [])
        if (isinstance(reset, dict) and reset.get('active') is True
            and type(reset.get('event_count')) is int
            and type(reset.get('start_chapter')) is int)
    ]
    for index, event in enumerate(profile.translator_export_events):
        if (isinstance(event, dict) and event.get('profile_id') == profile.id
                and event.get('status') == 'committed' and isinstance(event.get('chapters'), list)
                and all(type(n) is int and 0 < n <= 2_147_483_647 for n in event['chapters'])):
            chapters = [
                n for n in event['chapters']
                if not any(index < reset['event_count'] and n >= reset['start_chapter']
                           for reset in resets)
            ]
            yield {**event, 'chapters': chapters}


def retranslation_preview(profile, start_chapter: int) -> dict:
    """Read-only preview; never infer affected chapters from Context text."""
    if type(start_chapter) is not int or not 0 < start_chapter <= 2_147_483_647:
        raise ValueError("เลขบทเริ่มแปลใหม่ไม่ถูกต้อง")
    affected = sorted(n for n in completed_chapters(profile) if n >= start_chapter)
    return {
        'start_chapter': start_chapter,
        'chapters': affected,
        'count': len(affected),
        'latest_export': max(completed_chapters(profile), default=0),
    }


def confirm_retranslation(profile, start_chapter: int, *, context_chapter=None,
                          reason: str = "") -> dict | None:
    """Record a reversible, partial reset; preserve all original Export events."""
    preview = retranslation_preview(profile, start_chapter)
    if not preview['chapters']:
        return None
    if context_chapter is not None and (
            type(context_chapter) is not int or context_chapter + 1 != start_chapter):
        raise ValueError("เลขบทจาก Context ไม่ตรงกับจุดเริ่มแปล")
    previous_baseline = profile.translator_goal_baseline
    baseline_after = (min(previous_baseline, completed_chapter_count(profile) - preview['count'])
                      if previous_baseline is not None else None)
    entry = {
        'reset_id': uuid.uuid4().hex,
        'event_count': len(profile.translator_export_events),
        'start_chapter': start_chapter,
        'context_chapter': context_chapter,
        'reason': str(reason),
        'created_at': datetime.now().astimezone().isoformat(timespec='seconds'),
        'affected_chapters': preview['chapters'],
        'active': True,
        'goal_baseline_before': previous_baseline,
        'goal_baseline_after': baseline_after,
    }
    profile.translation_retranslation_resets.append(entry)
    profile.translator_goal_baseline = baseline_after
    return entry


def undo_retranslation(profile, reset_id: str | None = None) -> bool:
    """Restore the latest active reset without touching disk files or events."""
    active = [
        record for record in profile.translation_retranslation_resets
        if isinstance(record, dict) and record.get('active') is True
    ]
    if not active:
        return False
    record = active[-1]
    if reset_id is not None and record.get('reset_id') != reset_id:
        return False
    record['active'] = False
    if profile.translator_goal_baseline == record.get('goal_baseline_after'):
        profile.translator_goal_baseline = record.get('goal_baseline_before')
    return True


def completed_chapters(profile):
    return {n for event in confirmed_events(profile) for n in event['chapters']}


def completed_chapter_count(profile):
    return len(completed_chapters(profile))


def confirmed_daily_activity(profile):
    seen, activity, ids = set(), {}, set()
    for event in confirmed_events(profile):
        if event.get('event_id') in ids: continue
        ids.add(event.get('event_id'))
        fresh = set(event['chapters']) - seen
        seen.update(event['chapters'])
        activity.setdefault(event['local_date'], set()).update(fresh)
    return activity


def record_translator_export(profile, chapters, *, source_path, digest, exported_path,
                             event_id, completed_at=None, snapshot_path=None):
    if (not event_id or not re.fullmatch(r'[0-9a-f]{64}', digest)
            or any(type(n) is not int or not 0 < n <= 2_147_483_647 for n in chapters)):
        raise ValueError('Invalid confirmed Translator Export')
    chapters = sorted(set(chapters))
    for event in profile.translator_export_events:
        if event.get('event_id') == event_id:
            if (event.get('profile_id') != profile.id or event.get('chapters') != chapters
                    or event.get('sha256') != digest or event.get('translator_path') != str(source_path)):
                raise ValueError('Export event ID conflict')
            return event
    fresh = sorted(set(chapters) - completed_chapters(profile))
    when = completed_at or datetime.now().astimezone()
    if when.tzinfo is None: when = when.astimezone()
    event = {'event_id': event_id, 'profile_id': profile.id,
             'completed_at': when.isoformat(timespec='microseconds'), 'local_date': when.date().isoformat(),
             'chapters': chapters, 'new_chapters': fresh, 'chapter_range': format_chapters(chapters),
             'translator_path': str(source_path), 'sha256': digest,
             'exported_txt_path': str(exported_path), 'snapshot_path': str(snapshot_path or ''),
             'status': 'committed'}
    profile.translator_export_events.append(event)
    return event


def translator_chapters(data):
    from .recovery import _TRANSLATOR_CHAPTER_LINE
    chapters = set()
    for match in _TRANSLATOR_CHAPTER_LINE.finditer(data.decode('utf-8-sig', errors='strict')):
        groups = match.groups()
        first = next((groups[i] for i in (0,2,4) if groups[i]), None)
        last = next((groups[i] for i in (1,3,5) if groups[i]), None)
        if first:
            first, last = int(first), int(last or first)
            if not 0 < first <= last <= 2_147_483_647:
                raise ValueError('Invalid Translator chapter interval')
            if last - first > 100000: raise ValueError('Translator chapter interval is too large to verify')
            chapters.update(range(first, last + 1))
    return sorted(chapters)


def format_chapters(chapters):
    intervals = []
    for n in sorted(set(chapters)):
        if intervals and n == intervals[-1][1] + 1: intervals[-1][1] = n
        else: intervals.append([n,n])
    return ', '.join(str(first) if first == last else f'{first}–{last}' for first,last in intervals)


def completion_label(profile):
    chapters = completed_chapters(profile)
    if not chapters: return 'ยังไม่มี Export ที่ยืนยัน'
    highest = max(chapters)
    if min(chapters) == 1 and len(chapters) == highest:
        return f'แปลเสร็จถึงบท {highest}'
    latest = next((event for event in reversed(list(confirmed_events(profile))) if event['chapters']), None)
    return 'Export ล่าสุด: บท ' + format_chapters(latest['chapters'])


def completion_tooltip(profile):
    chapters = completed_chapters(profile)
    continuous = 0
    while continuous + 1 in chapters: continuous += 1
    return ('นับเฉพาะบทใหม่จาก Translator Export ที่สำเร็จครบทุกขั้นตอน\n'
            f'ยืนยันทั้งหมด {len(chapters):,} บท · บทสูงสุด {max(chapters, default=0):,}\n'
            f'ต่อเนื่องจากบท 1 ถึงบท {continuous:,} · Context และ TXT Submit ไม่นับยอดนี้')


def daily_chapter_count(profile: NovelProfile, day: str | None = None) -> int:
    return len(confirmed_daily_activity(profile).get(day or local_day(), set()))


def goal_progress(profile: NovelProfile) -> tuple[int, int, int] | None:
    target = profile.translation_goal_target
    if target is None or target <= 0: return None
    completed = max(0, completed_chapter_count(profile) - (profile.translator_goal_baseline or 0))
    return completed, target, min(100, round(completed * 100 / target))


def reset_goal_progress(profile: NovelProfile) -> bool:
    if profile.translation_goal_target is None: return False
    profile.translator_goal_baseline = completed_chapter_count(profile)
    return True


def restart_completed_goal_cycles(profile: NovelProfile) -> bool:
    # Compatibility only: goals now reset exclusively through explicit Reset.
    return False


def week_start(day: date | None = None) -> date:
    current = day or datetime.now().date()
    return current - timedelta(days=current.weekday())


def profile_week_count(profile: NovelProfile, today: date | None = None) -> int:
    end = today or datetime.now().date()
    start = week_start(end)
    return sum(
        len(chapters)
        for key, chapters in confirmed_daily_activity(profile).items()
        if start.isoformat() <= key <= end.isoformat()
    )
