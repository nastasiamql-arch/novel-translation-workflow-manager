import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QPushButton, QMessageBox

from novel_workflow.downloader_ui import source_manager
from novel_workflow.downloader_ui.source_manager import SourceManagerDialog


def test_test_url_challenge_offers_to_open_the_same_url(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    dialog = SourceManagerDialog(tmp_path)
    opened = []
    monkeypatch.setattr(source_manager.QDesktopServices, "openUrl", opened.append)

    def click_open_button():
        message_box = app.activeModalWidget()
        if message_box is None:
            QTimer.singleShot(10, click_open_button)
            return
        for button in message_box.findChildren(QPushButton):
            if button.text() == "เปิดหน้าเว็บใน Browser":
                button.click()
                return
        QTimer.singleShot(10, click_open_button)

    QTimer.singleShot(10, click_open_button)
    url = "https://tomatomtl.com/book/123"
    dialog._test_failed(
        "TomatoMTL is presenting an anti-bot challenge. Open the page in your browser; downloader will not bypass it.",
        url,
    )

    assert len(opened) == 1
    assert opened[0].toString() == url
    dialog.close()


def test_non_challenge_source_error_stays_a_warning(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    dialog = SourceManagerDialog(tmp_path)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    dialog._test_failed("The source returned HTTP 404", "https://example.com/book")
    assert warnings and warnings[0][2] == "The source returned HTTP 404"
    dialog.close()
