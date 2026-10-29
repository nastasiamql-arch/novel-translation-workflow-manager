"""Extract complete, structurally bounded vocabulary sections without parsing rows.

'คำศัพท์ใหม่' is an explicit label produced by the translation workflow, not
an instruction to search the novel for terms. Its contents are copied verbatim
(except section-separating blank lines) into the pending review queue. Never
change the caller's text when section boundaries are uncertain.
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
    # Kept for compatibility with existing callers.
    reviewable: bool = False

    @property
    def has_vocabulary(self):
        return self.vocabulary_count > 0


_HEADING = re.compile(r"^[ \t]*คำศัพท์ใหม่[ \t]*[:：]?[ \t]*$")
_END_MARKER = re.compile(r"^[ \t]*\[(?:จบตอน|จบบท)\][ \t]*$")


def extract_new_vocabulary(text: str, *, allow_unstructured: bool = False) -> ExtractionResult:
    """Copy the *entire* heading section to the next chapter or text end.

    The legacy allow_unstructured argument is ignored: row formatting no
    longer determines whether a verified section may be copied.
    """
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
        previous_nonblank = index - 1
        while previous_nonblank >= 0 and not lines[previous_nonblank].strip():
            previous_nonblank -= 1
        verified_end = bool(
            previous_nonblank >= 0
            and _END_MARKER.fullmatch(lines[previous_nonblank].rstrip("\r\n"))
        )

        # The title must be on its own line, after a blank line or a known
        # full-line chapter end marker; never match inline story dialogue.
        if index == 0 or (lines[index - 1].strip() and not verified_end):
            return unchanged("ambiguous", (
                f"ไม่สามารถยืนยันขอบเขตหัวข้อคำศัพท์ที่บรรทัด {index + 1}",))

        boundary = next((i for i in chapters if i > index), len(lines))
        if any(index < i < boundary for i in headings):
            return unchanged("ambiguous", ("พบหัวข้อคำศัพท์ซ้ำในบทเดียวกัน",))
        if boundary < len(lines):
            if boundary == index + 1 or (lines[boundary - 1].strip() and not verified_end):
                return unchanged("ambiguous", ("ไม่สามารถยืนยันจุดเริ่มบทถัดไป",))
            if not any(i < index for i in chapters):
                return unchanged("ambiguous", ("ไม่สามารถยืนยันบทก่อนส่วนคำศัพท์",))

        body = lines[index + 1:boundary]
        occupied = [i for i, line in enumerate(body) if line.strip()]
        if not occupied:
            return unchanged("ambiguous", (f"ไม่พบข้อความหลังคำศัพท์ใหม่ที่บรรทัด {index + 1}",))
        if len(occupied) == 1 and body[occupied[0]].strip() == "[-]":
            pass
        elif any(body[i].strip() == "[-]" for i in occupied):
            return unchanged("ambiguous", ("พบ [-] ปนกับข้อความคำศัพท์",))
        else:
            # This is a direct copy of the user's section, not an attempt to
            # split Chinese/Thai columns or guess how many terms exist.
            block = "".join(body[occupied[0]:occupied[-1] + 1]).rstrip("\r\n")
            blocks.append(block)
            count += len(occupied)  # Nonempty lines, not inferred term count.

        start = index
        if boundary == len(lines):
            while start and not lines[start - 1].strip():
                start -= 1
        spans.append((start, boundary))

    cleaned, cursor = [], 0
    for start, end in spans:
        cleaned.extend(lines[cursor:start])
        cursor = end
    cleaned.extend(lines[cursor:])
    separator = "\r\n" if "\r\n" in text else "\n"
    return ExtractionResult(
        text, "".join(cleaned), separator.join(blocks), count,
        "extracted" if count else "empty",
    )
