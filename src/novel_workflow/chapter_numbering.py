"""Conservative manual-first scanner for original-language chapter headings.

Never read Translator/Context progress or alter story text.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata

_MAX = 2_147_483_647
_NUMBER = r"[0-9０-９零〇○一二两兩三四五六七八九十百千万萬亿億]+"
_HEADING = re.compile(
    rf"(?im)^[ \t\u3000]*(?:#{{1,6}}[ \t\u3000]+)?(?:"
    # Chinese source titles often start immediately after 章 (第25章月薪40万).
    # Reject common grammatical continuations so prose such as 第25章的故事... is
    # not promoted to a heading merely because it starts at the beginning of a line.
    rf"第[ \t\u3000]*(?P<chinese>{_NUMBER})[ \t\u3000]*章(?=$|[ \t\u3000：:、.\-—]|(?!(?:的|之|有|是|在|将|把|與|与|和|中|后|後|前|时|時|内容|內容))[^\s])"
    rf"|chapter[ \t]+(?P<english>[0-9０-９]+)\b"
    rf"|(?:บทที่|ตอนที่)[ \t]*(?P<thai>[0-9０-９]+)"
    rf")"
)

# A volume label is a boundary, not a chapter; do not change its text.
_VOLUME_HEADING = re.compile(
    rf"(?im)^[ \t\u3000]*(?:#{{1,6}}[ \t\u3000]+)?"
    rf"(?:第[ \t\u3000]*(?P<ordinal>{_NUMBER})[ \t\u3000]*(?:卷|册|冊|部)"
    rf"|卷[ \t\u3000]*(?P<suffix>{_NUMBER}))"
)


@dataclass(frozen=True)
class ChapterHeading:
    line: int
    number: int
    number_start: int
    number_end: int
    title: str
    volume: int | None = None
    volume_index: int = 0


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
    active_volume = None
    volume_index = 0
    for line_no, line in enumerate(text.splitlines(keepends=True), 1):
        if line.lstrip().startswith(("\x60\x60\x60", "~~~")):
            fenced = not fenced
        if not fenced:
            volume_match = _VOLUME_HEADING.match(line)
            if volume_match:
                raw_volume = volume_match.group("ordinal") or volume_match.group("suffix")
                try:
                    active_volume = parse_number(raw_volume)
                except ValueError:
                    pass
                else:
                    volume_index += 1
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
                            offset + match.end(group), line[match.end():].strip(),
                            active_volume, volume_index,
                        ))
                        break
        offset += len(line)
    return result


def chapter_groups(headings: list[ChapterHeading],
                   volume_starts: set[int] | None = None) -> list[int]:
    """Sequence groups from explicit volume headings or confirmed manual breaks.

    An unlabelled number rollback alone is not evidence of a new volume.
    """
    starts = volume_starts or set()
    groups = []
    group = 0
    for i, heading in enumerate(headings):
        if i and (heading.volume_index != headings[i - 1].volume_index or i in starts):
            group += 1
        groups.append(group)
    return groups


def _normalized_title(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    return "".join(char for char in value if not char.isspace())


def chapter_issues(headings: list[ChapterHeading], text: str | None = None,
                   volume_starts: set[int] | None = None) -> list[str]:
    """Describe numbering problems and safely distinguish likely duplicate rows.

    When source text is supplied, identical consecutive headings with no nonblank
    content between them are called likely copies. Repeated numbers with differing
    titles or intervening story text remain warnings and are never removed here.
    """
    issues, seen = [], set()
    previous = None
    lines = text.splitlines() if text is not None else None
    previous_heading = None
    groups = chapter_groups(headings, volume_starts)
    for i, heading in enumerate(headings):
        if i and groups[i] != groups[i - 1]:
            seen, previous, previous_heading = set(), None, None
        number = heading.number
        if number in seen:
            status = "เลขซ้ำ"
            if lines is not None and previous_heading is not None and previous_heading.number == number:
                same_title = _normalized_title(previous_heading.title) == _normalized_title(heading.title)
                no_story_between = not any(
                    line.strip() for line in lines[previous_heading.line:heading.line - 1]
                )
                if same_title and no_story_between:
                    status = "หัวบทซ้ำที่น่าจะเป็นรายการเดียวกัน"
                elif same_title:
                    status = "เลข/ชื่อบทซ้ำ แต่มีเนื้อหาคั่น · ตรวจเนื้อเรื่อง"
                else:
                    status = "เลขบทซ้ำ แต่ชื่อบทต่างกัน"
        elif previous is not None and number < previous:
            status = "เลขย้อนกลับ"
        elif previous is not None and number > previous + 1:
            status = "เลขกระโดด / อาจมีบทขาดจริง"
        else:
            status = "ปกติ"
        issues.append(status)
        seen.add(number)
        previous = number
        previous_heading = heading
    return issues


def duplicate_heading_removal_plan(text: str, volume_starts: set[int] | None = None) -> tuple[str, list[int]]:
    """Plan removal of only adjacent, identical duplicate heading lines.

    Whitespace-only separators are retained. A repeated heading with intervening
    story text or a different title is never included in this plan.
    """
    headings = scan_chapters(text)
    issues = chapter_issues(headings, text, volume_starts)
    remove_lines = [
        heading.line for heading, issue in zip(headings, issues)
        if issue == "หัวบทซ้ำที่น่าจะเป็นรายการเดียวกัน"
    ]
    if not remove_lines:
        return text, []
    removed = set(remove_lines)
    result = "".join(
        line for line_no, line in enumerate(text.splitlines(keepends=True), 1)
        if line_no not in removed
    )
    return result, remove_lines



_CHINESE_DIGITS = "零一二三四五六七八九"
_CHINESE_UNITS = ((1000, "千"), (100, "百"), (10, "十"), (1, ""))
_SUSPECT_HEADING = re.compile(
    r"(?im)^[ \t\u3000]*(?:#{1,6}[ \t\u3000]+)?(?:第[^\r\n]{1,24}?章(?!的|之|有|是|在|将|把|與|与|和|中|后|後|前|时|時|内容|內容)|chapter[ \t]+\S+|(?:บทที่|ตอนที่)[ \t]*\S+)"
)


def format_heading_number(number: int, template: str) -> str:
    """Keep the chapter heading's Arabic, full-width or Chinese numeral style."""
    if type(number) is not int or not 0 < number <= _MAX:
        raise ValueError("Invalid chapter number")
    if template.isascii() and template.isdecimal():
        return str(number)
    fullwidth = "０１２３４５６７８９"
    if template and all(c in fullwidth for c in template):
        return str(number).translate(str.maketrans("0123456789", fullwidth))
    if template and all(c in "0123456789" + fullwidth for c in template):
        return str(number)
    if not template or any(c not in "零〇○一二两兩三四五六七八九十百千万萬亿億" for c in template):
        raise ValueError("Unsupported Chinese chapter numeral")
    parse_number(template)
    zero = next((c for c in template if c in "零〇○"), "零")
    two = "兩" if "兩" in template else ("两" if "两" in template else "二")
    wan = "萬" if "萬" in template else "万"
    yi = "億" if "億" in template else "亿"

    def group_text(value: int) -> str:
        parts = []
        need_zero = False
        for unit, suffix in _CHINESE_UNITS:
            digit, value = divmod(value, unit)
            if digit:
                if parts and need_zero:
                    parts.append(zero)
                if not (unit == 10 and digit == 1 and not parts):
                    parts.append(two if digit == 2 and unit in (100, 1000) else _CHINESE_DIGITS[digit])
                parts.append(suffix)
                need_zero = False
            elif parts and value:
                need_zero = True
        return "".join(parts)

    groups = [number % 10000, (number // 10000) % 10000, number // 100000000]
    result = ""
    gap = False
    for i in (2, 1, 0):
        section = groups[i]
        if not section:
            if result:
                gap = True
            continue
        if result and (gap or section < 1000):
            result += zero
        result += group_text(section) + (yi if i == 2 else wan if i == 1 else "")
        gap = False
    return result


def automatic_renumber_plan(text: str, start: int) -> tuple[str, list[tuple[int, int, int]]]:
    """Plan only a contiguous source batch; never infer missing chapters."""
    if type(start) is not int or not 0 < start <= _MAX:
        raise ValueError("ไม่มีเลขบทอ้างอิงจาก Translator")
    headings = scan_chapters(text)
    if not headings:
        raise ValueError("ไม่พบหัวบทที่รองรับ จึงไม่เปลี่ยนต้นฉบับ")
    known_lines = {h.line for h in headings}
    fenced = False
    for i, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith((chr(96) * 3, "~~~")):
            fenced = not fenced
            continue
        if not fenced and _SUSPECT_HEADING.match(line) and i not in known_lines:
            raise ValueError("พบหัวบทที่อ่านเลขไม่ได้ กรุณาตรวจเองก่อนแก้")
    if len(set(chapter_groups(headings))) > 1:
        raise ValueError("ต้นฉบับมีหลายเล่ม ไม่เสนอเรียงเลขอัตโนมัติข้ามเล่ม")
    nums = [h.number for h in headings]
    if any(n != nums[0] + i for i, n in enumerate(nums)):
        raise ValueError("ต้นฉบับมีเลขซ้ำหรือไม่ต่อเนื่อง อาจมีบทขาดจริง")
    if nums[0] < start:
        raise ValueError("บทต้นฉบับย้อนกลับไปก่อนบทถัดไปของ Translator")
    if start + len(headings) - 1 > _MAX:
        raise ValueError("หมายเลขบทใหม่เกินขีดจำกัด")
    return preview_renumber(text, {i: start + i for i in range(len(headings))})


def preview_renumber(text: str, changes: dict[int, int],
                     volume_starts: set[int] | None = None) -> tuple[str, list[tuple[int, int, int]]]:
    """Return exact proposed text. Keys are zero-based heading indices."""
    headings = scan_chapters(text)
    if any(type(k) is not int or k < 0 or k >= len(headings) for k in changes):
        raise ValueError("Chapter selection has changed; scan again")
    expected = [changes.get(i, heading.number) for i, heading in enumerate(headings)]
    if any(type(n) is not int or not 0 < n <= _MAX for n in expected):
        raise ValueError("Invalid chapter number")
    groups = chapter_groups(headings, volume_starts)
    if len(set(zip(groups, expected))) != len(expected):
        raise ValueError("Chapter numbers would collide within a volume; nothing changed")
    applied = []
    result = text
    for i in sorted(changes, reverse=True, key=lambda k: headings[k].number_start):
        heading = headings[i]
        new = changes[i]
        if new == heading.number:
            continue
        old_number = text[heading.number_start:heading.number_end]
        result = result[:heading.number_start] + format_heading_number(new, old_number) + result[heading.number_end:]
        applied.append((heading.line, heading.number, new))
    return result, sorted(applied)
