"""Resolve existing stage attachments without creating duplicate settings."""
from __future__ import annotations

from novel_workflow.translation_source_binding import (
    TranslationAttachment, enabled_translation_attachments,
)
from novel_workflow.vocabulary_source_binding import enabled_vocabulary_attachments
from novel_workflow.workflow_archive import resolve_attachment


def stage_attachments(repo, assembler, profile, stage):
    if profile is None:
        raise ValueError("ยังไม่ได้เลือกนิยาย")
    if stage == "แปล":
        return enabled_translation_attachments(repo, assembler, profile)
    if stage == "หาศัพท์":
        return enabled_vocabulary_attachments(repo, assembler, profile)
    if stage != "เกลา":
        raise ValueError("ขั้นตอน AI ไม่ถูกต้อง")
    matches = [s for s in profile.workflow.steps
               if s.name.strip() in {"เกลา", "เกลาสำนวน", "ตรวจคำแปล"}]
    if len(matches) != 1:
        raise ValueError("ไม่สามารถระบุขั้นตอนเกลาที่ผูกไว้ได้แน่นอน")
    files = []
    for item in sorted(matches[0].files, key=lambda f: f.order):
        if not item.enabled:
            continue
        try:
            resolved = resolve_attachment(repo, assembler, profile, item)
            error = ""
        except (OSError, ValueError, TypeError, KeyError) as exc:
            resolved, error = None, str(exc)
        files.append(TranslationAttachment(item.id, item.label or item.path or "ไฟล์",
                                            resolved, item.dynamic_reference, error))
    return tuple(files)
