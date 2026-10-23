"""AI Workspace preparation integration: real disk content and ZIP bytes."""
from zipfile import ZipFile

from novel_workflow.ai_workspace.core import build_jobs, JobStore, record_response
from novel_workflow.ai_workspace.page import BundlePreparationWorker
from novel_workflow.translation_batches import load_translation_source


def test_real_source_staging_and_zip_recovery(tmp_path):
    source_dir = tmp_path / "novel"
    source_dir.mkdir()
    for number in range(475, 505):
        (source_dir / f"{number}.txt").write_text(
            f"第{number}章 原文\n这是一段测试。\n", encoding="utf-8")
    prompt = tmp_path / "Prompt.md"
    prompt.write_text("Translate according to glossary.", encoding="utf-8")
    source = load_translation_source("folder", path=source_dir)
    jobs = build_jobs("a" * 32, "แปล", source.chapters, 3,
                      references=(prompt,), prompt="Use the attached Prompt.", model="test-model")
    worker = BundlePreparationWorker(source, jobs, (prompt,), tmp_path / "cache", as_zip=True)
    produced, failures = [], []
    worker.prepared.connect(produced.append)
    worker.failed.connect(failures.append)
    worker.run()
    assert not failures
    assert len(produced) == 1
    assert set(produced[0]) == {job.job_id for job in jobs}
    for job in jobs:
        job.prepared_files = produced[0][job.job_id]
        assert len(job.prepared_files) == 1
        with ZipFile(job.prepared_files[0]) as archive:
            assert "references/Prompt.md" in archive.namelist()
            assert len([name for name in archive.namelist() if name.startswith("source/")]) == 3
    store = JobStore(tmp_path, "a" * 32)
    store.save(jobs)
    restored = store.load()
    assert len(restored) == 10
    assert [job.prepared_files for job in restored] == [job.prepared_files for job in jobs]
    assert sorted(chapter for job in restored for chapter in job.chapter_numbers) == list(range(475, 505))


def test_imported_response_idempotent(tmp_path):
    folder = tmp_path / "novel"
    folder.mkdir()
    (folder / "475.txt").write_text("第475章 原文\n", encoding="utf-8")
    source = load_translation_source("folder", path=folder)
    job = build_jobs("a" * 32, "แปล", source.chapters, 1)[0]
    response = "บทที่ 475\nข้อความ\n[จบตอน]\nคำศัพท์ใหม่\n[-]"
    record_response(job, response)
    job.imported = True
    job.status = "IMPORTED"
    record_response(job, response)
    assert job.status == "IMPORTED"
