"""Conservatively remove verified vocabulary sections without changing novel text.

Recognize common vocabulary formats, not arbitrary story sentences. When a
verified end marker contains an unknown layout, the caller may offer explicit
review instead of requiring a new parser rule for every AI response.
"""
from dataclasses import dataclass
import re


@dataclass(frozen=True)
class ExtractionResult:
    original_text: str
    cleaned_text: str
    vocabulary_text: str
    vocabulary_count: int
    status: str
    warnings: tuple[str, ...] = ()
    reviewable: bool = False

    @property
    def has_vocabulary(self):
        return self.vocabulary_count > 0


_HEADING = re.compile(r"^[ \t]*คำศัพท์ใหม่[ \t]*[:：]?[ \t]*$")
_END_MARKER = re.compile(r"^[ \t]*\[(?:จบตอน|จบบท)\][ \t]*$")
_HAN = r"[\u3400-\u9fff\uf900-\ufaff\U00020000-\U0002fa1f]"
_THAI = re.compile(r"[\u0e01-\u0e5b]")
# Preserve the legacy, provably column-separated formats.
_ROW = re.compile(rf"^[ \t]*{_HAN}+(?:\t+|[ ]{{2,}})\S")
_NUMBERED_WORD = re.compile(
    rf"^[ \t]*(?:(?:[-*•][ \t]+)|(?:\d+[.)、][ \t]+))?"
    rf"(?:\*\*|`)?(?P<word>{_HAN}+)(?:\*\*|`)?(?P<tail>.*)$"
)
_TABLE_RULE = re.compile(r"^\|?[ \t]*:?-{3,}:?[ \t]*(?:\|[ \t]*:?-{3,}:?[ \t]*)+\|?$")
_TABLE_HEADER_FIRST = {"จีน", "ภาษาจีน", "คำจีน", "中文", "คำศัพท์", "ต้นฉบับ", "chinese", "term", "word"}


def _table_row_kind(line: str) -> str | None:
    """Classify Markdown table lines without counting labels as vocabulary."""
    raw = line.strip()
    if not (raw.startswith("|") and raw.endswith("|")):
        return None
    if _TABLE_RULE.fullmatch(raw):
        return "rule"
    cells = [cell.strip().strip("`*") for cell in raw.strip("|").split("|")]
    if len(cells) < 2:
        return None
    if cells[0].casefold() in _TABLE_HEADER_FIRST:
        return "header"
    if cells[0].isdigit() and len(cells) >= 3:
        cells = cells[1:]
    if re.fullmatch(rf"{_HAN}+", cells[0]) and _THAI.search(cells[1]):
        return "row"
    return None


def _is_vocabulary_row(line: str) -> bool:
    """Recognize rows with explicit separators; leave plain Chinese/Thai prose untrusted."""
    if _ROW.match(line) or _table_row_kind(line) == "row":
        return True
    match = _NUMBERED_WORD.fullmatch(line)
    if match is None:
        return False
    tail = match.group("tail")
    # 中: ไทย, 中 - ไทย, 中 → ไทย, 中 ไทย - คำอธิบาย
    if re.match(r"^[ \t]*(?:[:：=→⇒|/]|[-–—])[ \t]*", tail):
        return bool(_THAI.search(tail))
    if re.match(r"^[ \t]+[^\r\n]+[ \t]+[-–—:：|][ \t]+\S", tail):
        return bool(_THAI.search(tail))
    if re.match(r"^[ \t]+[\u0e01-\u0e5b]+[ \t]+(?:ชาย|หญิง|ไม่ระบุ)(?:[ \t]+\S+)?$", tail):
        return True
    return False


def extract_new_vocabulary(text: str, *, allow_unstructured: bool = False) -> ExtractionResult:
    """Extract bounded sections; unknown layouts require explicit user review."""
    from .recovery import _TRANSLATOR_CHAPTER_LINE
    lines = text.splitlines(keepends=True)
    headings = [i for i, line in enumerate(lines)
                if _HEADING.fullmatch(line.rstrip("\r\n"))]
    def unchanged(status, warning=(), reviewable=False):
        return ExtractionResult(text, text, "", 0, status, warning, reviewable)
    if not headings:
        return unchanged("none")
    chapters = [i for i, line in enumerate(lines)
                if _TRANSLATOR_CHAPTER_LINE.match(line.lstrip("\ufeff"))]
    spans, blocks, count = [], [], 0
    for index in headings:
        # Blank lines before the heading are optional; the nearest nonblank
        # line may be a known, full-line chapter-ending marker.
        previous = lines[index - 1].rstrip("\r\n") if index else ""
        previous_nonblank = index - 1
        while previous_nonblank >= 0 and not lines[previous_nonblank].strip():
            previous_nonblank -= 1
        verified_end = bool(previous_nonblank >= 0 and
                            _END_MARKER.fullmatch(lines[previous_nonblank].rstrip("\r\n")))
        if index == 0 or (previous.strip() and not verified_end):
            return unchanged("ambiguous", (
                f"ไม่สามารถยืนยันขอบเขตหัวข้อคำศัพท์ที่บรรทัด {index + 1}",))
        boundary = next ( (i for i in chapters if i > index), len(lines))
        if any(index < i < boundary for i in headings):
            return unchanged("ambiguous", ("พบหัวข้อคำศัพท์ซ้ำในบทเดียวกัน",))
        if boundary < len(lines) and (boundary == index + 1 or lines[boundary - 1].strip()):
            return unchanged("ambiguous", ("ไม่สามารถยืนยันจุดเริ่มบทถัดไป",))
        if boundary < len(lines) and not any(i < index for i in chapters):
            return unchanged("ambiguous", ("ไม่สามารถยืนยันบทก่อนส่วนคำศัพท์",))
        body = [line.rstrip("\r\n") for line in lines[index + 1:boundary]]
        nonempty = [line for line in body if line.strip()]
        if len(nonempty) == 1 and nonempty[0].strip() == "[-]":
            pass
        elif not nonempty or any(line.strip() == "[-]" for line in nonempty):
            return unchanged("ambiguous", ("ส่วนคำศัพท์ว่างหรือมี [-] ปนกับข้อความ",))
        else:
            rows = [line for line in nonempty if _is_vocabulary_row(line)]
            table_labels = [line for line in nonempty
                            if _table_row_kind(line) in {"header", "rule"}]
            parsed = bool(rows) and len(rows) + len(table_labels) == len(nonempty)
            if not parsed and not (verified_end and allow_unstructured):
                return unchanged("ambiguous", (
                    f"ตรวจรูปแบบรายการคำศัพท์หลังบรรทัด {index + 1} ไม่ครบ"
                    " · สามารถยืนยันส่วนคำศัพท์ที่ตรวจรูปแบบไม่ได้",), verified_end)
            first = next(i for i, line in enumerate(body) if line.strip())
            last = len(body) - next(i for i, line in enumerate(reversed(body)) if line.strip())
            blocks.append("".join(lines[index + 1 + first:index + 1 + last]).rstrip("\r\n"))
            count += len(rows) if parsed else len(nonempty)
        start = index
        if boundary == len(lines):
            while start and not lines[start - 1].strip(): start -= 1
        spans.append((start, boundary))
    output, cursor = [], 0
    for start, end in spans:
        output.extend(lines[cursor:start])
        cursor = end
    output.extend(lines[cursor:])
    separator = '\r\n' if '\r\n' in text else '\n'
    return ExtractionResult(text, ''.join(output), separator.join(blocks), count,
                            'extracted' if count else 'empty')
