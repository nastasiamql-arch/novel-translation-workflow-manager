"""Safe, opt-in routing from a saved Translator to an existing review stage.

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
