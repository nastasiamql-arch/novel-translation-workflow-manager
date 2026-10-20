"""Guard async source inspection and clipboard preparation without changing file selection."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

from PySide6.QtWidgets import QApplication, QPushButton

from novel_workflow.models import NovelProfile
from novel_workflow.storage import ProjectRepository
from novel_workflow.translation_batch_page import TranslationBatchPage


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
        assert page._copy_worker is not None
        assert page._copy_worker.wait(20000)
        app.processEvents()
        mime = app.clipboard().mimeData()
        paths = [Path(url.toLocalFile()) for url in mime.urls()]
        assert len(paths) == 3
        assert [p.name for p in paths] == ["0001.txt", "0002.txt", "0003.txt"]
        assert all(p.is_file() for p in paths)
        assert "สำเร็จ" in page.summary.text()
    finally:
        if page._load_worker and page._load_worker.isRunning():
            page._load_worker.wait(20000)
        if page._copy_worker and page._copy_worker.isRunning():
            page._copy_worker.wait(20000)
        page.close()
