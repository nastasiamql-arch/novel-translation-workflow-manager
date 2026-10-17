"""Safe opt-in checks for source chapters and existing Translator workflow handoff.

A workflow stage consists of files to copy. It does not perform AI proofreading
or mark a chapter reviewed; only the user can confirm review completion.
"""
from pathlib import Path


def suggested_review_step_ids(profile):
    """Best-effort UI defaults; saved user-selected step IDs take precedence."""
    translation = next(
        (step.id for step in profile.workflow.steps
         if step.name.strip().casefold() in {"แปล", "translator", "translation"}),
        None,
    )
    review = next(
        (step.id for step in profile.workflow.steps
         if step.name.strip().casefold() in {"ตรวจสอบบท", "ตรวจคำแปล", "review", "proofread"}),
        None,
    )
    return translation, review


def review_step_index(profile, active_index, document_path):
    """Return the chosen review stage only for an enabled, active Translator step."""
    if not profile.auto_review_enabled or document_path is None:
        return None
    steps = profile.workflow.steps
    translation, review = suggested_review_step_ids(profile)
    translation = profile.auto_review_translation_step_id or translation
    review = profile.auto_review_step_id or review
    if not translation or not review or translation == review:
        return None
    if not 0 <= active_index < len(steps) or steps[active_index].id != translation:
        return None
    filename = Path(document_path).name.casefold()
    # Only the project's novel-specific Translator work file is eligible.
    # Never trigger on context, source, notes, or an export draft.
    if filename == "translator.txt" or not filename.endswith("translator.txt"):
        return None
    return next((index for index, step in enumerate(steps) if step.id == review), None)

def is_original_source_document(path, bound_paths, project_source_dir, main_folder=None):
    """Require a source text document owned by this novel; never scan Context/Translator."""
    if path is None:
        return False
    candidate = Path(path).expanduser().resolve()
    name = candidate.name.casefold()
    if candidate.suffix.casefold() not in {".txt", ".md", ".markdown"}:
        return False
    if any(name.endswith(suffix) for suffix in (
        "translator.txt", "context.txt", "glossary.txt", "vocabulary.txt",
        "reviewed.txt", "notes.txt", "prompt.md",
    )):
        return False
    if candidate in bound_paths:
        return True
    project_source_dir = Path(project_source_dir).resolve()
    if candidate.is_relative_to(project_source_dir):
        return True
    if main_folder:
        root = Path(main_folder).expanduser().resolve()
        if candidate.parent in {root, root / "source"}:
            return True
    return False


def scan_original_chapter_issues(text):
    """Reuse the existing number scanner, returning issues without changing text."""
    from .chapter_numbering import scan_chapters, chapter_issues
    headings = scan_chapters(text)
    return headings, chapter_issues(headings)
