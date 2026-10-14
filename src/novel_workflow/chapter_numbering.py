"""Conservative manual-first scanner for original-language chapter headings.

Never read Translator/Context progress or alter story text.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

_MAX = 2_147_483_647
_NUMBER = r"[0-9０-９零〇○一二两兩三四五六七八九十百千万萬亿億]+"
_HEADING = re.compile(
    rf"(?im)^[ \t]*(?:#{{1,6}}[ \t]+)?(?:"
    rf"第[ \t]*(?P<chinese>{_NUMBER})[ \t]*章"
    rf"|chapter[ \t]+(?P<english>[0-9０-９]+)\b"
    rf"|(?:บทที่|ตอนที่)[ \t]*(?P<thai>[0-9０-９]+)"
    rf")(?=[ \t：:、.\-—]|$)"
)


@dataclass(frozen=True)
class ChapterHeading:
    line: int
    number: int
    number_start: int
    number_end: int
    title: str


def parse_number(value: str) -> int:
    value = value.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    if value.isascii() and value.isdecimal():
        number = int(value)
    else:
        digits = {letter: i for i, letter in enumerate("零一二三四五六七八九")}
        digits.update({"〇": 0, "○": 0, "两": 2, "兩": 2})
        units = {"十": 10, "百": 100, "千": 1000}
        sections = {"万": 10000, "萬": 10000, "亿": 100000000, "億": 100000000}
        if not value or any(c not in digits and c not in units and c not in sections for c in value):
            raise ValueError("Unsupported Chinese numeral")
        total = section = current = 0
        for char in value:
            if char in digits:
                current = digits[char]
            elif char in units:
                section += (current or 1) * units[char]
                current = 0
            else:
                section += current
                total += section * sections[char]
                section = current = 0
        number = total + section + current
    if not 0 < number <= _MAX:
        raise ValueError("Invalid chapter number")
    return number


def scan_chapters(text: str) -> list[ChapterHeading]:
    """Recognize anchored headings, never numerals inside narrative paragraphs."""
    result = []
    fenced = False
    offset = 0
    for line_no, line in enumerate(text.splitlines(keepends=True), 1):
        if line.lstrip().startswith(("\x60\x60\x60", "~~~")):
            fenced = not fenced
        if not fenced:
            match = _HEADING.match(line)
            if match:
                for group in ("chinese", "english", "thai"):
                    if match.group(group) is not None:
                        try:
                            number = parse_number(match.group(group))
                        except ValueError:
                            break
                        result.append(ChapterHeading(
                            line_no, number, offset + match.start(group),
                            offset + match.end(group), line[match.end():].strip()
                        ))
                        break
        offset += len(line)
    return result


def chapter_issues(headings: list[ChapterHeading]) -> list[str]:
    issues, seen = [], set()
    previous = None
    for heading in headings:
        number = heading.number
        if number in seen:
            status = "เลขซ้ำ"
        elif previous is not None and number < previous:
            status = "เลขย้อนกลับ"
        elif previous is not None and number > previous + 1:
            status = "เลขกระโดด / อาจมีบทขาดจริง"
        else:
            status = "ปกติ"
        issues.append(status)
        seen.add(number)
        previous = number
    return issues


def preview_renumber(text: str, changes: dict[int, int]) -> tuple[str, list[tuple[int, int, int]]]:
    """Return exact proposed text. Keys are zero-based heading indices."""
    headings = scan_chapters(text)
    if any(type(k) is not int or k < 0 or k >= len(headings) for k in changes):
        raise ValueError("Chapter selection has changed; scan again")
    expected = [changes.get(i, heading.number) for i, heading in enumerate(headings)]
    if any(type(n) is not int or not 0 < n <= _MAX for n in expected):
        raise ValueError("Invalid chapter number")
    if len(set(expected)) != len(expected):
        raise ValueError("Chapter numbers would collide; nothing changed")
    applied = []
    result = text
    for i in sorted(changes, reverse=True, key=lambda k: headings[k].number_start):
        heading = headings[i]
        new = changes[i]
        if new == heading.number:
            continue
        result = result[:heading.number_start] + str(new) + result[heading.number_end:]
        applied.append((heading.line, heading.number, new))
    return result, sorted(applied)
