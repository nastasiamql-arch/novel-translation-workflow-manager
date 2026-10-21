"""Read-only chapter sources and numbered groups for the translation stage.

Parsing reuses the existing vocabulary parser; no Translator, Context, Export,
progress counters or workflow state is ever mutated here.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .vocabulary_batches import (
    ChapterFile, PastedChapter, make_chapter_batches, parse_pasted_chapters,
    scan_chapter_files, split_missing_numbers,
)
from .workflow_archive import _check_path, file_digest


@dataclass(frozen=True)
class TranslationChapter:
    number: int
    filename: str
    path: Path | None = None
    content: bytes | None = None


@dataclass(frozen=True)
class TranslationSource:
    chapters: tuple[TranslationChapter, ...]
    signatures: tuple[tuple[Path, bytes], ...]
    folder: Path | None = None
    raw_text: str | None = None
    # Cheap directory-wide change detection after the initial full fingerprint.
    # Only copied chapters need another content hash on subsequent copies.
    file_stats: tuple[tuple[Path, tuple[int, int, int, int]], ...] = ()


def _stat_signature(path: Path) -> tuple[int, int, int, int]:
    info = path.stat()
    return (info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_ino)


def _signature(path: Path) -> tuple[Path, bytes]:
    resolved = _check_path(path)
    if not resolved.is_file():
        raise ValueError(f"ไม่ใช่ไฟล์ต้นฉบับ: {resolved}")
    before = _stat_signature(resolved)
    digest = file_digest(resolved)
    if _stat_signature(resolved) != before:
        raise ValueError(f"ต้นฉบับเปลี่ยนระหว่างตรวจ: {resolved.name}")
    return resolved, digest


def _split_text(text: str) -> tuple[TranslationChapter, ...]:
    segments = parse_pasted_chapters(text)
    if "".join(segment.text for segment in segments) != text:
        raise ValueError("ต้นฉบับมีข้อความที่ไม่ได้จัดสรรเข้าบท กรุณาตรวจหัวบท")
    return tuple(
        TranslationChapter(ch.number, ch.filename, content=ch.text.encode("utf-8"))
        for ch in sorted(segments, key=lambda x: x.number)
    )


def load_translation_source(mode: str, *, path: str | Path | None = None,
                            text: str | None = None) -> TranslationSource:
    """Never write to a chosen original, even when it is a multi-chapter TXT."""
    if mode == "paste":
        if text is None:
            raise ValueError("กรุณาวางต้นฉบับก่อน")
        return TranslationSource(_split_text(text), (), raw_text=text)
    if mode not in {"file", "folder", "step"} or not path:
        raise ValueError("กรุณาเลือกแหล่งต้นฉบับ")
    source = _check_path(path)
    if source.is_dir():
        files = scan_chapter_files(source)
        if not files:
            raise ValueError("ไม่พบไฟล์ TXT ที่มีเลขบทในโฟลเดอร์")
        chapters = tuple(TranslationChapter(c.number, c.path.name, path=_check_path(c.path))
                         for c in files)
        signatures = tuple(_signature(c.path) for c in chapters)
        metadata = tuple((path, _stat_signature(path)) for path, _ in signatures)
        return TranslationSource(chapters, signatures, folder=source, file_stats=metadata)
    if not source.is_file() or source.suffix.casefold() != ".txt":
        raise ValueError("ต้นฉบับรวมต้องเป็นไฟล์ TXT")
    signed = _signature(source)
    try:
        contents = source.read_bytes().decode("utf-8-sig")
    except UnicodeError as exc:
        raise ValueError(f"ต้นฉบับต้องเป็น UTF-8: {source.name}") from exc
    try:
        chapters = _split_text(contents)
    except ValueError as exc:
        raise ValueError(f"ไฟล์ที่ตรวจ: {source}\n{exc}") from exc
    return TranslationSource(chapters, (signed,), raw_text=None)


def translation_groups(source: TranslationSource, size: int = 5):
    """Group by actual numbers; gaps are never filled with later chapters."""
    return make_chapter_batches(
        tuple(ChapterFile(c.number, c.path or Path(c.filename)) for c in source.chapters), size
    )


def validate_translation_source(source: TranslationSource, *, text: str | None = None,
                                selected_paths=None):
    """Detect changes since preview, including added/deleted chapters in folders."""
    if source.raw_text is not None and source.raw_text != text:
        raise ValueError("Draft เปลี่ยนหลัง Preview กรุณาตรวจหัวบทใหม่")
    if source.folder is not None:
        current = tuple((_check_path(c.path), c.number) for c in scan_chapter_files(source.folder))
        original = tuple((c.path, c.number) for c in source.chapters)
        if current != original:
            raise ValueError("รายการไฟล์บทเปลี่ยน กรุณารีเฟรชก่อนคัดลอก")
    # Unselected files cannot affect this batch's contents; their metadata
    # still detects modifications, additions, removals and path replacement.
    if selected_paths is not None and source.folder is not None and source.file_stats:
        for path, expected in source.file_stats:
            if _stat_signature(_check_path(path)) != expected:
                raise ValueError(f"ต้นฉบับเปลี่ยนหลัง Preview: {path.name} กรุณารีเฟรช")
        selected = {Path(path).resolve() for path in selected_paths}
        fingerprints = ((path, digest) for path, digest in source.signatures
                        if path in selected)
    else:
        # Strict contract for ordinary callers and combined source files.
        fingerprints = iter(source.signatures)
    for path, digest in fingerprints:
        if file_digest(_check_path(path)) != digest:
            raise ValueError(f"ต้นฉบับเปลี่ยนหลัง Preview: {path.name} กรุณารีเฟรช")


def chapters_for_group(source: TranslationSource, group) -> tuple[TranslationChapter, ...]:
    by_number = {chapter.number: chapter for chapter in source.chapters}
    chapters = tuple(by_number[c.number] for c in group.chapters)
    if not chapters:
        raise ValueError("ชุดนี้ไม่มีบทให้คัดลอก")
    return chapters


def find_translation_groups(groups, query: str):
    """Accept 6-10, 6–10 or a contained chapter number such as 603."""
    query = query.strip().replace("–", "-").replace("—", "-")
    if not query:
        return tuple(groups)
    if "-" in query:
        bounds = query.split("-")
        if len(bounds) != 2 or any(not part.strip().isdecimal() for part in bounds):
            return ()
        lo, hi = (int(part) for part in bounds)
        if lo > hi:
            return ()
        return tuple(g for g in groups if g.start <= hi and g.end >= lo)
    if not query.isdecimal():
        return ()
    number = int(query)
    return tuple(g for g in groups if g.start <= number <= g.end)
