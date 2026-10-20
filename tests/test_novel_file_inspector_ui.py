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
