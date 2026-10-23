"""Durable, fail-closed AI web job records. No browser or Qt dependencies."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import re

from novel_workflow.storage import read_json, write_json

MAX_TABS = 10
TERMINAL = {"IMPORTED", "CANCELLED"}
ENDING = "[จบตอน]"
HEADING = re.compile(r"(?m)^[ \t]*(?:บทที่|ตอนที่)[ \t]*(\d+)[^\n]*$")
VOCABULARY = re.compile(r"(?m)^[ \t]*คำศัพท์ใหม่[ \t]*$")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AIJob:
    job_id: str
    batch_id: str
    profile_id: str
    stage: str
    submission_order: int
    chapter_numbers: list[int]
    source_files: list[str]
    reference_files: list[str]
    prepared_files: list[str] = field(default_factory=list)
    model: str = ""
    prompt: str = ""
    status: str = "PREPARED"
    error: str = ""
    page_url: str = ""
    raw_response: str = ""
    raw_response_history: list[dict[str, str]] = field(default_factory=list)
    chapters: dict[str, str] = field(default_factory=dict)
    vocabulary: dict[str, list[str]] = field(default_factory=dict)
    submitted_verified: bool = False
    imported: bool = False
    auto_export: bool = False
    created_at: str = field(default_factory=now)
    submitted_at: str = ""
    received_at: str = ""
    events: list[dict[str, str]] = field(default_factory=list)


def build_jobs(profile_id: str, stage: str, chapters, per_job: int,
               *, max_tabs: int = 10, references=(), model="", prompt="") -> list[AIJob]:
    """Group distinct consecutively numbered chapters without inventing missing ones."""
    if stage not in {"หาศัพท์", "แปล", "เกลา"}:
        raise ValueError("ไม่รู้จักขั้นตอน")
    if not 1 <= max_tabs <= MAX_TABS or per_job < 1:
        raise ValueError("จำนวนแท็บหรือบทต่องานไม่ถูกต้อง")
    chapters = sorted(chapters, key=lambda x: x.number)
    numbers = [ch.number for ch in chapters]
    if not numbers or len(numbers) != len(set(numbers)):
        raise ValueError("ต้นฉบับว่างหรือมีเลขบทซ้ำ")
    if numbers != list(range(numbers[0], numbers[-1] + 1)):
        raise ValueError("เลขบทขาดช่วง: กรุณาเลือกช่วงที่ต่อเนื่อง")
    groups = [chapters[i:i + per_job] for i in range(0, len(chapters), per_job)]
    if len(groups) > max_tabs:
        raise ValueError(f"งาน {len(groups)} ชุด เกินขีดจำกัด {max_tabs} แท็บ")
    batch_id = uuid4().hex
    result = []
    for i, group in enumerate(groups, 1):
        result.append(AIJob(
            job_id=uuid4().hex, batch_id=batch_id, profile_id=profile_id, stage=stage,
            submission_order=i, chapter_numbers=[ch.number for ch in group],
            source_files=[str(ch.path) if ch.path is not None else "" for ch in group],
            reference_files=[str(ref) for ref in references],
            model=model, prompt=prompt,
        ))
    return result


def parse_translation(text: str, expected_numbers) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Only accept complete, unambiguous chapter boundaries; never discard raw data."""
    expected = list(expected_numbers)
    matches = list(HEADING.finditer(text))
    numbers = [int(m.group(1)) for m in matches]
    if numbers != expected:
        raise ValueError(f"RESULT_INCOMPLETE: คาดบท {expected} แต่พบ {numbers}")
    if text[:matches[0].start()].strip():
        raise ValueError("RESULT_PARSE_FAILED: มีข้อความก่อนหัวบท")
    chapters, vocabulary = {}, {}
    for i, match in enumerate(matches):
        number = str(expected[i])
        segment = text[match.start():matches[i + 1].start() if i + 1 < len(matches) else len(text)]
        end = segment.find(ENDING)
        if end < 0 or segment[:end].count(ENDING) != 0:
            raise ValueError(f"RESULT_PARSE_FAILED: บท {number} ไม่มี [จบตอน]")
        body = segment[:end].strip()
        tail = segment[end + len(ENDING):].strip()
        if not body or body.strip() == match.group(0).strip():
            raise ValueError(f"RESULT_INCOMPLETE: บท {number} ไม่มีเนื้อหา")
        if tail:
            vocabulary_match = VOCABULARY.search(tail)
            if vocabulary_match is None or tail[:vocabulary_match.start()].strip():
                raise ValueError(f"RESULT_PARSE_FAILED: บท {number} มีข้อความนอกโครงสร้าง")
            items = tail[vocabulary_match.end():].strip()
            if items == "[-]" or not items:
                vocabulary[number] = []
            else:
                vocabulary[number] = [line.strip() for line in items.splitlines()
                                      if line.strip()]
                if any("[-]" in term for term in vocabulary[number]):
                    raise ValueError("RESULT_PARSE_FAILED: [-] ปะปนรายการคำศัพท์")
        else:
            vocabulary[number] = []
        chapters[number] = body + "\n" + ENDING
    return chapters, vocabulary


class JobStore:
    """Atomic per-profile state; writes never go to the Git checkout."""
    def __init__(self, root: Path, profile_id: str):
        if not re.fullmatch(r"[a-fA-F0-9]{32}", profile_id):
            raise ValueError("Invalid profile ID")
        self.path = Path(root) / "profiles" / profile_id / "ai_workspace_jobs.json"

    def load(self) -> list[AIJob]:
        doc = read_json(self.path, {"schema": 1, "jobs": []})
        if not isinstance(doc, dict) or doc.get("schema") != 1 or not isinstance(doc.get("jobs"), list):
            raise ValueError("AI Workspace state schema ไม่ถูกต้อง")
        return [AIJob(**entry) for entry in doc["jobs"]]

    def save(self, jobs: list[AIJob]) -> None:
        identifiers = [job.job_id for job in jobs]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("job_id ซ้ำ")
        write_json(self.path, {"schema": 1, "jobs": [asdict(job) for job in jobs]})

    def update(self, jobs: list[AIJob], updated: AIJob) -> None:
        if updated.job_id not in {j.job_id for j in jobs}:
            raise ValueError("Job not found")
        self.save(jobs)


def ordered_results(jobs: list[AIJob]) -> str:
    if not jobs:
        raise ValueError("ยังไม่มีงาน")
    ordered = sorted(jobs, key=lambda item: item.submission_order)
    if [j.submission_order for j in ordered] != list(range(1, len(jobs) + 1)):
        raise ValueError("submission_order ไม่ต่อเนื่อง")
    if any(j.status not in {"RECEIVED", "REVIEWED", "IMPORTED"} for j in ordered):
        raise ValueError("ยังมีงานที่รับผลลัพธ์ไม่ครบ")
    numbers = [n for job in ordered for n in job.chapter_numbers]
    if len(numbers) != len(set(numbers)) or numbers != list(range(numbers[0], numbers[-1] + 1)):
        raise ValueError("มีบทซ้ำหรือขาดช่วง")
    if any(set(j.chapters) != {str(n) for n in j.chapter_numbers} for j in ordered):
        raise ValueError("ผลลัพธ์บางบทไม่ครบ")
    return "\n\n".join(job.chapters[str(n)] for job in ordered for n in job.chapter_numbers) + "\n"


def record_response(job: AIJob, raw: str) -> None:
    """Preserve untrusted raw response even if structural validation fails."""
    if job.imported:
        if job.raw_response != raw:
            raise ValueError("งานนี้ Export แล้ว คำตอบใหม่ไม่สามารถเขียนทับได้")
        return
    if job.raw_response and job.raw_response != raw:
        raise ValueError("คำตอบใหม่ขัดแย้งกับผลลัพธ์เดิม กรุณาตรวจด้วยตนเอง")
    job.raw_response = raw
    job.received_at = now()
    if job.stage in {"หาศัพท์", "เกลา"}:
        # Their existing workflow prompts have their own output contracts.
        # Preserve the complete answer for review instead of incorrectly
        # applying translation chapter delimiters or modifying the glossary.
        job.chapters = {}
        job.vocabulary = {}
        job.status = "RECEIVED" if raw.strip() else "REVIEW_REQUIRED"
        job.error = "รอตรวจผลลัพธ์ของขั้นตอนนี้ด้วยตนเอง" if raw.strip() else "ไม่มีคำตอบ"
        return
    try:
        job.chapters, job.vocabulary = parse_translation(raw, job.chapter_numbers)
    except ValueError as exc:
        job.status = "REVIEW_REQUIRED"
        job.error = str(exc)
    else:
        job.status = "RECEIVED"
        job.error = ""
