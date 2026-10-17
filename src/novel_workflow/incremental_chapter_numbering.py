"""Verified incremental source chapter renumbering for one-by-one append workflows.

Only a previously saved/verified chapter-numbering snapshot can authorize
preserving an already-corrected prefix. Without that proof we refuse gaps.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from .chapter_numbering import (
    _MAX, _SUSPECT_HEADING, automatic_renumber_plan, preview_renumber,
    scan_chapters,
)
from .storage import read_json


def automatic_append_plan(text: str, start: int, verified_prefix: str | None = None):
    """Return (new_text, changes), altering only newly appended chapter headings.

    The prefix must exactly match the recorded corrected file (including story
    text), and its numbers must still be sequential from the Translator.
    """
    if verified_prefix is None:
        return automatic_renumber_plan(text, start)
    if not verified_prefix or not text.startswith(verified_prefix):
        raise ValueError("เนื้อหาบทเก่าเปลี่ยนหลังตรวจ กรุณาตรวจด้วยตนเอง")
    old = scan_chapters(verified_prefix)
    all_headings = scan_chapters(text)
    if not old or [h.number for h in old] != list(range(start, start + len(old))):
        raise ValueError("เลขบทเก่าที่บันทึกไว้ไม่ตรง Translator")
    if len(all_headings) < len(old) or any(
        (a.number, a.number_start, a.number_end) !=
        (b.number, b.number_start, b.number_end)
        for a, b in zip(old, all_headings)
    ):
        raise ValueError("หัวบทเดิมเปลี่ยนหลังตรวจ กรุณาตรวจด้วยตนเอง")
    # A newly pasted heading must be on a fresh line, not concatenate with
    # the final story paragraph of the last validated chapter.
    if (len(text) > len(verified_prefix)
            and not verified_prefix.endswith(("\n", "\r"))
            and not text[len(verified_prefix):].startswith(("\n", "\r"))):
        raise ValueError("บทใหม่ไม่ได้เริ่มบรรทัดใหม่")
    known_lines = {h.line for h in all_headings}
    fenced = False
    for line_index, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            continue
        if not fenced and _SUSPECT_HEADING.match(line) and line_index not in known_lines:
            raise ValueError("พบหัวบทที่อ่านเลขไม่ได้ กรุณาตรวจเองก่อนแก้")
    fresh = all_headings[len(old):]
    if any(h.number_start < len(verified_prefix) for h in fresh):
        raise ValueError("พบการเปลี่ยนหัวบทเดิม")
    if not fresh:
        return text, []
    next_chapter = start + len(old)
    if next_chapter + len(fresh) - 1 > _MAX:
        raise ValueError("เลขบทใหม่เกินช่วงที่รองรับ")
    if (fresh[0].number < next_chapter or any(
            h.number != fresh[0].number + index
            for index, h in enumerate(fresh))):
        raise ValueError("บทใหม่มีเลขซ้ำ/ย้อนกลับ/กระโดดจริง กรุณาตรวจด้วยตนเอง")
    return preview_renumber(
        text, {len(old) + index: next_chapter + index
               for index in range(len(fresh))}
    )


def verified_prefix_from_history(profile_dir, profile_id, source_path, text, start):
    """Reconstruct the latest finished correction, verifying both SHA256 hashes.

    A deleted/changed snapshot, reverted correction, different Translator start
    or modified story text cannot authorize a new unattended correction.
    """
    source_path = Path(source_path).resolve()
    history_dir = (Path(profile_dir) / "chapter_numbering").resolve()
    history = read_json(history_dir / "history.json", {"events": []})
    if not isinstance(history, dict) or not isinstance(history.get("events"), list):
        return None
    event = next((
        e for e in reversed(history["events"])
        if isinstance(e, dict) and e.get("profile_id") == profile_id
        and e.get("path") == str(source_path)
    ), None)
    if not event or event.get("reverted") or not isinstance(event.get("changes"), list):
        return None
    name = event.get("snapshot")
    if not isinstance(name, str) or Path(name).name != name:
        return None
    path = (history_dir / name).resolve()
    if path.parent != history_dir:
        return None
    backup = read_json(path, None)
    if (not isinstance(backup, dict) or backup.get("profile_id") != profile_id
            or backup.get("path") != str(source_path)
            or not isinstance(backup.get("text"), str)):
        return None
    before = backup["text"]
    if hashlib.sha256(before.encode("utf-8")).hexdigest() != event.get("before_sha256"):
        return None
    old = scan_chapters(before)
    by_line = {h.line: (i, h.number) for i, h in enumerate(old)}
    replacements = {}
    for change in event["changes"]:
        if not isinstance(change, dict):
            return None
        found = by_line.get(change.get("line"))
        if found is None or found[1] != change.get("original"):
            return None
        replacements[found[0]] = change.get("corrected")
    if not replacements:
        return None
    try:
        after, _ = preview_renumber(before, replacements)
    except (ValueError, TypeError):
        return None
    if hashlib.sha256(after.encode("utf-8")).hexdigest() != event.get("after_sha256"):
        return None
    if not text.startswith(after):
        return None
    headings = scan_chapters(after)
    if not headings or [h.number for h in headings] != list(
        range(start, start + len(headings))
    ):
        return None
    return after
