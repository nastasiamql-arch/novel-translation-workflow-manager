import os
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from novel_workflow.downloader.storage import DownloaderRepository
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
        assert not (root / "NovelWorkflow").exists()
        assert repository.root.name == "NovelDownloader"
        window.close()
        print("Downloader UI smoke passed: standalone storage, empty library, disabled actions, no Palantir data access")


if __name__ == "__main__":
    app = QApplication.instance() or QApplication([])
    main()
