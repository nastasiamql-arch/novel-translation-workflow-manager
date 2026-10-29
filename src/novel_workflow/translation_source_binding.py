"""Translation-stage attachments only; never use the vocabulary or review stage."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .polish_history import _files
from .workflow_archive import resolve_attachment, _check_path
from .vocabulary_source_binding import source_score, VocabularyAttachment


@dataclass(frozen=True)
class TranslationAttachment:
    id: str
    label: str
    path: Path | None
    dynamic_reference: str | None = None
    error: str = ""


def translation_step(profile):
    matches = [step for step in profile.workflow.steps if step.name.strip() == "แปล"]
    if len(matches) != 1:
        raise ValueError("ไม่พบขั้นตอนแปลที่ระบุได้แน่นอน กรุณาตรวจ Workflow")
    return matches[0]


def enabled_translation_attachments(repo, assembler, profile):
    step = translation_step(profile)
    results = []
    for item in sorted(step.files, key=lambda f: f.order):
        if not item.enabled:
            continue
        try:
            path = resolve_attachment(repo, assembler, profile, item)
            error = ""
        except (OSError, ValueError, KeyError, TypeError) as exc:
            path, error = None, str(exc)
        results.append(TranslationAttachment(
            item.id, item.label or item.path or item.dynamic_reference or "ไฟล์",
            path, item.dynamic_reference, error
        ))
    return tuple(results)


def source_candidates(entries):
    """Display all enabled candidates; user makes the source selection."""
    return tuple(e for e in entries if e.path is not None and (
        e.path.is_dir() or e.path.suffix.casefold() == ".txt"
    ))


def translation_reference_files(entries, source_path=None, selected_id=None):
    """Resolve only enabled translation assets and drop source alternatives.

    Do not silently attach other bound TXT novels, numbered sibling chapters
    or dynamic source references when preparing a selected range.
    """
    source = _check_path(source_path) if source_path else None
    originals = {source} if source and source.is_file() else set()
    if source and source.is_dir():
        from .translation_batches import fast_folder_snapshot
        originals.update(path for _, path, _ in fast_folder_snapshot(source))
    result, seen = [], set()
    for entry in entries:
        if entry.id == selected_id or entry.dynamic_reference == "CURRENT_SOURCE_CHAPTER":
            continue
        if entry.path is None:
            raise ValueError(f"ไฟล์ขั้นตอนแปลไม่พร้อม: {entry.label}: {entry.error}")
        path = _check_path(entry.path)
        if path in originals or source and source.is_dir() and path.is_relative_to(source):
            continue
        score = source_score(VocabularyAttachment(entry.id, entry.label, path, entry.dynamic_reference))
        if score >= 70:
            continue
        for file in _files(path):
            resolved = _check_path(file)
            if resolved in originals:
                continue
            key = str(resolved).casefold()
            if key not in seen:
                seen.add(key)
                result.append(resolved)
    return tuple(result)
