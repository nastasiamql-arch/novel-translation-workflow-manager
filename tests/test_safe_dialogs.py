"""Real Qt widget checks for the bounded chapter and export preview dialog."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from novel_workflow import safe_dialogs


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("count", [0, 1, 10, 50, 100, 1000, 10000])
def test_scrollable_details_preserve_every_line(app, monkeypatch, count):
    details = "\n".join(f"{i} 中文 ไทย " + "very_long_filename_" * 10 for i in range(count))
    dialog = safe_dialogs.ScrollableConfirmation(None, "ตรวจ", "รายการตรวจ", details)
    dialog.show()
    app.processEvents()
    try:
        assert dialog.details.toPlainText() == details
        area = app.primaryScreen().availableGeometry()
        assert dialog.width() <= int(area.width() * .90)
        assert dialog.height() <= int(area.height() * .84)
        assert dialog.actions.isVisible()
        assert dialog.cancel.isVisible()
        assert dialog.details.geometry().bottom() < dialog.actions.geometry().top()
        if count >= 100:
            assert dialog.details.verticalScrollBar().maximum() > 0
    finally:
        dialog.close()


@pytest.mark.parametrize("width,height", [(900, 600), (1280, 720), (1366, 768), (1920, 1080)])
def test_size_limit_with_multiple_screen_shapes(app, monkeypatch, width, height):
    monkeypatch.setattr(
        safe_dialogs, "_available_geometry",
        lambda _parent: QRect(0, 0, width, height),
    )
    dlg = safe_dialogs.ScrollableConfirmation(None, "ตรวจ", "รายการ", "第12章\n" * 1000)
    dlg.show()
    app.processEvents()
    try:
        assert dlg.width() <= int(width * .90)
        assert dlg.height() <= int(height * .84)
        assert dlg.cancel.isVisible()
    finally:
        dlg.close()


def test_esc_and_window_close_never_confirm(app):
    QTimer.singleShot(0, lambda: QTest.keyClick(QApplication.activeModalWidget(), Qt.Key_Escape))
    assert not safe_dialogs.confirm_scrollable(None, "ลบ", "ยืนยัน", "รายละเอียด")
    QTimer.singleShot(0, lambda: QApplication.activeModalWidget().close())
    assert not safe_dialogs.confirm_scrollable(None, "ลบ", "ยืนยัน", "รายละเอียด")
    QTimer.singleShot(0, lambda: QApplication.activeModalWidget().cancel.click())
    assert not safe_dialogs.confirm_scrollable(None, "ลบ", "ยืนยัน", "รายละเอียด")
    QTimer.singleShot(0, lambda: QApplication.activeModalWidget().confirm.click())
    assert safe_dialogs.confirm_scrollable(None, "ลบ", "ยืนยัน", "รายละเอียด")
