"""Workspace sidebar navigation and workflow step regression tests."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QPushButton, QComboBox

from novel_workflow.models import WorkflowStep, StepFile
from novel_workflow.storage import ProjectRepository
from novel_workflow.workspace_window import MainWindow
from test_release_36 import app, setup_profile


def _open(tmp_path):
    # Keep the QApplication wrapper alive for this independent pytest group.
    # Without it Windows can abort in native Qt before any assertion runs.
    qt_app = app()
    repo, profile, _ = setup_profile(tmp_path)
    window = MainWindow(repo)
    window._test_qt_app = qt_app
    window.select_profile(next(i for i, item in enumerate(window.ps_list) if item.id == profile.id))
    return repo, profile, window, window.workspaces[profile.id]


def test_sidebar_has_three_tools_and_one_stage_dropdown(tmp_path):
    repo, profile, window, workspace = _open(tmp_path)
    try:
        tools = (workspace.editor_shortcut, workspace.txt_vocabulary_shortcut,
                 workspace.translation_batch_shortcut)
        assert [button.text() for button in tools] == ["Editor", "หาศัพท์", "แปล"]
        assert workspace.sidebar_normal.parent() is workspace.sidebar
        assert all(button.parent() is workspace.sidebar_normal for button in tools)
        assert [workspace.sidebar_normal.layout().indexOf(button) for button in tools] == sorted(
            workspace.sidebar_normal.layout().indexOf(button) for button in tools
        )
        assert workspace.sidebar_normal.layout().indexOf(workspace.step_selector) > workspace.sidebar_normal.layout().indexOf(tools[-1])
        assert workspace.sidebar_normal.layout().indexOf(workspace.file_search) > workspace.sidebar_normal.layout().indexOf(workspace.step_selector)
        assert workspace.sidebar_normal.layout().indexOf(workspace.files) > workspace.sidebar_normal.layout().indexOf(workspace.file_search)
        assert workspace.steps.count() == len(profile.workflow.steps)
        assert workspace.sidebar_normal.layout().indexOf(workspace.steps) == -1
        assert not any(button.text() == "บันทึกไว้รอตรวจ"
                       for button in workspace.sidebar.findChildren(QPushButton))
        assert workspace.history_button.text() == "Novel Polish"
        assert len(workspace.sidebar.findChildren(QComboBox, "workspaceStepSelector")) == 1
    finally:
        window.close()


def test_dropdown_selection_uses_ids_and_never_copies(tmp_path, monkeypatch):
    repo, profile, window, workspace = _open(tmp_path)
    try:
        custom = WorkflowStep(name="ขั้นตอนกำหนดเอง", files=[StepFile(label="Custom")])
        window.profile.workflow.steps.append(custom)
        window.refresh_steps()
        assert workspace.step_selector.findData(custom.id) >= 0
        copies = []
        monkeypatch.setattr(window, "copy_step", lambda *a, **kw: copies.append(window.step().id))
        workspace.step_selector.setCurrentIndex(workspace.step_selector.findData(custom.id))
        assert window.step().id == custom.id
        assert workspace.step_index == 2
        assert workspace.files.item(0).text() == "Custom"
        assert not copies
        window.copy_named_stage(profile.id, 2)
        assert copies == [custom.id]
        assert window.settings.workspace_step_indices[profile.id] == 2
        window._persist_workspace_session()
        assert repo.load_settings().workspace_step_indices[profile.id] == 2
    finally:
        window.close()


def test_editor_navigation_reuses_tabs_without_copy_or_batch_reset(tmp_path, monkeypatch):
    repo, profile, window, workspace = _open(tmp_path)
    try:
        existing_editor = workspace.editor
        current_tab = existing_editor.tabs.currentWidget()
        seen = []
        monkeypatch.setattr(window, "copy_step", lambda *a, **kw: seen.append(True))
        workspace.editor_shortcut.click()
        assert workspace.editor_content_stack.currentWidget() is existing_editor
        window.open_txt_vocabulary(profile.id)
        assert workspace.editor_content_stack.currentWidget() is workspace.txt_vocabulary_page
        workspace.editor_shortcut.click()
        assert workspace.editor_content_stack.currentWidget() is existing_editor
        assert existing_editor.tabs.currentWidget() is current_tab
        assert workspace.editor is existing_editor
        assert not seen
    finally:
        window.close()


def test_vocabulary_step_remains_copyable_in_dropdown(tmp_path, monkeypatch):
    repo, profile, window, workspace = _open(tmp_path)
    try:
        assert profile.vocabulary_step
        step_id = profile.vocabulary_step.id
        copied = []
        monkeypatch.setattr(window, "copy_step", lambda *a, **kw: copied.append(window.step().id))
        workspace.step_selector.setCurrentIndex(workspace.step_selector.findData(step_id))
        assert workspace.vocabulary_mode and window.step().id == step_id
        assert not copied
        window.copy_named_stage(profile.id, "vocabulary")
        assert copied == [step_id]
        workspace.step_selector.setCurrentIndex(workspace.step_selector.findData(profile.workflow.steps[0].id))
        assert not workspace.vocabulary_mode
    finally:
        window.close()
