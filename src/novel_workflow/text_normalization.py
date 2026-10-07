"""Remove empty text lines without trimming meaningful lines or TSV fields."""
from pathlib import Path


def remove_empty_lines(text: str) -> str:
    # Split newline sequences only: vertical tabs and other characters within
    # a nonempty line are content, not paragraph separators.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line for line in text.split("\n") if line.strip())


def cleans_file_text(path: Path) -> bool:
    """Plain text/TSV and novel Markdown use compact paragraph formatting."""
    if path.suffix.lower() in {".txt", ".tsv"}:
        return not any(part.lower() in {"prompts", "style"} for part in path.parts)
    return path.suffix.lower() in {".md", ".markdown"} and (
        path.stem.lower() == "context"
        or any(part.lower() in {"source", "translated", "reviewed", "glossary", "characters"}
               for part in path.parts)
    )
