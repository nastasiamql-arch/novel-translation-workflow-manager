import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from novel_workflow.downloader.storage import DownloaderRepository
from novel_workflow.downloader_ui.window import DownloaderWindow


def test_challenge_failure_explains_why_book_is_absent_and_how_to_retry(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
    window = DownloaderWindow(DownloaderRepository(tmp_path / "NovelDownloader"))
    window._pending_url = "https://tomatomtl.com/book/123"

    window._add_failed(
        "TomatoMTL is presenting an anti-bot challenge. Open the page in your browser; downloader will not bypass it."
    )

    assert window.books_list.count() == 0
    assert "ยังไม่ได้เพิ่มนิยาย" in window.panel.summary.text()
    assert "รายการทางซ้าย" in window.panel.summary.text()
    assert "กด + เพิ่มจาก URL อีกครั้ง" in window.panel.summary.text()
    assert "ยังไม่ได้เพิ่มนิยาย" in window.statusBar().currentMessage()
    window.close()


def test_other_add_failure_remains_visible_after_warning_is_closed(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
    window = DownloaderWindow(DownloaderRepository(tmp_path / "NovelDownloader"))

    window._add_failed("No source supports this URL")

    assert "No source supports this URL" in window.panel.summary.text()
    assert "รายการทางซ้าย" in window.panel.summary.text()
    window.close()
