import re
import unicodedata

_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$", re.IGNORECASE)


def format_chapter_filename(index: int, title: str, max_length: int = 180) -> str:
    if isinstance(index, bool) or not isinstance(index, int) or index < 0:
        raise ValueError("Chapter index must be a non-negative integer")
    prefix = f"{index:04d} "
    normalized = unicodedata.normalize("NFC", str(title or "").strip())
    safe = _INVALID.sub("_", normalized).rstrip(" .")
    if not safe:
        safe = "untitled"
    if _RESERVED.match(safe):
        safe = "_" + safe
    safe = safe[: max(1, max_length - len(prefix) - 4)].rstrip(" .") or "untitled"
    return f"{prefix}{safe}.txt"
