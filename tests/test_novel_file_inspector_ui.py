"""Standalone inspector navigation must leave workflow untouched."""
from __future__ import annotations
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtWidgets import QApplication
from novel_workflow.storage import ProjectRepository
from novel_workflow.shell_components import NavigationSidebar
from novel_workflow.workspace_window import MainWindow

@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])

def test_navigation_order_and_inspector_route(app):
    nav = NavigationSidebar(False)
    try:
        assert list(nav.buttons) == ["library", "workspace", "progress", "groups", "novel-inspector", "settings"]
        out = []
        nav.selected.connect(out.append)
        nav.buttons["novel-inspector"].click()
        assert out == ["novel-inspector"]
    finally:
        nav.close()

def test_standalone_page_no_profile_created(app, tmp_path):
    repo = ProjectRepository(tmp_path)
    window = MainWindow(repo)
    try:
        window.navigate("novel-inspector")
        page = window._utility_pages["novel-inspector"]
        assert page.objectName() == "novelFileInspectorPage"
        assert window.main_pages.currentWidget() == window.utility_page
        assert window.utility_stack.currentWidget() == page
        assert window.navigation.buttons["novel-inspector"].isChecked()
        assert page.store.root == tmp_path / "novel_file_inspector"
        window.return_from_utility_page()
        assert window.main_pages.currentWidget() == window.library_page
        assert not repo.list_profiles()
    finally:
        window._automatic_update_timer.stop()
        window.close()


def test_inspector_single_screen_and_direct_folder_scan(app, tmp_path, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QSplitter
    from novel_workflow.novel_file_inspector_page import NovelFileInspectorPage
    repo = ProjectRepository(tmp_path / "state")
    page = NovelFileInspectorPage(repo)
    root = tmp_path / "chapters"
    root.mkdir()
    (root / "0001.txt").write_text("第2章 标题\n" + "中" * 1600, encoding="utf-8")
    try:
        assert page.findChild(QSplitter).orientation() == Qt.Horizontal
        assert page.table.model().columnCount() == 4
        assert not hasattr(page, "profile_combo")
        assert not hasattr(page, "tabs")
        page.set_source(str(root), "folder")
        assert page.worker is not None
        assert page.worker.wait(15000)
        app.processEvents()
        assert page.result is not None
        assert page.result.summary()["heading_mismatch"] == 1
        assert page.summary.text().find("หัวบทไม่ตรง") >= 0
        assert page.renumber_dialog.isHidden()
        assert page.history_dialog.isHidden()
    finally:
        if page.worker and page.worker.isRunning():
            page.worker.cancel()
            page.worker.wait(15000)
        page.close()


def test_scan_progress_has_clear_status_outside_bar(app, tmp_path):
    from novel_workflow.novel_file_inspector_page import NovelFileInspectorPage
    page = NovelFileInspectorPage(ProjectRepository(tmp_path))
    try:
        assert page.progress.objectName() == "inspectorScanProgress"
        assert not page.progress.isTextVisible()
        page.progress_scan(53, 100)
        assert page.progress.value() == 53
        assert "53/100" in page.progress_status.text()
        assert "53%" in page.progress_status.text()
        page.progress_scan(1250, 2500)
        assert "1,250/2,500" in page.progress_status.text()
        assert "50%" in page.progress_status.text()
    finally:
        page.close()
