"""Verified export accounting, independent from rotating filenames."""
from datetime import datetime
from copy import deepcopy
from .translation_progress import local_day
from .text_normalization import remove_empty_lines


def record_export(profile, filename, prefix, sequence, timestamp=None):
    stamp = timestamp or datetime.now().astimezone().isoformat()
    profile.verified_export_history.append(dict(profile=profile.id, timestamp=stamp,
        filename=filename, prefix=prefix, sequence=sequence, success=True))
    profile.verified_goal_count += 1


def daily_export_count(profile, day=None):
    day = day or local_day()
    return sum(1 for event in profile.verified_export_history
               if event.get('success') and event.get('timestamp', '')[:10] == day)


def verified_goal_text(profile):
    count, target = profile.verified_goal_count, profile.verified_goal_target
    if not target or target <= 0:
        return f'{count} ไฟล์'
    text = f'{count}/{target}'
    if count >= target: text += ' ✓'
    if count > target: text += f' · +{count-target} เกินเป้า'
    return text


def reset_verified_goal(profile):
    profile.verified_goal_cycles.append(dict(count=profile.verified_goal_count,
        target=profile.verified_goal_target, reset_at=datetime.now().astimezone().isoformat()))
    profile.verified_goal_count = 0


class ExportService:
    def __init__(self, repo, profile_id):
        self.repo, self.profile_id = repo, profile_id

    def profile(self):
        return next(p for p in self.repo.list_profiles() if p.id == self.profile_id)

    def commit(self, filename, prefix, sequence, next_sequence, settings):
        profile = self.profile()
        profile.txt_export_settings = deepcopy(settings)
        profile.txt_export_settings.current = next_sequence
        record_export(profile, filename, prefix, sequence)
        self.repo.save_profile(profile)

    def set_target(self, target):
        profile = self.profile()
        profile.verified_goal_target = target or None
        settings = profile.txt_export_settings
        if not settings.advanced_range:
            settings.start, settings.end = 1, target or 100
            settings.current = max(1, min(settings.current, settings.end))
        self.repo.save_profile(profile)
        return profile

    def reset(self):
        profile = self.profile()
        reset_verified_goal(profile)
        self.repo.save_profile(profile)
        return profile

    def save_draft(self, text):
        profile = self.profile()
        if profile.txt_export_draft != text:
            profile.txt_export_draft = text
            self.repo.save_profile(profile)
