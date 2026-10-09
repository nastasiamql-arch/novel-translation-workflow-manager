"""Editor contract: remove only zero-character novel lines; never trim data."""
from pathlib import Path
import re

LINE_SEPARATOR = re.compile(r'\r\n|[\n\r\u2028\u2029\u0085]')
NOVEL_FOLDERS = {'source', 'translated', 'reviewed', 'polished', 'polishing'}
STRUCTURED_FOLDERS = {'prompts', 'prompt', 'style', 'glossary', 'characters', 'vocabulary', 'config', 'configuration'}
NOVEL_HEADINGS = {'novel', 'novel text', 'source', 'translation', 'reviewed', 'polished', 'เนื้อหานิยาย', 'ต้นฉบับ', 'คำแปล', 'เกลาสำนวน'}


def normalize_novel_text(text: str) -> str:
    """Delete exactly empty lines, preserving retained characters and separators."""
    pieces = re.split(r'(\r\n|[\n\r\u2028\u2029\u0085])', text)
    retained = [(pieces[i], pieces[i + 1] if i + 1 < len(pieces) else '')
                for i in range(0, len(pieces), 2) if pieces[i] != '']
    return ''.join(line + (sep if i < len(retained) - 1 else '')
                   for i, (line, sep) in enumerate(retained))


remove_empty_lines = normalize_novel_text


def is_vocabulary(path: Path, text: str = '') -> bool:
    names = {part.casefold() for part in path.parts}
    if path.suffix.lower() == '.tsv' or names & {'glossary', 'characters', 'vocabulary'}:
        return True
    if re.search(r'(glossary|characters?|vocab(?:ulary)?|คำศัพท์|ตัวละคร)', path.stem, re.I):
        return True
    rows = [line for line in LINE_SEPARATOR.split(text) if line != '']
    return bool(rows) and all(line.count('\t') >= 3 for line in rows)


def cleans_file_text(path: Path) -> bool:
    path = Path(path)
    names = {part.casefold() for part in path.parts}
    if path.suffix.lower() not in {'.txt', '.md', '.markdown'}:
        return False
    if names & STRUCTURED_FOLDERS or is_vocabulary(path):
        return False
    if re.search(r'^(prompt|style|config|settings)(?:[_. -]|$)', path.stem, re.I):
        return False
    return (bool(names & NOVEL_FOLDERS) or path.stem.casefold() == 'context'
            or bool(re.search(r'^(chapter|segverified|verified|novel|บทที่|第)', path.stem, re.I)))


def normalize_context_text(text: str) -> str:
    """Preserve structured Context; compact only explicitly named novel sections."""
    headings = list(re.finditer(r'(?m)^(#{1,6})[ \t]+([^\r\n]+)', text))
    if not headings:
        if is_vocabulary(Path('Context.md'), text) or text.lstrip().startswith(('{', '[', '```')):
            return text
        return normalize_novel_text(text)
    return ''.join(line for line, novel in context_line_modes(text)
                   if not (novel and LINE_SEPARATOR.sub('', line) == ''))


def context_line_modes(text: str):
    pieces = re.split(r'(\r\n|[\n\r\u2028\u2029\u0085])', text)
    depth = 0
    fenced = False
    for i in range(0, len(pieces), 2):
        body = pieces[i]
        sep = pieces[i + 1] if i + 1 < len(pieces) else ''
        heading = re.match(r'^(#{1,6})[ \t]+(.+)', body)
        if not fenced and heading:
            level = len(heading.group(1))
            if depth and level <= depth:
                depth = 0
            if heading.group(2).casefold().strip(' #') in NOVEL_HEADINGS:
                depth = level
        fence = body.lstrip().startswith(('```', '~~~'))
        novel = bool(depth) and not fenced and not fence
        yield body + sep, novel
        if fence:
            fenced = not fenced


def context_is_novel_at(text: str, offset: int) -> bool:
    if not re.search(r'(?m)^#{1,6}[ \t]', text):
        return not text.lstrip().startswith(('{', '[', '```')) and not is_vocabulary(Path('Context.md'), text)
    consumed = 0
    mode = False
    for line, mode in context_line_modes(text):
        consumed += len(line.encode('utf-16-le')) // 2
        if offset < consumed:
            return mode
    return mode


def deleted_ranges(old: str, new: str):
    """Linear diff for normalization, which only deletes existing characters."""
    i = j = 0
    while i < len(old):
        if j < len(new) and old[i] == new[j]:
            i += 1
            j += 1
            continue
        start = i
        while i < len(old) and (j == len(new) or old[i] != new[j]):
            i += 1
        yield start, i


def normalize_file_text(path: Path, text: str) -> str:
    if not cleans_file_text(path) or is_vocabulary(path, text):
        return text
    if path.stem.casefold() == 'context':
        return normalize_context_text(text)
    return normalize_novel_text(text)


def vocabulary_warnings(text: str) -> list[int]:
    """One-based incomplete row numbers; report only, never repair columns."""
    return [i for i, line in enumerate(LINE_SEPARATOR.split(text), 1)
            if line != '' and line.count('\t') != 3]


def detect_newline(text: str) -> str:
    separators = LINE_SEPARATOR.findall(text)
    return max(dict.fromkeys(separators), key=separators.count) if separators else '\n'
