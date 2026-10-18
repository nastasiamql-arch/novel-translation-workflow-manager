"""Read-only chapter detection and safe TXT splitting for vocabulary preparation.

No workflow/export state is touched. Source documents are never rewritten by scanning
or copying. Pasted texts are only saved after explicit user confirmation.
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4


_FILENAME_NUMBER = re.compile(r"^0*([1-9]\d*)(?:[\s._-]+.*)?$")
_ZH = re.compile(r"^\s*(?:#{1,6}\s*)?第\s*([0-9０-９〇零一二两兩三四五六七八九十百千万萬亿億]+)\s*[章节節回]\s*(.*)$")
_TH = re.compile(r"^\s*(?:#{1,6}\s*)?(?:บทที่|ตอนที่|บท|ตอน)\s*([0-9０-９]+)(?:\s*[:：.\-–]\s*|\s+)?(.*)$", re.I)
_EN = re.compile(r"^\s*(?:#{1,6}\s*)?chapter\s+([0-9０-９]+)(?:\s*[:：.\-–]\s*|\s+)?(.*)$", re.I)
_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "兩": 2, "三": 3, "四": 4,
           "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000, "萬": 10000,
          "亿": 100000000, "億": 100000000}


@dataclass(frozen=True)
class ChapterFile:
    number: int
    path: Path


@dataclass(frozen=True)
class ChapterBatch:
    index: int
    start: int
    end: int
    chapters: tuple[ChapterFile, ...]
    missing: tuple[int, ...]


@dataclass(frozen=True)
class PastedChapter:
    number: int
    heading: str
    text: str
    first_line: int
    filename: str


@dataclass(frozen=True)
class SplitResult:
    written: int
    skipped: int
    backup_directory: Path | None


def scan_chapter_files(folder: str | Path) -> tuple[ChapterFile, ...]:
    """Find numbered TXT files in one directory and sort numerically."""
    directory = Path(folder).expanduser()
    if not directory.is_dir():
        raise ValueError(f"ไม่พบโฟลเดอร์ต้นฉบับ: {directory}")
    found: dict[int, Path] = {}
    for path in directory.iterdir():
        if not path.is_file() or path.suffix.casefold() != ".txt":
            continue
        match = _FILENAME_NUMBER.fullmatch(path.stem)
        if not match:
            continue
        number = int(match.group(1))
        if number in found:
            raise ValueError(f"มีไฟล์เลขบท {number:04d} ซ้ำ: {found[number].name}, {path.name}")
        found[number] = path
    return tuple(ChapterFile(n, found[n]) for n in sorted(found))


def make_chapter_batches(chapters: tuple[ChapterFile, ...], size: int = 5,
                         start: int | None = None, end: int | None = None) -> tuple[ChapterBatch, ...]:
    """Group by actual chapter *numbers*, never shift later chapters into gaps."""
    if not 1 <= size <= 100:
        raise ValueError("จำนวนบทต่อชุดต้องอยู่ระหว่าง 1–100")
    if not chapters:
        return ()
    first = chapters[0].number if start is None else start
    last = chapters[-1].number if end is None else end
    if first < 1 or last < first or last - first > 100000:
        raise ValueError("ช่วงบทไม่ถูกต้องหรือยาวเกินไป")
    by_number = {chapter.number: chapter for chapter in chapters}
    output = []
    for index, low in enumerate(range(first, last + 1, size), 1):
        high = min(last, low + size - 1)
        output.append(ChapterBatch(
            index, low, high,
            tuple(by_number[n] for n in range(low, high + 1) if n in by_number),
            tuple(n for n in range(low, high + 1) if n not in by_number),
        ))
    return tuple(output)


def read_utf8_text(path: str | Path) -> str:
    chosen = Path(path).expanduser()
    if not chosen.is_file():
        raise ValueError(f"ไม่พบไฟล์: {chosen}")
    try:
        return chosen.read_text(encoding="utf-8-sig")
    except UnicodeError as exc:
        raise ValueError(f"ไฟล์ไม่ใช่ UTF-8: {chosen.name}") from exc


def batch_clipboard_text(batch: ChapterBatch) -> str:
    if not batch.chapters:
        raise ValueError("ชุดนี้ไม่มีไฟล์บทให้คัดลอก")
    parts = []
    for chapter in batch.chapters:
        text = read_utf8_text(chapter.path)
        parts.append(f"===== บท {chapter.number:04d} | {chapter.path.name} =====\n{text}")
    return "\n\n".join(parts)


def _chapter_number(raw: str) -> int:
    if raw.isdecimal():
        return int(raw)
    if any(character not in _DIGITS and character not in _UNITS for character in raw):
        raise ValueError("รูปแบบเลขบทภาษาจีนไม่รองรับ")
    if not any(character in _UNITS for character in raw):
        return int("".join(str(_DIGITS[c]) for c in raw))
    total = subtotal = digit = 0
    for c in raw:
        if c in _DIGITS:
            digit = _DIGITS[c]
        elif _UNITS[c] < 10000:
            subtotal += (digit or 1) * _UNITS[c]
            digit = 0
        else:
            total += (subtotal + digit or 1) * _UNITS[c]
            subtotal = digit = 0
    return total + subtotal + digit


def _heading_match(line: str) -> tuple[int, str] | None:
    for pattern in (_ZH, _TH, _EN):
        match = pattern.fullmatch(line)
        if match:
            number = _chapter_number(match.group(1))
            if number < 1 or number > 999999:
                raise ValueError(f"เลขบทไม่ถูกต้อง: {line[:100]}")
            return number, match.group(2).strip()
    return None


def _target_filename(number: int, title: str) -> str:
    safe = unicodedata.normalize("NFKC", title)
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", safe)
    safe = re.sub(r"\s+", " ", safe).strip(" .")[:70].rstrip(" .")
    return f"{number:04d}" + (f" {safe}" if safe else "") + ".txt"


def parse_pasted_chapters(text: str) -> tuple[PastedChapter, ...]:
    """Split only at supported full-line chapter headings; retain original text."""
    if not text.strip():
        raise ValueError("กรุณาวางเนื้อหาที่มีหัวบทก่อน")
    matches = []
    offset = 0
    line_no = 0
    for rawline in text.splitlines(keepends=True):
        line_no += 1
        heading = _heading_match(rawline.rstrip("\r\n"))
        if heading:
            number, title = heading
            matches.append((number, title, offset, line_no, rawline.rstrip("\r\n")))
        offset += len(rawline)
    if not matches:
        raise ValueError("ไม่พบหัวบท เช่น 第一章, 第100章, บทที่ 1, ตอนที่ 2 หรือ Chapter 3")
    if len(matches) > 5000:
        raise ValueError("พบเกิน 5,000 บท กรุณาแบ่งข้อความก่อน")
    if text[:matches[0][2]].strip():
        raise ValueError("พบเนื้อหาก่อนหัวบทแรก กรุณาตรวจและแยกข้อความส่วนนั้นก่อนบันทึก")
    seen = set()
    chapters = []
    for index, (number, title, begin, lineno, header) in enumerate(matches):
        if number in seen:
            raise ValueError(f"พบหัวบทเลข {number:04d} ซ้ำ กรุณาตรวจข้อความต้นฉบับ")
        seen.add(number)
        # Include leading whitespace in first chapter; no pasted content is lost.
        first = 0 if index == 0 else begin
        end = matches[index + 1][2] if index + 1 < len(matches) else len(text)
        chapters.append(PastedChapter(number, header, text[first:end], lineno,
                                      _target_filename(number, title)))
    return tuple(chapters)


def split_missing_numbers(chapters: tuple[PastedChapter, ...]) -> tuple[int, ...]:
    if not chapters:
        return ()
    numbers = {chapter.number for chapter in chapters}
    return tuple(n for n in range(min(numbers), max(numbers) + 1) if n not in numbers)


def _destination_targets(folder: Path, chapters: tuple[PastedChapter, ...]) -> tuple[tuple[Path, PastedChapter], ...]:
    # An existing numbered chapter wins over a new pasted title, even if the
    # filename is different: never create two files for the same chapter number.
    existing = {entry.number: entry.path for entry in scan_chapter_files(folder)}
    return tuple((existing.get(chapter.number, folder / chapter.filename), chapter) for chapter in chapters)


def existing_chapter_targets(folder: str | Path, chapters: tuple[PastedChapter, ...]) -> tuple[Path, ...]:
    root = Path(folder).expanduser()
    return tuple(path for path, _ in _destination_targets(root, chapters) if path.exists())


def write_split_chapters(folder: str | Path, chapters: tuple[PastedChapter, ...],
                         *, on_existing: str = "skip") -> SplitResult:
    """Stage UTF-8 files before installation; overwrite only with explicit backup."""
    if on_existing not in ("skip", "replace"):
        raise ValueError("ตัวเลือกจัดการไฟล์ซ้ำไม่ถูกต้อง")
    root = Path(folder).expanduser()
    if not root.is_dir():
        raise ValueError(f"ไม่พบโฟลเดอร์ปลายทาง: {root}")
    if not chapters:
        raise ValueError("ยังไม่ได้ตรวจตัวอย่างบท")
    targets = list(_destination_targets(root, chapters))
    if len({str(path).casefold() for path, _ in targets}) != len(targets):
        raise ValueError("ชื่อไฟล์หลังแปลงซ้ำกัน กรุณาตรวจหัวบท")
    for destination, _ in targets:
        if destination.exists() and not destination.is_file():
            raise ValueError(f"ปลายทางไม่ใช่ไฟล์: {destination.name}")
    selected = [(dest, segment) for dest, segment in targets if on_existing == "replace" or not dest.exists()]
    staged: list[tuple[Path, Path]] = []
    backups: dict[Path, Path] = {}
    installed: list[Path] = []
    backup_dir = None
    try:
        for destination, segment in selected:
            fd, tempname = tempfile.mkstemp(prefix=".novel-txt-", suffix=".part", dir=root)
            temp = Path(tempname)
            staged.append((destination, temp))
            with os.fdopen(fd, "wb") as file:
                file.write(segment.text.encode("utf-8"))
                file.flush()
                os.fsync(file.fileno())
        conflicts = [dest for dest, _ in selected if dest.exists()]
        if conflicts:
            backup_dir = root / ".txt_vocabulary_backups" / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:8])
            backup_dir.mkdir(parents=True, exist_ok=False)
            for destination in conflicts:
                backup = backup_dir / destination.name
                shutil.copy2(destination, backup)
                backups[destination] = backup
        for destination, temp in staged:
            # Recheck unexpected concurrent writes; never overwrite in skip mode.
            if on_existing == "skip" and destination.exists():
                raise FileExistsError(f"มีไฟล์ใหม่เกิดขึ้นระหว่างบันทึก: {destination.name}")
            os.replace(temp, destination)
            installed.append(destination)
        return SplitResult(len(installed), len(targets) - len(selected), backup_dir)
    except Exception:
        for destination in reversed(installed):
            if destination in backups:
                shutil.copy2(backups[destination], destination)
            else:
                destination.unlink(missing_ok=True)
        raise
    finally:
        for _, temporary in staged:
            temporary.unlink(missing_ok=True)
