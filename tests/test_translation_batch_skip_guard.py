"""Skip prevention must never block re-copying a previously copied AI batch."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton, QLabel
from novel_workflow.batch_copy_history import load_history
from novel_workflow.models import NovelProfile
from novel_workflow.storage import ProjectRepository
from novel_workflow.translation_batch_page import TranslationBatchPage


def _copy_and_finish(page, app, index):
    button = page.findChild(QPushButton, f"translationBatchCopy{index}")
    assert button is not None
    button.click()
    worker = page._copy_worker
    assert worker is not None
    assert worker.wait(20000)
    app.processEvents()
    assert "สำเร็จ" in page.summary.text()


def test_skipping_needs_confirmation_but_old_batches_can_always_be_recopied(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    repo = ProjectRepository(tmp_path / "repo")
    profile = NovelProfile()
    folder = tmp_path / "source"
    folder.mkdir()
    for number in range(1, 10):
        (folder / f"{number:04d}.txt").write_text(f"第{number}章 测试\n正文", encoding="utf-8")
    page = TranslationBatchPage(
        repo, lambda: profile, object(),
        {"mode": "folder", "path": str(folder), "size": 3},
        lambda _state: None, lambda: None,
    )
    page.resize(1100, 640)
    page.show()
    try:
        assert page._load_worker.wait(20000)
        app.processEvents()
        assert len(page._groups) == 3
        first = page.findChild(QPushButton, "translationBatchCopy1")
        second = page.findChild(QPushButton, "translationBatchCopy2")
        third = page.findChild(QPushButton, "translationBatchCopy3")
        assert first.parent().property("batchVisual") == "next"
        assert second.parent().property("batchVisual") == "new"
        assert page.findChild(QLabel, "translationBatchStatus1").text().startswith("●")

        _copy_and_finish(page, app, 1)
        assert first.parent().property("batchVisual") == "copied"
        assert first.property("batchCopyAction") == "repeat"
        assert "คัดลอกอีกครั้ง" in first.text()
        assert second.parent().property("batchVisual") == "next"

        prompts = []
        def deny_skip(skipped, target):
            prompts.append((skipped.index, target.index))
            return False
        monkeypatch.setattr(page, "_confirm_skipped_group", deny_skip)
        third.click()
        assert page._copy_worker is None
        assert prompts == [(2, 3)]
        assert len(load_history(repo, profile.id, "translation")) == 1

        monkeypatch.setattr(page, "_confirm_skipped_group",
                            lambda skipped, target: prompts.append((skipped.index, target.index)) or True)
        _copy_and_finish(page, app, 3)
        assert prompts == [(2, 3), (2, 3)]
        assert second.parent().property("batchVisual") == "next"
        assert third.parent().property("batchVisual") == "copied"

        # AI failed to return the result: an old copied group stays one-click
        # repeatable even after later batches have been copied.
        monkeypatch.setattr(
            page, "_confirm_skipped_group",
            lambda *_args: (_ for _ in ()).throw(AssertionError("old copy must never prompt")),
        )
        _copy_and_finish(page, app, 1)
        assert [e["start"] for e in load_history(repo, profile.id, "translation")] == [1, 7, 1]
        assert "คัดลอกอีกครั้ง" in first.text()
        assert second.parent().property("batchVisual") == "next"
        assert page.state["last_copied_start"] == 1
    finally:
        if page._load_worker and page._load_worker.isRunning():
            page._load_worker.wait(20000)
        if page._copy_worker and page._copy_worker.isRunning():
            page._copy_worker.wait(20000)
        page.close()
        app.processEvents()
