from pathlib import Path
from types import SimpleNamespace
import pytest

from novel_workflow.ai_workspace.core import (
    build_jobs, parse_translation, record_response, ordered_results, JobStore,
)


def chapters(start=475, count=30):
    return [SimpleNamespace(number=i, path=Path(f"{i}.txt")) for i in range(start, start + count)]


def test_ten_groups_30_chapters():
    jobs = build_jobs("a" * 32, "แปล", chapters(), 3)
    assert len(jobs) == 10
    assert [job.submission_order for job in jobs] == list(range(1, 11))
    assert jobs[0].chapter_numbers == [475, 476, 477]
    assert jobs[-1].chapter_numbers == [502, 503, 504]
    assert len({j.job_id for j in jobs}) == 10


def test_no_extra_tabs_and_missing_numbers():
    with pytest.raises(ValueError, match="เกิน"):
        build_jobs("a" * 32, "แปล", chapters(), 2)
    with pytest.raises(ValueError, match="ขาดช่วง"):
        build_jobs("a" * 32, "แปล", chapters()[:1] + chapters()[2:], 3)
    with pytest.raises(ValueError, match="ซ้ำ"):
        build_jobs("a" * 32, "แปล", chapters()[:3] + chapters()[:1], 3)


def example(n, term="[-]"):
    return f"บทที่ {n}\nเนื้อหาของบท {n}\n[จบตอน]\nคำศัพท์ใหม่\n{term}\n"


def test_parse_vocab_and_empty_marker():
    parsed, vocab = parse_translation(example(475) + example(476, "凌云 = หลิงอวิ๋น"), [475, 476])
    assert vocab["475"] == []
    assert vocab["476"] == ["凌云 = หลิงอวิ๋น"]
    assert parsed["475"].endswith("[จบตอน]")


def test_parse_never_silently_truncates():
    for text in (example(475) + "unrecognized", "preface\n" + example(475),
                 "บทที่ 475\nbad", example(476)):
        with pytest.raises(ValueError):
            parse_translation(text, [475])


def test_order_by_submission_order_after_out_of_order_arrival():
    jobs = build_jobs("a" * 32, "แปล", chapters(475, 3), 1)
    for i in (2, 0, 1):
        record_response(jobs[i], example(jobs[i].chapter_numbers[0]))
    assert [int(line.split()[1]) for line in ordered_results(jobs).splitlines()
            if line.startswith("บทที่")] == [475, 476, 477]


def test_missing_job_prevents_export_and_recovers(tmp_path):
    jobs = build_jobs("a" * 32, "แปล", chapters(475, 3), 1)
    record_response(jobs[2], example(477))
    with pytest.raises(ValueError, match="ไม่ครบ"):
        ordered_results(jobs)
    store = JobStore(tmp_path, "a" * 32)
    store.save(jobs)
    recovered = store.load()
    assert recovered[2].raw_response == jobs[2].raw_response
    assert recovered[0].submission_order == 1
    record_response(recovered[0], example(475))
    record_response(recovered[1], example(476))
    assert "บทที่ 477" in ordered_results(recovered)


def test_raw_survives_parser_failure():
    job = build_jobs("a" * 32, "แปล", chapters(475, 1), 1)[0]
    record_response(job, "not structured")
    assert job.status == "REVIEW_REQUIRED" and job.raw_response == "not structured"


def test_auto_export_requires_explicit_persisted_batch_permission(tmp_path):
    jobs = build_jobs("a" * 32, "แปล", chapters(475, 3), 1)
    assert not any(job.auto_export for job in jobs)
    for job in jobs:
        job.auto_export = True
        record_response(job, example(job.chapter_numbers[0]))
    store = JobStore(tmp_path, "a" * 32)
    store.save(jobs)
    restored = store.load()
    assert all(job.auto_export for job in restored)
    assert [job.submission_order for job in restored] == [1, 2, 3]
    assert "บทที่ 477" in ordered_results(restored)


@pytest.mark.parametrize("stage", ["หาศัพท์", "เกลา"])
def test_stage_specific_raw_is_not_misparsed_as_translation(stage):
    job = build_jobs("a" * 32, stage, chapters(475, 1), 1)[0]
    raw = "คำศัพท์ใหม่\n凌云 = หลิงอวิ๋น\n[-]" if stage == "หาศัพท์" else "ข้อความเกลาที่ไม่ได้มีหัวบท"
    record_response(job, raw)
    assert job.status == "RECEIVED"
    assert job.raw_response == raw
    assert not job.chapters and not job.vocabulary
    with pytest.raises(ValueError):
        ordered_results([job])
