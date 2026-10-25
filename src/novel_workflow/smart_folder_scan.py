"""Pure bounded folder scan and role matching helpers."""
from pathlib import Path
import re

EXCLUDED_DIRS = {"backup", "recovery", "polish history", "cache", "__pycache__",
                 ".git", ".metadata", "metadata", "novelworkflow", "history"}
MAX_FILES = 10000
MAX_DEPTH = 8


def scan_novel_folder(root, *, max_files=MAX_FILES, max_depth=MAX_DEPTH):
    """Find files without following links; prune application and backup folders."""
    root = Path(root).expanduser()
    if not root.is_dir():
        return []
    found = []
    stack = [(root, 0)]
    while stack and len(found) < max_files:
        folder, depth = stack.pop()
        try:
            with __import__('os').scandir(folder) as entries:
                for entry in entries:
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            if depth < max_depth and entry.name.casefold() not in EXCLUDED_DIRS:
                                stack.append((Path(entry.path), depth + 1))
                        elif entry.is_file(follow_symlinks=False):
                            name = entry.name.casefold()
                            if (name.startswith("~$") or name.endswith((".tmp", ".temp", ".bak", "~"))
                                    or ".tmp." in name or ".temp." in name):
                                continue
                            found.append(Path(entry.path))
                            if len(found) >= max_files:
                                break
                    except OSError:
                        continue
        except OSError:
            continue
    return sorted(found, key=lambda path: (len(path.parts), str(path).casefold()))


def infer_novel_code(paths, configured=""):
    if configured.strip():
        return configured.strip()
    counts = {}
    for path in paths:
        stem = path.stem.strip()
        match = re.fullmatch(r"(.+?)(?:[ _.-]?)(?:context|glossary|translator|prompt|style)", stem, re.I)
        if match:
            code = match.group(1).strip(" _.-")
            if code:
                counts[code] = counts.get(code, 0) + 1
    if not counts:
        return ""
    highest = max(counts.values())
    winners = sorted(code for code, count in counts.items() if count == highest)
    return winners[0] if len(winners) == 1 else ""


def _compact(value):
    return re.sub(r"[\s_.-]+", "", value).casefold()


def candidates_by_role(paths, code):
    roles = {key: [] for key in ("prompt", "style", "guideline", "main", "context",
                                  "glossary", "translator", "novel", "vocab_instruction")}
    code_key = _compact(code)
    for path in paths:
        stem = _compact(path.stem)
        if code_key:
            for role, suffix in (("prompt", "prompt"), ("style", "style"),
                                 ("context", "context"), ("glossary", "glossary"),
                                 ("translator", "translator")):
                if stem == code_key + _compact(suffix):
                    roles[role].append(path)
            if stem == code_key:
                roles["main"].append(path)
        if stem in {_compact("ไกด์ไลน์การแปล"), _compact("แนวทางการแปล"), "translationguideline", "translationguidelines"}:
            roles["guideline"].append(path)
        if stem == _compact("Novel"):
            roles["novel"].append(path)
        if stem == _compact("a หาศัพท์") or stem == _compact("หาศัพท์"):
            roles["vocab_instruction"].append(path)
    # Preferred locations influence only tie-breaking when there is a single best-area match.
    for role in ("prompt", "style", "guideline"):
        project = [p for p in roles[role] if "project" in {part.casefold() for part in p.parts}]
        if project:
            roles[role] = project
    return roles
