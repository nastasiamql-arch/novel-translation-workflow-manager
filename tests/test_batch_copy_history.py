from novel_workflow.batch_copy_history import (
    group_copy_status, load_history, record_copy,
)
from novel_workflow.storage import ProjectRepository


def test_copy_history_is_profile_scoped_atomic_and_revision_aware(tmp_path):
    repo = ProjectRepository(tmp_path / "app")
    first = "a" * 32
    second = "b" * 32
    event = record_copy(
        repo, first, "translation", identity="source-a", revision="rev-1",
        start=1, end=2, chapter_numbers=[1, 2], batch_size=2,
        copy_mode="files", copied_file_count=2,
        chapter_fingerprints={"1": "x", "2": "y"},
    )
    assert event["success"] is True
    assert len(load_history(repo, first, "translation")) == 1
    assert load_history(repo, second, "translation") == []
    events = load_history(repo, first, "translation")
    assert group_copy_status(
        events, identity="source-a", revision="rev-1", start=1, end=2,
        chapter_numbers=[1, 2], chapter_fingerprints={"1": "x", "2": "y"},
    ) == "copied"
    assert group_copy_status(
        events, identity="source-a", revision="rev-2", start=1, end=2,
        chapter_numbers=[1, 2], chapter_fingerprints={"1": "x", "2": "y"},
    ) == "review"
    assert group_copy_status(
        events, identity="source-b", revision="rev-1", start=1, end=2,
        chapter_numbers=[1, 2],
    ) == "new"


def test_copy_history_repeat_events_do_not_change_unique_group_status(tmp_path):
    repo = ProjectRepository(tmp_path / "app")
    profile_id = "c" * 32
    for _ in range(2):
        record_copy(
            repo, profile_id, "vocabulary", identity="folder", revision="rev",
            start=10, end=12, chapter_numbers=[10, 11, 12], batch_size=3,
            copy_mode="zip", copied_file_count=1,
        )
    events = load_history(repo, profile_id, "vocabulary")
    assert len(events) == 2
    assert group_copy_status(
        events, identity="folder", revision="rev", start=10, end=12,
        chapter_numbers=[10, 11, 12],
    ) == "copied"


def test_batch_draft_lives_outside_settings_and_restores_per_profile(tmp_path):
    repo = ProjectRepository(tmp_path / "app")
    profile_id = "d" * 32
    draft = "第一章\n" + ("เนื้อหา" * 3000)
    repo.save_batch_draft(profile_id, "translation", draft)
    assert repo.load_batch_draft(profile_id, "translation") == draft
    assert repo.load_batch_draft("e" * 32, "translation") == ""
    assert not repo.settings_path.exists()


def test_vocabulary_page_restores_copy_state_after_restart(tmp_path):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QPushButton
    from novel_workflow.vocabulary_batch_page import TxtVocabularyPage

    app = QApplication.instance() or QApplication([])
    repo = ProjectRepository(tmp_path / "app")
    profile_id = "f" * 32
    source = tmp_path / "chapters"
    source.mkdir()
    for number in range(1, 5):
        (source / f"{number:04d}.txt").write_text(f"บท {number}", encoding="utf-8")
    page = TxtVocabularyPage(
        {"folder": str(source), "batch_size": 2}, lambda _state: None, source,
        repo=repo, profile_id=profile_id,
    )
    first = page.findChild(QPushButton, "txtVocabularyCopyBatch1")
    assert first is not None
    first.click()
    assert len(load_history(repo, profile_id, "vocabulary")) == 1
    page.close()
    resumed = TxtVocabularyPage(
        {"folder": str(source), "batch_size": 2}, lambda _state: None, source,
        repo=repo, profile_id=profile_id,
    )
    restored_button = resumed.findChild(QPushButton, "txtVocabularyCopyBatch1")
    assert restored_button is not None
    assert "คัดลอกอีกครั้ง" in restored_button.text()
    assert "คัดลอกแล้ว 1 ชุด" in resumed.summary.text()
    assert "ยังไม่ได้ 1 ชุด" in resumed.summary.text()
    resumed.close()
    app.processEvents()
