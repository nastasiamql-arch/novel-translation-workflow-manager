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


    def save_story_schedule(self, profile_id: str, mode: str, *,
                            final_chapter: int, start_day: str | date,
                            duration_days: int | None = None,
                            daily_target: int | None = None,
                            deadline: str | date | None = None,
                            rest_weekdays=()):
        """Save one novel's dated plan, never write to its export ledger.

        'duration' means N working days, not N calendar days. Date overrides
        and edit history are preserved across subsequent schedule changes.
        """
        if mode not in ("duration", "daily", "deadline"):
            raise ValueError("Unknown story schedule mode")
        if not isinstance(profile_id, str) or not profile_id:
            raise ValueError("Select an existing novel")
        final = _positive(final_chapter)
        start = _date(start_day)
        days = _positive(duration_days) if mode == "duration" else None
        target = _positive(daily_target) if mode == "daily" else None
        due = _date(deadline) if mode == "deadline" and deadline is not None else None
        if mode == "deadline" and (due is None or due < start):
            raise ValueError("Deadline must be on or after the start day")
        weekdays = sorted(set(rest_weekdays))
        if any(type(day) is not int or day < 0 or day > 6 for day in weekdays):
            raise ValueError("Invalid rest weekday")
        if len(weekdays) == 7:
            raise ValueError("At least one working day is required")
        beginning = date.fromisoformat(start)
        if mode == "deadline" and not any(
            (beginning + timedelta(days=offset)).weekday() not in weekdays
            for offset in range((date.fromisoformat(due) - beginning).days + 1)
        ):
            raise ValueError("No working days before the deadline")
        profile = next((p for p in self.repo.list_profiles() if p.id == profile_id), None)
        if profile is None:
            raise ValueError("Select an existing novel")
        chapters = completed_chapters(profile)
        completed = len([n for n in chapters if 1 <= n <= final])
        # Count the same confirmed unique chapters used by Progress and Export.
        fields = {
            "profile_id": profile_id, "mode": mode, "final_chapter": final,
            "start_day": start, "duration_days": days, "daily_target": target,
            "deadline": due, "rest_weekdays": weekdays,
        }
        with self.repo.profile_lock:
            data = self._load()
            schedules = data.setdefault("story_schedules", {})
            if not isinstance(schedules, dict):
                raise ValueError("Invalid story schedules")
            previous = schedules.get(profile_id, {})
            if not isinstance(previous, dict):
                raise ValueError("Invalid story schedule")
            now = _now()
            history = list(previous.get("history", []))
            if previous and any(previous.get(k) != v for k, v in fields.items()):
                history.append({"changed_at": now, "previous": {
                    k: previous.get(k) for k in fields}})
            schedule = {**previous, **fields,
                        "baseline_completed": (previous.get("baseline_completed", completed)
                                               if previous.get("start_day") == start
                                               and previous.get("final_chapter") == final
                                               else completed),
                        "overrides": dict(previous.get("overrides", {})),
                        "history": history, "updated_at": now}
            schedule.setdefault("created_at", now)
            schedules[profile_id] = schedule
            # Reuse the long-term goal record so older Progress views agree.
            goals = data.setdefault("finish_goals", {})
            prior_goal = goals.get(profile_id, {})
            if not isinstance(prior_goal, dict):
                prior_goal = {}
            goals[profile_id] = {
                **prior_goal, "profile_id": profile_id, "final_chapter": final,
                "confirmed_finished": (prior_goal.get("confirmed_finished", False)
                                       if prior_goal.get("final_chapter") == final else False),
                "updated_at": now,
            }
            data["schema_version"] = max(3, data.get("schema_version", 0))
            write_json(self.path, data)
        return dict(schedule)

    def story_schedule(self, profile_id: str):
        schedule = self._load().get("story_schedules", {}).get(profile_id)
        return dict(schedule) if isinstance(schedule, dict) else None

    def override_story_day(self, profile_id: str, day: str | date, target: int):
        """Zero is a rest day; positive values override one day's chapter goal."""
        local_day = _date(day)
        if type(target) is not int or target < 0:
            raise ValueError("Day goal must be a nonnegative integer")
        with self.repo.profile_lock:
            data = self._load()
            schedule = data.get("story_schedules", {}).get(profile_id)
            if not isinstance(schedule, dict):
                raise ValueError("No schedule for this novel")
            # Reject editing days outside the plan, including foreign novel IDs.
            dates = self._story_dates(schedule, date.fromisoformat(local_day),
                                      max_days=3660)
            if local_day not in {d.isoformat() for d in dates}:
                raise ValueError("Day is outside the schedule")
            overrides = schedule.setdefault("overrides", {})
            if not isinstance(overrides, dict):
                raise ValueError("Invalid day overrides")
            old = overrides.get(local_day)
            if old != target:
                schedule.setdefault("history", []).append({
                    "changed_at": _now(), "date": local_day, "previous_target": old,
                    "new_target": target})
                overrides[local_day] = target
                schedule["updated_at"] = _now()
                write_json(self.path, data)
        return target

    @staticmethod
    def _story_dates(schedule, today: date, *, max_days=3660):
        start = date.fromisoformat(schedule["start_day"])
        rest = set(schedule.get("rest_weekdays", ()))
        mode = schedule["mode"]
        dates = []
        working = 0
        final_working = schedule.get("duration_days")
        if mode == "daily":
            # Daily quota can extend beyond the original estimated finish date.
            quota = schedule["daily_target"]
            outstanding = max(0, schedule["final_chapter"] -
                              schedule.get("baseline_completed", 0))
            final_working = max(1, (outstanding + quota - 1) // quota)
        deadline = (date.fromisoformat(schedule["deadline"])
                    if mode == "deadline" else None)
        for offset in range(max_days):
            day = start + timedelta(days=offset)
            if deadline is not None and day > deadline:
                break
            dates.append(day)
            override = schedule.get("overrides", {}).get(day.isoformat())
            if override != 0 and (day.weekday() not in rest or override is not None):
                working += 1
            if final_working is not None and working >= final_working:
                # For an uncapped daily plan, show today's work even if it has
                # taken longer than the initial estimate.
                if mode != "daily" or day >= today:
                    break
        return dates

    def story_day_rows(self, profile_id: str, today: str | date | None = None):
        """Return date targets dynamically recalculated from verified exports.

        Past targets are computed using past export activity; missing or extra
        completions alter only the remaining allocation. No export is written.
        """
        local_today = date.fromisoformat(_date(today or date.today()))
        schedule = self.story_schedule(profile_id)
        if schedule is None:
            return None
        profile = next((p for p in self.repo.list_profiles() if p.id == profile_id), None)
        if profile is None:
            return None
        final = schedule["final_chapter"]
        chapters = {n for n in completed_chapters(profile) if 1 <= n <= final}
        activity = confirmed_daily_activity(profile)
        dates = self._story_dates(schedule, local_today)
        overrides = schedule.get("overrides", {})
        rest = set(schedule.get("rest_weekdays", ()))
        active = [day for day in dates
                  if overrides.get(day.isoformat()) != 0
                  and (day.weekday() not in rest
                       or overrides.get(day.isoformat()) is not None)]
        if not active:
            return {"profile": profile, "schedule": schedule, "rows": [],
                    "completed": len(chapters), "remaining": max(0, final - len(chapters)),
                    "percent": min(100, round(len(chapters) * 100 / final))}
        baseline_remaining = max(0, final - schedule.get("baseline_completed", 0))
        past_remaining = baseline_remaining
        # Today's already exported chapters still count against today's fixed
        # target. They are subtracted from *tomorrow's* distribution.
        today_actual = len(activity.get(local_today.isoformat(), set()) & chapters)
        current_remaining = max(0, final - len(chapters) + today_actual)
        # Reserve manually assigned future targets before distributing the
        # unassigned chapters. Otherwise a 90-chapter, three-day plan with
        # an 80-chapter override on day three would incorrectly total 140.
        flexible_future = [day for day in active
                           if day >= local_today
                           and overrides.get(day.isoformat()) is None]
        manual_future = sum(overrides[day.isoformat()] for day in active
                            if day >= local_today
                            and overrides.get(day.isoformat()) is not None)
        future_remaining = max(0, current_remaining - manual_future)
        rows = []
        for day in dates:
            key = day.isoformat()
            actual = len(activity.get(key, set()) & chapters)
            override = overrides.get(key)
            is_rest = override == 0 or (override is None and day.weekday() in rest)
            work_left = sum(1 for other in (
                active if day < local_today else flexible_future
            ) if other >= day)
            if is_rest:
                target = 0
            elif override is not None:
                target = override
            elif schedule["mode"] == "daily":
                target = min(schedule["daily_target"],
                             past_remaining if day < local_today else future_remaining)
            elif day < local_today:
                target = (past_remaining + work_left - 1) // work_left if work_left else 0
            else:
                target = (future_remaining + work_left - 1) // work_left if work_left else 0
            if day < local_today:
                past_remaining = max(0, past_remaining - actual)
            elif override is None:
                # Fixed manual quotas were already reserved above.
                future_remaining = max(0, future_remaining - target)
            if is_rest:
                status = "วันพัก"
            elif day < local_today:
                status = "เกินเป้า" if actual > target else (
                    "ตามแผน" if actual == target else "ต่ำกว่าแผน")
            elif actual > target and target:
                status = "เกินเป้า"
            elif actual >= target and target:
                status = "ตามแผน"
            else:
                status = "กำลังแปล" if day == local_today else "รอดำเนินการ"
            rows.append({"date": key, "target": target, "actual": actual,
                         "status": status, "rest": is_rest})
        return {"profile": profile, "schedule": schedule, "rows": rows,
                "completed": len(chapters), "remaining": max(0, final - len(chapters)),
                "percent": min(100, round(len(chapters) * 100 / final))}

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
