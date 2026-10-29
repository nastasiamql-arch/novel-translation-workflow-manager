"""Guard async source inspection and clipboard preparation without changing file selection."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QPushButton

from novel_workflow.models import NovelProfile
from novel_workflow.storage import ProjectRepository
from novel_workflow.translation_batch_page import TranslationBatchPage


def test_translation_batch_ignores_lesson_inside_chapter(tmp_path):
    app = QApplication.instance() or QApplication([])
    repo = ProjectRepository(tmp_path / "repo")
    profile = NovelProfile()
    source = tmp_path / "CMR.txt"
    original = (
        "第2章 之前\n正文\n第3章 干仗\n正文\n"
        "第三节课的上课铃刚刚打响，教室后门的动静就吸引了全班的目光。\n"
        "第4章 完结\n结束"
    )
    source.write_text(original, encoding="utf-8")
    page = TranslationBatchPage(repo, lambda: profile, object(), {
        "mode": "file", "path": str(source), "size": 5,
    }, lambda _state: None, lambda: None)
    try:
        assert page._load_worker is not None
        assert page._load_worker.wait(20000)
        app.processEvents()
        assert "พร้อมคัดลอก" in page.summary.text()
        assert len(page._source.chapters) == 3
        assert page._source.chapters[1].number == 3
        assert source.read_text(encoding="utf-8") == original
    finally:
        if page._load_worker and page._load_worker.isRunning():
            page._load_worker.wait(20000)
        page.close()


def test_translation_batch_copy_uses_background_worker_and_exact_files(tmp_path):
    app = QApplication.instance() or QApplication([])
    repo = ProjectRepository(tmp_path / "repo")
    profile = NovelProfile()
    source = tmp_path / "source"
    source.mkdir()
    for i in range(1, 7):
        (source / f"{i:04d}.txt").write_text(f"第{i}章\\n正文 {i}", encoding="utf-8")
    page = TranslationBatchPage(repo, lambda: profile, object(), {
        "mode": "folder", "path": str(source), "size": 3
    }, lambda _state: None, lambda: None)
    try:
        assert page._load_worker is not None
        assert page._load_worker.wait(20000)
        app.processEvents()
        assert len(page._groups) == 2
        button = page.findChild(QPushButton, "translationBatchCopy1")
        assert button is not None
        button.click()
        worker = page._copy_worker
        if worker is not None:
            assert worker.wait(20000)
        app.processEvents()
        mime = app.clipboard().mimeData()
        paths = [Path(url.toLocalFile()) for url in mime.urls()]
        assert len(paths) == 3
        assert [p.name for p in paths] == ["0001.txt", "0002.txt", "0003.txt"]
        assert all(p.is_file() for p in paths)
        assert "สำเร็จ" in page.summary.text()
        from novel_workflow.batch_copy_history import load_history
        events = load_history(repo, profile.id, "translation")
        assert len(events) == 1
        assert events[0]["chapter_numbers"] == [1, 2, 3]
        assert events[0]["copied_file_count"] == 3
        page.close()
        resumed = TranslationBatchPage(repo, lambda: profile, object(), {
            "mode": "folder", "path": str(source), "size": 3
        }, lambda _state: None, lambda: None)
        assert resumed._load_worker.wait(20000)
        app.processEvents()
        assert resumed._group_status(resumed._groups[0]) == "copied"
        assert resumed._group_status(resumed._groups[1]) == "new"
        resumed.close()
    finally:
        if page._load_worker and page._load_worker.isRunning():
            page._load_worker.wait(20000)
        if page._copy_worker and page._copy_worker.isRunning():
            page._copy_worker.wait(20000)
        page.close()


def test_translation_batch_error_shows_actual_source_and_duplicate_locations(tmp_path):
    app = QApplication.instance() or QApplication([])
    repo = ProjectRepository(tmp_path / "repo")
    profile = NovelProfile()
    source = tmp_path / "CMR.txt"
    contents = "第1章 开始\n正文\n第3章 干仗\n正文\n第三章 再次出现\n正文"
    source.write_text(contents, encoding="utf-8")
    page = TranslationBatchPage(repo, lambda: profile, object(), {
        "mode": "file", "path": str(source), "size": 5
    }, lambda _state: None, lambda: None)
    try:
        assert page._load_worker is not None
        assert page._load_worker.wait(20000)
        app.processEvents()
        assert str(source) in page.path_label.text()
        assert str(source) in page.summary.text()
        assert "บรรทัด 3: 第3章 干仗" in page.summary.text()
        assert "บรรทัด 5: 第三章 再次出现" in page.summary.text()
        assert page.summary.textInteractionFlags() & Qt.TextSelectableByMouse
        assert not page._groups
        assert source.read_text(encoding="utf-8") == contents
    finally:
        if page._load_worker and page._load_worker.isRunning():
            page._load_worker.wait(20000)
        page.close()
