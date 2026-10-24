"""Retired AI Workspace must not affect existing desktop workflows."""
from __future__ import annotations

import importlib.util
from pathlib import Path

from PySide6.QtWidgets import QApplication

from novel_workflow.models import NovelProfile
from novel_workflow.storage import ProjectRepository
from novel_workflow.shell_components import NavigationSidebar
from novel_workflow.workspace_window import MainWindow


ROOT = Path(__file__).resolve().parents[1]


def test_retired_feature_is_not_installed_or_navigable():
    assert importlib.util.find_spec("novel_workflow.ai_workspace") is None
    assert not (ROOT / "src/novel_workflow/ai_workspace").exists()
    app = QApplication.instance() or QApplication([])
    sidebar = NavigationSidebar(False)
    try:
        assert list(sidebar.buttons) == [
            "today", "library", "workspace", "novel-inspector", "settings",
        ]
        sidebar.set_collapsed(True)
        assert sidebar.collapsed
        sidebar.set_collapsed(False)
        assert not sidebar.collapsed
    finally:
        sidebar.close()


def test_legacy_navigation_key_has_safe_fallback(tmp_path):
    app = QApplication.instance() or QApplication([])
    repo = ProjectRepository(tmp_path)
    settings = repo.load_settings()
    from datetime import date
    settings.last_update_check_date = date.today().isoformat()
    repo.save_settings(settings)
    window = MainWindow(repo)
    try:
        before = window.main_pages.currentWidget()
        window.navigate("ai-workspace")  # Historical key is intentionally unhandled.
        assert window.main_pages.currentWidget() is before
        assert "ai-workspace" not in window._utility_pages
        window.main_pages.setCurrentWidget(window.utility_page)
        window._active_utility_page = "ai-workspace"
        window._sync_navigation()
        assert window.navigation.buttons["workspace"].isChecked()
    finally:
        window._automatic_update_timer.stop()
        window.main_pages.setCurrentWidget(window.library_page)
        window._active_utility_page = None
        window.close()


def test_obsolete_browser_payloads_are_not_packaged():
    assert "playwright" not in (ROOT / "pyproject.toml").read_text(encoding="utf-8").lower()
    assert "playwright" not in (ROOT / "NovelWorkflow.spec").read_text(encoding="utf-8").lower()
    assert "playwright" not in (ROOT / "build_windows.ps1").read_text(encoding="utf-8").lower()
    assert "windows_standard_chrome" not in (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert (ROOT / "src/novel_workflow/clipboard_files.py").is_file()
    for module in ("translation_batches", "translation_batch_clipboard", "vocabulary_batches", "export_service", "updater"):
        assert (ROOT / "src/novel_workflow" / (module + ".py")).is_file()


def test_legacy_jobs_are_preserved_when_loading_regular_profiles(tmp_path):
    repo = ProjectRepository(tmp_path)
    profile = NovelProfile(name="Original novel")
    repo.save_profile(profile)
    jobs = repo.profile_dir(profile.id) / "ai_workspace_jobs.json"
    payload = b'{"jobs":[{"unexported":"do not delete"}]}'
    jobs.write_bytes(payload)
    assert repo.list_profiles()[0].name == profile.name
    assert jobs.read_bytes() == payload
    repo.save_profile(repo.list_profiles()[0])
    assert jobs.read_bytes() == payload
