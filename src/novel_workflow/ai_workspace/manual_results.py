"""Fail-closed import from a manually selected Chrome job."""
from __future__ import annotations

import hashlib
import re

from .core import record_response, parse_translation, HEADING


def accept_clipboard_response(job, raw: str) -> bool:
    """Return False for identical content; never overwrite or misattribute a response.

    Unparseable material can be retained for review only if it does not identify
    chapters belonging to another job. Existing responses remain untouched.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("Clipboard ว่างหรือไม่ใช่ข้อความ")
    expected = list(job.chapter_numbers)
    found = [int(m.group(1)) for m in HEADING.finditer(raw)]
    if found and found != expected:
        raise ValueError(f"WRONG_JOB: งานนี้ต้องเป็นบท {expected} แต่ Clipboard มีบท {found}")
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    if job.raw_response:
        old_hash = hashlib.sha256(job.raw_response.encode("utf-8")).hexdigest()
        if old_hash == digest:
            return False
        raise ValueError("RESPONSE_CONFLICT: คำตอบใหม่ต่างจากของเดิม กรุณาตรวจและเก็บสำรองก่อนแทนที่")
    if job.stage == "แปล" and found:
        # Reject wrong-chapter payload before persisting any response.
        try:
            parse_translation(raw, expected)
        except ValueError:
            # Keep the raw response for user-led review, without promoting it.
            pass
    record_response(job, raw)
    return True
