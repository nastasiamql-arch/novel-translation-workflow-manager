"""Conservative detection of a terminal vocabulary section in Translator text.

This parser never modifies its input. Ambiguous sections are returned intact so
that the caller can stop the export and ask the user to inspect the text.
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

    @property
    def has_vocabulary(self):
        return self.vocabulary_count > 0


_HEADING = re.compile(r"^[ \t]*คำศัพท์ใหม่[ \t]*[:：]?[ \t]*$")
_END_MARKER = re.compile(r"^[ \t]*\[(?:จบตอน|จบบท)\][ \t]*$")
_ROW = re.compile(r"^[^\S\r\n]*[\u3400-\u9fff\uf900-\ufaff]+(?:\t+|[^\S\r\n]{2,})\S")
# A single space has no unambiguous column separator in free-form Thai.
# Require a Chinese term, Thai name, explicit gender field and description.
_SINGLE_SPACE_ROW = re.compile(
    r"^[ \t]*[\u3400-\u9fff\uf900-\ufaff]+ [\u0e01-\u0e5b]+ "
    r"(?:ชาย|หญิง|ไม่ระบุ) [\u0e01-\u0e5b].*$"
)


def extract_new_vocabulary(text: str) -> ExtractionResult:
    """Extract sections bounded by a subsequent chapter or the end of input."""
    from .recovery import _TRANSLATOR_CHAPTER_LINE
    lines = text.splitlines(keepends=True)
    headings = [i for i, line in enumerate(lines)
                if _HEADING.fullmatch(line.rstrip("\r\n"))]
    def unchanged(status, warning=()):
        return ExtractionResult(text, text, "", 0, status, warning)
    if not headings:
        return unchanged("none")
    chapters = [i for i, line in enumerate(lines)
                if _TRANSLATOR_CHAPTER_LINE.match(line.lstrip("\ufeff"))]
    spans, blocks, count = [], [], 0
    for index in headings:
        # A known, full-line end marker is a verified boundary even without
        # a blank line; arbitrary nonblank prose remains unsafe.
        if index == 0 or (lines[index - 1].strip() and not
                          _END_MARKER.fullmatch(lines[index - 1].rstrip("\r\n"))):
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
        elif nonempty and all(_ROW.match(line) or _SINGLE_SPACE_ROW.fullmatch(line)
                              for line in nonempty):
            first = next(i for i, line in enumerate(body) if line.strip())
            last = len(body) - next(i for i, line in enumerate(reversed(body)) if line.strip())
            blocks.append("".join(lines[index + 1 + first:index + 1 + last]).rstrip("\r\n"))
            count += len(nonempty)
        else:
            return unchanged("ambiguous", ("รูปแบบหรือขอบเขตคำศัพท์ไม่ชัดเจน",))
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
