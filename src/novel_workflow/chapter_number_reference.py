"""Read-only chapter start suggestion from a uniquely bound novel Translator file.

The original Chinese file is never read or modified by this resolver. A Translator
chapter is a hint, not evidence that a website has no missing chapters.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from .translation_progress import translator_chapters


@dataclass(frozen=True)
class TranslatorReference:
    start: int | None
    latest: int | None
    path: Path | None
    source: str
    message: str


def _normal_stem(stem: str) -> str:
    return re.sub(r"[\W_]+", "", stem.casefold())


def should_auto_propose(headings, start: int | None) -> bool:
    """Only propose for an isolated, already-sequential incoming chapter batch."""
    if start is None or not headings or headings[0].number < start:
        return False
    return all(
        heading.number == headings[0].number + index
        for index, heading in enumerate(headings)
    ) and start + len(headings) - 1 <= 2_147_483_647


def _bound_paths(repo, profile):
    references = list(profile.working_files)
    for step in profile.workflow.steps:
        references.extend(step.files)
    if profile.vocabulary_step is not None:
        references.extend(profile.vocabulary_step.files)
    paths = set()
    for item in references:
        if not item.path or item.reference_type == "dynamic":
            continue
        try:
            path = (
                Path(item.path).expanduser().resolve()
                if item.reference_type == "external_file"
                else repo.resolve_project_path(profile.id, item.path).resolve()
            )
        except (OSError, TypeError, ValueError):
            continue
        paths.add(path)
    return paths


def _latest_confirmed_export(profile, path: Path) -> int | None:
    latest = None
    for event in profile.translator_export_events:
        if not isinstance(event, dict):
            continue
        if event.get("status") != "committed" or event.get("profile_id") != profile.id:
            continue
        try:
            source = Path(event["translator_path"]).expanduser().resolve()
            if source != path:
                continue
            chapters = event.get("chapters")
            if (not isinstance(chapters, list) or
                    not all(type(n) is int and 0 < n <= 2_147_483_647 for n in chapters)):
                continue
            if chapters:
                highest = max(chapters)
                latest = highest if latest is None else max(highest, latest)
        except (ValueError, OSError, TypeError, KeyError):
            continue
    return latest


def resolve_translator_reference(
    repo, profile_id: str, source_path: Path,
    open_texts: dict[Path, str] | None = None,
) -> TranslatorReference:
    """Resolve only this novel's uniquely owned and uniquely chosen Translator.

    The open_texts mapping takes precedence over disk to account for unsaved
    Translator edits visible in the same workspace. No Context files are read.
    """
    missing = lambda reason: TranslatorReference(None, None, None, "ไม่มี", reason)
    profiles = repo.list_profiles()
    profile = next((p for p in profiles if p.id == profile_id), None)
    if profile is None:
        return missing("ไม่พบ Novel Profile ที่เลือก")
    source_path = Path(source_path).expanduser().resolve()
    bindings = {p.id: _bound_paths(repo, p) for p in profiles}
    candidates = sorted(
        (p for p in bindings[profile_id]
         if p != source_path and p.name.casefold().endswith("translator.txt")
         and sum(p in owned for owned in bindings.values()) == 1),
        key=lambda p: str(p).casefold(),
    )
    if not candidates:
        return missing("ไม่พบไฟล์ Translator ที่ผูกเฉพาะนิยายเรื่องนี้ · กรุณาระบุเลขเริ่มต้นเอง")
    if len(candidates) > 1:
        source_stem = _normal_stem(source_path.stem)
        matching = [
            p for p in candidates
            if _normal_stem(p.stem[:-len("translator")]) == source_stem
        ]
        if len(matching) != 1:
            return missing("พบ Translator หลายไฟล์ของเรื่องนี้ จึงไม่เลือกไฟล์ใดโดยเดา")
        path = matching[0]
    else:
        path = candidates[0]

    try:
        if open_texts is not None and path in open_texts:
            data = open_texts[path].encode("utf-8")
        else:
            data = path.read_bytes()
        chapters = translator_chapters(data)
    except (OSError, UnicodeError, ValueError) as exc:
        return missing(f"อ่านเลขบทจาก {path.name} ไม่สำเร็จ ({type(exc).__name__})")
    latest_in_file = max(chapters, default=None)
    latest_exported = _latest_confirmed_export(profile, path)
    if (latest_in_file is not None and latest_exported is not None
            and latest_exported > latest_in_file):
        return missing(
            f"{path.name} มีบทสูงสุด {latest_in_file} แต่ประวัติ Export ยืนยันถึง "
            f"{latest_exported} · ข้อมูลไม่ตรงกัน กรุณาตรวจเลขเริ่มต้นเอง"
        )
    latest = latest_in_file if latest_in_file is not None else latest_exported
    if latest is None:
        return missing(f"{path.name} ไม่มีหัวบทที่อ่านได้ และไม่มีประวัติ Export ที่ยืนยัน")
    if latest >= 2_147_483_647:
        return missing("หมายเลขบทล่าสุดถึงขีดจำกัดที่รองรับ")
    origin = "Translator" if latest_in_file is not None else "ประวัติ Export ของ Translator"
    return TranslatorReference(
        start=latest + 1, latest=latest, path=path, source=origin,
        message=f"{origin}: {path.name} · บทล่าสุด {latest} · เสนอเริ่มบท {latest + 1}",
    )
