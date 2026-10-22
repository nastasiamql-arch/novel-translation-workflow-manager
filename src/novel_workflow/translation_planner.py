"""Persistent, manual translation planning backed exclusively by confirmed exports.

Planner data lives outside profile.json to avoid changing existing novel schemas.
The activity ledger remains owned by translation_progress; plans never mutate it.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from .storage import read_json, write_json
from .translation_progress import completed_chapters, confirmed_daily_activity

PLAN_TYPES = ("focus", "daily", "finish", "rest")


def _date(value: str | date) -> str:
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str):
        raise ValueError("Invalid local date")
    try:
        day = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Invalid local date") from exc
    if day.isoformat() != value:
        raise ValueError("Invalid local date")
    return value


def _positive(value, *, optional=False):
    if optional and value is None:
        return None
    if type(value) is not int or not 1 <= value <= 2_147_483_647:
        raise ValueError("Chapter goal must be a positive integer")
    return value


def _now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


class TranslationPlanner:
    """Small atomic JSON store; keeps unknown extension fields on every edit."""

    def __init__(self, repository):
        self.repo = repository
        self.path = Path(repository.root) / "translation_planner.json"

    def _load(self):
        data = read_json(self.path, {})
        if not isinstance(data, dict):
            raise ValueError("Invalid planner data")
        if not isinstance(data.get("days", {}), dict) or not isinstance(data.get("finish_goals", {}), dict):
            raise ValueError("Invalid planner collections")
        return data

    def get(self, day: str | date):
        value = self._load().get("days", {}).get(_date(day))
        return dict(value) if isinstance(value, dict) else None

    def save(self, day: str | date, profile_id: str | None, plan_type: str,
             *, target_chapters: int | None = None, final_chapter: int | None = None):
        local_date = _date(day)
        if plan_type not in PLAN_TYPES:
            raise ValueError("Unknown plan type")
        if plan_type != "rest":
            known = {profile.id for profile in self.repo.list_profiles()}
            if not profile_id or profile_id not in known:
                raise ValueError("Select an existing novel")
        else:
            profile_id = None
        target = _positive(target_chapters) if plan_type == "daily" else None
        final = _positive(final_chapter, optional=True) if plan_type == "finish" else None
        # Serialize edits with other repository writes, protecting concurrent UI jobs.
        with self.repo.profile_lock:
            data = self._load()
            days = data.setdefault("days", {})
            previous = days.get(local_date)
            previous = previous if isinstance(previous, dict) else {}
            now = _now()
            history = list(previous.get("history", [])) if isinstance(previous.get("history", []), list) else []
            fields = {
                "profile_id": profile_id, "local_date": local_date,
                "plan_type": plan_type, "target_chapters": target,
                "final_chapter": final,
            }
            if previous and any(previous.get(key) != value for key, value in fields.items()):
                history.append({"changed_at": now, "previous": {
                    key: previous.get(key) for key in fields
                }})
            plan = {**previous, **fields}
            plan.setdefault("id", uuid4().hex)
            plan.setdefault("created_at", now)
            plan["updated_at"] = now
            plan["history"] = history
            days[local_date] = plan
            if plan_type == "finish":
                goals = data.setdefault("finish_goals", {})
                previous_goal = goals.get(profile_id, {})
                if not isinstance(previous_goal, dict):
                    previous_goal = {}
                goals[profile_id] = {
                    **previous_goal, "profile_id": profile_id,
                    "final_chapter": final, "confirmed_finished": False,
                    "updated_at": now,
                }
            write_json(self.path, data)
        return dict(plan)

    def finish_goal(self, profile_id):
        return self._load().get("finish_goals", {}).get(profile_id)

    def confirm_finished(self, profile_id: str, finished: bool = True):
        with self.repo.profile_lock:
            data = self._load()
            goal = data.get("finish_goals", {}).get(profile_id)
            if not isinstance(goal, dict):
                raise ValueError("No long-term completion goal exists")
            goal["confirmed_finished"] = bool(finished)
            goal["updated_at"] = _now()
            write_json(self.path, data)

    def week(self, first_day: date | None = None):
        start = first_day or date.today()
        return [
            (day.isoformat(), self.get(day))
            for day in (start + timedelta(days=offset) for offset in range(7))
        ]

    def summary(self, day: str | date, profiles=None):
        local_date = _date(day)
        plan = self.get(local_date)
        if plan is None:
            return {"status": "empty", "day": local_date}
        if plan.get("plan_type") == "rest":
            return {"status": "rest", "day": local_date, "plan": plan}
        profiles = profiles if profiles is not None else self.repo.list_profiles()
        profile = next((p for p in profiles if p.id == plan.get("profile_id")), None)
        if profile is None:
            return {"status": "missing_profile", "day": local_date, "plan": plan}
        kind = plan.get("plan_type")
        chapters = completed_chapters(profile)
        activity = confirmed_daily_activity(profile)
        today_count = len(activity.get(local_date, set()))
        result = {
            "status": "active", "day": local_date, "plan": plan,
            "profile": profile, "today_count": today_count,
            "completed_total": len(chapters), "percent": None,
            "remaining": None, "missing_preview": [],
        }
        if kind == "daily":
            target = plan["target_chapters"]
            if type(target) is int and target > 0:
                result["percent"] = min(100, round(today_count * 100 / target))
                result["remaining"] = max(0, target - today_count)
                result["excess"] = max(0, today_count - target)
        if kind == "finish":
            goal = self.finish_goal(profile.id) or {}
            final = goal.get("final_chapter")
            result["confirmed_finished"] = goal.get("confirmed_finished") is True
            if type(final) is int and final > 0:
                within = sum(1 for n in chapters if 1 <= n <= final)
                result["percent"] = min(100, round(within * 100 / final))
                result["remaining"] = final - within
                result["missing_preview"] = [
                    n for n in range(1, final + 1) if n not in chapters
                ][:10]
                result["final_chapter"] = final
        return result
