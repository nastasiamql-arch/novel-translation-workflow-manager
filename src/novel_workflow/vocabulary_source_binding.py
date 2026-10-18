"""Only the files enabled in a novel's existing vocabulary step.

The TXT tool must not invent a second glossary/prompt configuration or take
attachments from translation, review, export or other stages.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .polish_history import _files
from .vocabulary_batches import scan_chapter_files
from .workflow_archive import resolve_attachment


@dataclass(frozen=True)
class VocabularyAttachment:
    id: str
    label: str
    path: Path | None
    dynamic_reference: str | None = None
    error: str = ""


def enabled_vocabulary_attachments(repo, assembler, profile) -> tuple[VocabularyAttachment, ...]:
    step = profile.vocabulary_step
    if step is None:
        return ()
    result = []
    for item in sorted(step.files, key=lambda file: file.order):
        if not item.enabled:
            continue
        try:
            path = resolve_attachment(repo, assembler, profile, item)
            error = ""
        except (OSError, ValueError, KeyError, TypeError) as exc:
            path, error = None, str(exc)
        result.append(VocabularyAttachment(
            item.id, item.label or item.path or item.dynamic_reference or "ไฟล์",
            path, item.dynamic_reference, error,
        ))
    return tuple(result)


def chapter_source_directory(source: VocabularyAttachment | None) -> Path | None:
    if not source or source.path is None:
        return None
    return source.path if source.path.is_dir() else source.path.parent


def source_score(attachment: VocabularyAttachment) -> int:
    """High confidence selection only. An ambiguous source requires user choice."""
    path = attachment.path
    if path is None:
        return -1
    if attachment.dynamic_reference == "CURRENT_SOURCE_CHAPTER":
        return 150
    if path.is_dir():
        try:
            return 100 if scan_chapter_files(path) else 0
        except (OSError, ValueError):
            return 0
    if path.suffix.casefold() != ".txt":
        return 0
    name = path.stem.casefold()
    if re.search(r"prompt|glossary|vocab|dictionary|guideline|คำศัพท์|คำสั่ง|ไกด์|术语|词汇|提示", name):
        return 0
    if re.match(r"^0*[1-9]\d*(?:[\s._-].*)?$", name):
        return 130
    try:
        with path.open("r", encoding="utf-8-sig") as stream:
            sample = stream.read(18000)
    except (OSError, UnicodeError):
        return 0
    header = re.compile(r"^\s*(?:第[0-9０-９〇零一二两兩三四五六七八九十百千万萬亿億]+[章节節回]|(?:บทที่|ตอนที่|Chapter)\s*[0-9０-９]+)", re.M | re.I)
    detected = len(header.findall(sample))
    if detected >= 2:
        return 120
    if detected == 1:
        return 70
    return 0


def suggest_source_id(entries: tuple[VocabularyAttachment, ...]) -> str | None:
    candidates = [(source_score(e), e.id) for e in entries]
    if not candidates:
        return None
    candidates.sort(reverse=True)
    best = candidates[0][0]
    if best < 70 or len([score for score, _ in candidates if score == best]) != 1:
        return None
    return candidates[0][1]


def source_by_id(entries: tuple[VocabularyAttachment, ...], source_id: str | None):
    return next((entry for entry in entries if entry.id == source_id), None)


def batch_stage_files(batch, entries: tuple[VocabularyAttachment, ...],
                      selected_source_id: str, *, chapter_folder: Path | None = None) -> tuple[Path, ...]:
    """Five selected chapter files + only non-source enabled vocabulary files.

    Numbered siblings of the selected source are replaced by the current batch,
    preventing a linked CURRENT_SOURCE_CHAPTER or sibling chapter from being
    copied on top of unrelated batches.
    """
    source = source_by_id(entries, selected_source_id)
    if source is None or source.path is None:
        raise ValueError("ไม่พบต้นฉบับที่เลือกในขั้นตอนหาศัพท์ กรุณาตรวจไฟล์อีกครั้ง")
    folder = chapter_folder or chapter_source_directory(source)
    if folder is None:
        raise ValueError("ไม่พบโฟลเดอร์ต้นฉบับ")
    current_chapters = scan_chapter_files(folder)
    current = {entry.number: entry.path.resolve() for entry in current_chapters}
    expected = {chapter.number: chapter.path.resolve() for chapter in batch.chapters}
    if any(current.get(number) != path for number, path in expected.items()):
        raise ValueError("ไฟล์บทมีการเปลี่ยนแปลง กรุณากดรีเฟรชก่อนคัดลอก")
    numbered = set(current.values())
    originals = [chapter.path.resolve() for chapter in batch.chapters]
    attachments = []
    for entry in entries:
        if entry.id == selected_source_id or entry.dynamic_reference == "CURRENT_SOURCE_CHAPTER":
            continue
        if entry.path is None:
            raise ValueError(f"ไฟล์หาศัพท์ที่เปิดใช้งานไม่พร้อม: {entry.label}: {entry.error}")
        for file in _files(entry.path):
            if file.resolve() in numbered:
                continue
            attachments.append(file)
    result = []
    seen = set()
    for path in originals + attachments:
        key = str(path.resolve()).casefold()
        if key not in seen:
            seen.add(key)
            result.append(path)
    return tuple(result)
