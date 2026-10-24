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
        """Normalize legacy days in memory; persist migration only when editing."""
        data = read_json(self.path, {})
        if not isinstance(data, dict):
            raise ValueError("Invalid planner data")
        if not isinstance(data.get("days", {}), dict) or not isinstance(data.get("finish_goals", {}), dict):
            raise ValueError("Invalid planner collections")
        days = data.setdefault("days", {})
        for day, item in list(days.items()):
            _date(day)
            if not isinstance(item, dict):
                raise ValueError("Invalid planner day")
            if "plans" in item:
                if not isinstance(item["plans"], dict) or not all(
                    isinstance(key, str) and isinstance(plan, dict)
                    for key, plan in item["plans"].items()
                ):
                    raise ValueError("Invalid per-novel plans")
            elif "plan_type" in item:
                key = item.get("profile_id") or "__global__"
                if not isinstance(key, str):
                    raise ValueError("Invalid legacy plan profile")
                days[day] = {"plans": {key: item}}
            else:
                raise ValueError("Unrecognized planner day structure")
        return data

    def plans_for_day(self, day: str | date):
        bucket = self._load().get("days", {}).get(_date(day), {})
        return [dict(item) for item in bucket.get("plans", {}).values()]

    def get(self, day: str | date, profile_id: str | None = None):
        bucket = self._load().get("days", {}).get(_date(day), {})
        plans = bucket.get("plans", {})
        plan = plans.get(profile_id) if profile_id is not None else next(iter(plans.values()), None)
        return dict(plan) if isinstance(plan, dict) else None

    def active_for_day(self, day: str | date, profile_id: str | None = None):
        """A finish goal carries for its novel even if other novels have plans."""
        local_date = _date(day)
        data = self._load()
        days = data.get("days", {})
        plans = days.get(local_date, {}).get("plans", {})
        if profile_id is None:
            explicit = next(iter(plans.values()), None)
        else:
            explicit = plans.get(profile_id)
            if explicit is None:
                global_rest = plans.get("__global__")
                if isinstance(global_rest, dict) and global_rest.get("plan_type") == "rest":
                    explicit = global_rest
        if isinstance(explicit, dict):
            return dict(explicit)
        eligible = []
        for key, bucket in days.items():
            if key > local_date:
                continue
            for plan in bucket.get("plans", {}).values():
                if plan.get("plan_type") != "finish":
                    continue
                if profile_id is not None and plan.get("profile_id") != profile_id:
                    continue
                eligible.append((key, plan))
        for _key, plan in sorted(eligible, key=lambda pair: pair[0], reverse=True):
            goal = data.get("finish_goals", {}).get(plan.get("profile_id"), {})
            if isinstance(goal, dict) and goal.get("confirmed_finished") is not True:
                return {**plan, "carried_from": plan.get("local_date")}
        return None

    def save(self, day: str | date, profile_id: str | None, plan_type: str,
             *, target_chapters: int | None = None, final_chapter: int | None = None):
        local_date = _date(day)
        if plan_type not in PLAN_TYPES:
            raise ValueError("Unknown plan type")
        # None remains a supported global rest for migrated old documents.
        if plan_type != "rest" or profile_id is not None:
            known = {profile.id for profile in self.repo.list_profiles()}
            if not profile_id or profile_id not in known:
                raise ValueError("Select an existing novel")
        target = _positive(target_chapters) if plan_type == "daily" else None
        final = _positive(final_chapter, optional=True) if plan_type == "finish" else None
        with self.repo.profile_lock:
            data = self._load()
            data["schema_version"] = 2
            days = data.setdefault("days", {})
            bucket = days.setdefault(local_date, {"plans": {}})
            plans = bucket["plans"]
            key = profile_id or "__global__"
            previous = plans.get(key)
            previous = previous if isinstance(previous, dict) else {}
            now = _now()
            history = list(previous.get("history", [])) if isinstance(previous.get("history", []), list) else []
            fields = {
                "profile_id": profile_id, "local_date": local_date,
                "plan_type": plan_type, "target_chapters": target,
                "final_chapter": final,
            }
            if previous and any(previous.get(field) != value for field, value in fields.items()):
                history.append({"changed_at": now, "previous": {
                    field: previous.get(field) for field in fields
                }})
            plan = {**previous, **fields}
            plan.setdefault("id", uuid4().hex)
            plan.setdefault("created_at", now)
            plan["updated_at"] = now
            plan["history"] = history
            plans[key] = plan
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

    def week_all(self, first_day: date | None = None):
        start = first_day or date.today()
        return [
            (day.isoformat(), self.plans_for_day(day))
            for day in (start + timedelta(days=offset) for offset in range(7))
        ]

    def summary(self, day: str | date, profiles=None, *, profile_id=None):
        local_date = _date(day)
        plan = self.active_for_day(local_date, profile_id=profile_id)
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
                # Find only the first ten gaps; never iterate to a potentially
                # enormous announced final chapter in the UI thread.
                gaps = []
                expected = 1
                for number in sorted(n for n in chapters if 1 <= n <= final):
                    while expected < number and len(gaps) < 10:
                        gaps.append(expected)
                        expected += 1
                    expected = number + 1
                    if len(gaps) >= 10:
                        break
                while expected <= final and len(gaps) < 10:
                    gaps.append(expected)
                    expected += 1
                result["missing_preview"] = gaps
                result["final_chapter"] = final
        return result
