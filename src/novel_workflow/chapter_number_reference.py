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


def matched_translator_path(repo, profile_id: str, source_path: Path):
    """Resolve an exclusive same-codename Translator; generic tabs are excluded."""
    try:
        source_path = Path(source_path).expanduser().resolve()
        profiles = repo.list_profiles()
        profile = next((p for p in profiles if p.id == profile_id), None)
        if profile is None:
            return None, "ไม่พบ Novel Profile ที่เลือก"
        if (source_path.name.casefold() == "novel.txt"
                or source_path.suffix.casefold() not in {".txt", ".md", ".markdown"}
                or source_path.name.casefold().endswith(
                    ("translator.txt", "context.txt", "glossary.txt", "vocabulary.txt")
                )):
            return None, "แท็บนี้ไม่ใช่ไฟล์ต้นฉบับที่จับคู่กับ Translator"
        bound = {p.id: _bound_paths(repo, p) for p in profiles}
        own = bound[profile_id]
        root = repo.profile_dir(profile_id).resolve()
        main = Path(profile.main_folder).expanduser().resolve() if profile.main_folder else None
        if main is not None and any(
            p.id != profile_id and p.main_folder
            and Path(p.main_folder).expanduser().resolve() == main
            for p in profiles
        ):
            main = None
        authorized = (
            source_path in own or source_path.is_relative_to(root)
            or (main is not None and source_path.is_relative_to(main))
        )
        candidates = []
        for path in own:
            if (path != source_path and path.name.casefold().endswith("translator.txt")
                    and _normal_stem(path.stem[:-len("translator")]) == _normal_stem(source_path.stem)
                    and sum(path in other for other in bound.values()) == 1
                    and (authorized or path.parent == source_path.parent)):
                candidates.append(path)
        if authorized:
            sibling = source_path.with_name(source_path.stem + "Translator.txt")
            if (sibling.is_file() and not any(
                    sibling in paths for pid, paths in bound.items() if pid != profile_id
            ) and sibling not in candidates):
                candidates.append(sibling.resolve())
        if len(candidates) > 1:
            return None, "พบ Translator หลายไฟล์ที่ชื่อจับคู่กัน จึงไม่เดาไฟล์"
        if not candidates:
            available = sum(
                path.name.casefold().endswith("translator.txt") for path in own
            )
            return None, (
                "พบ Translator หลายไฟล์ แต่ไม่มีไฟล์ที่ชื่อจับคู่กับต้นฉบับ"
                if available > 1 else "ไม่พบ Translator ที่ชื่อจับคู่กับต้นฉบับในนิยายนี้"
            )
        return candidates[0], ""
    except (OSError, ValueError, TypeError) as exc:
        return None, f"ตรวจการจับคู่ไฟล์ไม่สำเร็จ ({type(exc).__name__})"


def resolve_translator_reference(
    repo, profile_id: str, source_path: Path,
    open_texts: dict[Path, str] | None = None,
) -> TranslatorReference:
    """Resolve only this novel's uniquely owned and uniquely chosen Translator.

    The open_texts mapping takes precedence over disk to account for unsaved
    Translator edits visible in the same workspace. No Context files are read.
    """
    missing = lambda reason: TranslatorReference(None, None, None, "ไม่มี", reason)
    path, reason = matched_translator_path(repo, profile_id, source_path)
    if path is None:
        return missing(reason)
    profile = next((p for p in repo.list_profiles() if p.id == profile_id), None)
    if profile is None:
        return missing("ไม่พบ Novel Profile ที่เลือก")

    try:
        if open_texts is not None and path in open_texts:
            data = open_texts[path].encode("utf-8")
        else:
            data = path.read_bytes()
        chapters = translator_chapters(data)
    except (OSError, UnicodeError, ValueError) as exc:
        return missing(f"อ่านเลขบทจาก {path.name} ไม่สำเร็จ ({type(exc).__name__})")
    latest = max(chapters, default=None)
    if latest is None:
        return missing(
            f"{path.name} ไม่มีหัวบทที่อ่านได้ · ไม่ใช้ประวัติ Export เก่ากำหนดเลข"
        )
    if latest >= 2_147_483_647:
        return missing("หมายเลขบทล่าสุดถึงขีดจำกัดที่รองรับ")
    old_export = _latest_confirmed_export(profile, path)
    note = (
        f" · เคย Export ถึง {old_export} (ประวัติเดิม ไม่ใช่เลขอ้างอิง)"
        if old_export is not None and old_export > latest else ""
    )
    return TranslatorReference(
        start=latest + 1, latest=latest, path=path, source="Translator",
        message=f"Translator: {path.name} · บทล่าสุด {latest} · "
                f"เสนอเริ่มบท {latest + 1}{note}",
    )
