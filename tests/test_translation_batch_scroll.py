"""Regression: copying a late translation batch must not reset its scroll position."""
import os
import time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from novel_workflow.batch_copy_history import load_history
from novel_workflow.models import NovelProfile
from novel_workflow.storage import ProjectRepository
from novel_workflow.translation_batch_page import TranslationBatchPage


def test_detail_scroll_resets_only_for_a_new_selection(tmp_path):
    app = QApplication.instance() or QApplication([])
    repo = ProjectRepository(tmp_path / "repo")
    profile = NovelProfile()
    folder = tmp_path / "source"
    folder.mkdir()
    for number in range(1, 5):
        (folder / f"{number:04d}.txt").write_text(f"第{number}章\n正文", encoding="utf-8")
    page = TranslationBatchPage(repo, lambda: profile, object(),
                                {"mode": "folder", "path": str(folder), "size": 2},
                                lambda _state: None, lambda: None)
    page.resize(1400, 640)
    page.show()
    try:
        assert page._load_worker.wait(20000)
        app.processEvents()
        if page._copy_worker:
            assert page._copy_worker.wait(20000)
        app.processEvents()
        page._display_references = tuple(folder / f"reference-{i:03d}.txt" for i in range(100))
        page._select_group(page._groups[0], switch=False)
        app.processEvents()
        bar = page.batch_workspace.text.verticalScrollBar()
        assert bar.maximum() > 0
        bar.setValue(bar.maximum() // 2)
        before = bar.value()
        assert before > 0
        page._update_row_states()
        assert bar.value() == before
        page._select_group(page._groups[1], switch=False)
        assert bar.value() == 0
    finally:
        if page._copy_worker and page._copy_worker.isRunning():
            page._copy_worker.wait(20000)
        page.close()
        app.processEvents()


def test_translation_batch_86_copy_preserves_viewport_and_row(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    repo = ProjectRepository(tmp_path / "repo")
    profile = NovelProfile()
    folder = tmp_path / "source"
    folder.mkdir()
    # 90 groups of four chapters, enough to trigger the lazy 35-row boundary.
    for number in range(1, 361):
        (folder / f"{number:04d}.txt").write_text(
            f"第{number}章 测试\\n正文 {number}", encoding="utf-8"
        )
    page = TranslationBatchPage(
        repo, lambda: profile, object(),
        {"mode": "folder", "path": str(folder), "size": 4},
        lambda _state: None, lambda: None,
    )
    page.resize(980, 640)
    page.show()
    try:
        assert page._load_worker is not None
        assert page._load_worker.wait(20000)
        app.processEvents()
        assert len(page._groups) == 90
        group = page._groups[85]
        page._scroll_to_group(group)
        app.processEvents()
        # Force a measurable scroll range on the headless Windows Qt runner.
        # Its offscreen layout may report an empty viewport despite showing
        # and creating all 86 lazy rows. The copy behavior must preserve an
        # existing nonzero scrollbar position, independently of window manager.
        page.scroll.setWidgetResizable(False)
        page.rows_host.setFixedHeight(9000)
        page.rows_host.resize(920, 9000)
        app.processEvents()
        bar = page.scroll.verticalScrollBar()
        assert bar.maximum() > 0
        bar.setValue(min(4500, bar.maximum()))
        before = bar.value()
        assert before > 0
        assert page._rendered >= 86
        button = page.findChild(QPushButton, "translationBatchCopy86")
        status = page.findChild(QLabel, "translationBatchStatus86")
        assert button is not None and status is not None
        row = button.parent()
        # Deliberately jumping ahead must request confirmation, but repeated
        # copies of the same already-copied old group must never request it.
        prompts = []
        def confirm(skipped, target):
            prompts.append((skipped.index, target.index))
            return True
        monkeypatch.setattr(page, "_confirm_skipped_group", confirm)

        for copy_number in (1, 2):
            button.click()
            assert page._selected_group == group
            assert f"ชุด {group.index} ·" in page.batch_workspace.title.text()
            assert page.state["selected_batch"]["index"] == group.index
            worker = page._copy_worker
            if worker is not None:
                assert worker.wait(20000)
            app.processEvents()
            # A prewarm worker may finish while the requested copy is queued;
            # its finished handler then starts a replacement worker. Wait for
            # the copy itself rather than assuming one worker is sufficient.
            deadline = time.monotonic() + 20
            while page._copy_pending is not None and time.monotonic() < deadline:
                QTest.qWait(20)
            assert page._copy_pending is None
            # The original row is still alive and the list remains rendered
            # beyond the first 35 groups; no jump to group 1/26.
            assert page._rendered >= 86
            assert page.findChild(QPushButton, "translationBatchCopy86") is button
            assert button.parent() is row
            assert bar.value() == before
            assert "คัดลอกแล้ว" in status.text()
            assert "คัดลอกอีกครั้ง" in button.text()
            assert len(load_history(repo, profile.id, "translation")) == copy_number
        assert prompts == [(1, 86)]
    finally:
        if page._load_worker and page._load_worker.isRunning():
            page._load_worker.wait(20000)
        if page._copy_worker and page._copy_worker.isRunning():
            page._copy_worker.wait(20000)
        page.close()
        app.processEvents()
