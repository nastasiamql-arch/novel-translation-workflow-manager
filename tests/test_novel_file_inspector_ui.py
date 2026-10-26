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
        assert list(nav.buttons) == ["today", "library", "workspace", "novel-inspector", "settings"]
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


@pytest.mark.parametrize("kind", ["folder", "zip"])
def test_actual_picker_does_not_use_removed_profile_widget(app, tmp_path, monkeypatch, kind):
    import zipfile
    from PySide6.QtWidgets import QFileDialog
    from novel_workflow.novel_file_inspector_page import NovelFileInspectorPage
    root = tmp_path / "files"
    root.mkdir()
    (root / "0001.txt").write_text("第1章 标题\n" + "中" * 1600, encoding="utf-8")
    archive = tmp_path / "files.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.write(root / "0001.txt", "0001.txt")
    page = NovelFileInspectorPage(ProjectRepository(tmp_path / "state"))
    try:
        if kind == "folder":
            monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *_a: str(root))
            page.choose_folder()
        else:
            monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_a: (str(archive), "ZIP (*.zip)"))
            page.choose_zip()
        assert page.worker.wait(15000)
        app.processEvents()
        assert page.result and page.result.summary()["total"] == 1
    finally:
        if page.worker and page.worker.isRunning():
            page.worker.cancel()
            page.worker.wait(15000)
        page.close()


def test_combined_txt_file_picker_readonly(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    from novel_workflow.novel_file_inspector_page import NovelFileInspectorPage
    source = tmp_path / "APOC.txt"
    original = "第一卷\n第1章 开始\n" + "甲" * 1600 + "\n第2章分割遗产\n" + "乙" * 1600
    source.write_text(original, encoding="utf-8")
    page = NovelFileInspectorPage(ProjectRepository(tmp_path / "state"))
    try:
        monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_a: (str(source), "TXT (*.txt)"))
        page.choose_combined()
        assert page.worker.wait(15000)
        app.processEvents()
        assert page.result.kind == "combined"
        assert page.model.rowCount() == 2
        assert all(not b.isEnabled() for b in page.repair_buttons)
        page.table.selectRow(1)
        app.processEvents()
        assert "第2章分割遗产" in page.text.toPlainText()
        assert source.read_text(encoding="utf-8") == original
    finally:
        if page.worker and page.worker.isRunning():
            page.worker.cancel()
            page.worker.wait(15000)
        page.close()
