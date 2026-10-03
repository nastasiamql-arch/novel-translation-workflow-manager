"""Standalone entry point for Novel Downloader."""
import sys
from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase, QIcon
from PySide6.QtWidgets import QApplication

from .downloader_ui.window import DownloaderWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Novel Downloader")
    app.setOrganizationName("NovelDownloader")
    families = set(QFontDatabase.families())
    font = QFont()
    font.setFamilies([name for name in ("Segoe UI Variable Text", "Leelawadee UI", "Segoe UI", "Tahoma") if name in families])
    font.setPointSizeF(10.5)
    app.setFont(font)
    icon_path = Path(__file__).resolve().parent / "resources" / "palantir_novel.png"
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))
    window = DownloaderWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
