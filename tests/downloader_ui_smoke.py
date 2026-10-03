import os
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton

from novel_workflow.downloader.storage import DownloaderRepository
from novel_workflow.downloader_ui.source_manager import SourceManagerDialog
from novel_workflow.downloader_ui.window import DownloaderWindow


def main():
    with tempfile.TemporaryDirectory(prefix="novel-downloader-smoke-") as directory:
        root = Path(directory)
        repository = DownloaderRepository(root / "NovelDownloader")
        window = DownloaderWindow(repository)
        assert window.books_list.count() == 0
        assert window.panel.book is None
        assert not window.panel.check_button.isEnabled()
        assert not window.panel.new_button.isEnabled()
        assert "กด + เพิ่มจาก URL" in window.panel.summary.text()
        sources = SourceManagerDialog(repository.sources_dir, window)
        source_buttons = {button.text() for button in sources.findChildren(QPushButton)}
        assert "รีเฟรชรายชื่อเว็บ" in source_buttons
        assert "โหลดใหม่" not in source_buttons
        assert "ไม่ได้ดาวน์โหลดนิยาย" in sources.purpose_label.text()
        sources.close()
        assert not (root / "NovelWorkflow").exists()
        assert repository.root.name == "NovelDownloader"
        window.close()
        print("Downloader UI smoke passed: standalone storage, empty library, disabled actions, no Palantir data access")


if __name__ == "__main__":
    app = QApplication.instance() or QApplication([])
    main()
