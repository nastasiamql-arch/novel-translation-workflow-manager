"""Durable, profile-scoped history for explicit batch clipboard actions."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .storage import profile_guard, read_json, write_json


def source_identity(mode: str, path: str | Path | None, source_id: str | None = None) -> str:
    """Identify a user-selected source without conflating same-named novels."""
    resolved = str(Path(path).expanduser().resolve()) if path else ""
    value = json.dumps([mode, source_id or "", resolved], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def source_revision(parts) -> str:
    """Hash a stable, ordered source manifest supplied by the source loader."""
    payload = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_history(repo, profile_id: str, kind: str) -> list[dict]:
    path = repo.profile_dir(profile_id) / "batch_copy_history.json"
    try:
        value = read_json(path, {})
    except (OSError, ValueError):
        return []
    if not isinstance(value, dict) or value.get("schema_version", 1) not in (1, 2):
        return []
    events = value.get(kind, [])
    if not isinstance(events, list):
        return []
    return [event for event in events if isinstance(event, dict)
            and event.get("profile_id") == profile_id and event.get("success") is True
            and isinstance(event.get("source_identity"), str)
            and isinstance(event.get("source_revision"), str)
            and isinstance(event.get("chapter_numbers"), list)
            and all(isinstance(n, int) and n > 0 for n in event["chapter_numbers"])
            and isinstance(event.get("start"), int) and isinstance(event.get("end"), int)]


@profile_guard
def record_copy(repo, profile_id: str, kind: str, *, identity: str, revision: str,
                start: int, end: int, chapter_numbers, batch_size: int,
                copy_mode: str, copied_file_count: int, chapter_fingerprints=None) -> dict:
    """Atomically append a successful event after Clipboard accepts file URLs."""
    if kind not in {"translation", "vocabulary"}:
        raise ValueError("ประเภทประวัติชุดบทไม่ถูกต้อง")
    path = repo.profile_dir(profile_id) / "batch_copy_history.json"
    data = read_json(path, {})
    if not isinstance(data, dict):
        raise ValueError("ไฟล์ประวัติชุดบทมีโครงสร้างไม่ถูกต้อง จึงไม่เขียนทับไฟล์เดิม")
    if data.get("schema_version") not in (None, 1, 2):
        raise ValueError("รูปแบบประวัติชุดบทไม่รองรับ จึงไม่เขียนทับไฟล์เดิม")
    events = data.get(kind, [])
    if not isinstance(events, list):
        raise ValueError("ไฟล์ประวัติชุดบทเสียรูปแบบ จึงไม่เขียนทับไฟล์เดิม")
    event = {
        "profile_id": profile_id,
        "source_identity": identity,
        "source_revision": revision,
        "start": int(start),
        "end": int(end),
        "chapter_numbers": [int(n) for n in chapter_numbers],
        "batch_size": int(batch_size),
        "copy_mode": str(copy_mode),
        "copied_file_count": int(copied_file_count),
        "copied_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "success": True,
        "chapter_fingerprints": dict(chapter_fingerprints or {}),
    }
    data["schema_version"] = 2
    data[kind] = [*events, event]
    write_json(path, data)
    return event


def group_copy_status(events, *, identity: str, revision: str,
                      start: int, end: int, chapter_numbers, chapter_fingerprints=None) -> str:
    chapters = tuple(int(n) for n in chapter_numbers)
    for event in reversed(events):
        if event.get("source_identity") != identity:
            continue
        old_chapters = tuple(event.get("chapter_numbers") or ())
        if (event.get("source_revision") == revision
                and event.get("start") == int(start)
                and event.get("end") == int(end)
                and old_chapters == chapters):
            old_fingerprints = event.get("chapter_fingerprints") or {}
            if chapter_fingerprints is None or old_fingerprints == dict(chapter_fingerprints):
                return "copied"
            return "review"
    current = set(chapters)
    for event in events:
        if event.get("source_identity") != identity:
            continue
        old = set(event.get("chapter_numbers") or ())
        if current.intersection(old) or event.get("start", -1) <= end and event.get("end", -1) >= start:
            return "review"
    return "new"


def revision_summary(events, *, identity: str, revision: str, groups) -> dict:
    statuses = [group_copy_status(
        events, identity=identity, revision=revision,
        start=group.start, end=group.end,
        chapter_numbers=[chapter.number for chapter in group.chapters],
    ) for group in groups]
    copied = [i for i, status in enumerate(statuses) if status == "copied"]
    return {
        "total": len(groups), "copied": len(copied),
        "remaining": statuses.count("new"), "review": statuses.count("review"),
        "last_index": copied[-1] if copied else None,
        "next_index": next((i for i, status in enumerate(statuses) if status != "copied"), None),
        "statuses": statuses,
    }
