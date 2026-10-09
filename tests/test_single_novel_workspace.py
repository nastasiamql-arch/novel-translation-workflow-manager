import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QTabBar
from novel_workflow.models import NovelProfile
from novel_workflow.storage import ProjectRepository
from novel_workflow.workspace_window import MainWindow
from test_release_36 import app, setup_profile


@pytest.fixture(autouse=True)
def dispose_windows():
    app()
    existing = set(QApplication.topLevelWidgets())
    yield
    for widget in set(QApplication.topLevelWidgets()) - existing:
        for timer in widget.findChildren(QTimer):
            timer.stop()
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def select(window, profile):
    window.select_profile(next(i for i, p in enumerate(window.ps_list) if p.id == profile.id))


def test_switch_replaces_workspace_preserving_files_draft_cursor_and_library(tmp_path):
    repo, first, _ = setup_profile(tmp_path)
    second = NovelProfile(name='Second')
    repo.save_profile(second)
    path = repo.profile_dir(first.id) / 'source/Novel.txt'
    path.write_text('original', encoding='utf-8')
    window = MainWindow(repo); select(window, first)
    tabs = window.workspaces[first.id].editor
    editor = tabs.open_file(path); editor.setPlainText('edited ไทย 中文')
    cursor = editor.textCursor(); cursor.setPosition(3); editor.setTextCursor(cursor)
    tabs.export_tab.editor.setPlainText('draft ไทย')
    tabs.tabs.setCurrentWidget(editor)
    select(window, second)
    assert set(window.workspaces) == {second.id}
    assert window._open_workspace_ids == [second.id]
    assert window.workspace_stack.count() == 2  # empty page + one novel
    assert not window.findChildren(QTabBar, 'novelTabBar')
    assert path.read_text(encoding='utf-8') == 'edited ไทย 中文'
    assert {p.id for p in repo.list_profiles()} == {first.id, second.id}
    select(window, first)
    restored = window.workspaces[first.id].editor
    assert restored._current_editor().toPlainText() == 'edited ไทย 中文'
    assert restored._current_editor().textCursor().position() == 3
    assert restored.export_tab.editor.toPlainText() == 'draft ไทย'
    assert set(window.workspaces) == {first.id}


def test_failed_save_keeps_current_workspace_and_unsaved_data(tmp_path, monkeypatch):
    repo, first, _ = setup_profile(tmp_path)
    second = NovelProfile(name='Second'); repo.save_profile(second)
    window = MainWindow(repo); select(window, first)
    workspace = window.workspaces[first.id]
    workspace.editor.export_tab.editor.setPlainText('unsaved ไทย')
    monkeypatch.setattr(workspace.editor, 'save_all', lambda **kwargs: False)
    select(window, second)
    assert window.profile.id == first.id
    assert set(window.workspaces) == {first.id}
    assert workspace.editor.export_tab.editor.toPlainText() == 'unsaved ไทย'


def test_old_multiple_novel_session_restores_only_last_active(tmp_path):
    repo, first, _ = setup_profile(tmp_path)
    second = NovelProfile(name='Second'); repo.save_profile(second)
    settings = repo.load_settings()
    settings.workspace_open_profile_ids = [first.id, second.id]
    settings.last_profile_id = second.id
    first_file = repo.profile_dir(first.id) / 'source/Novel.txt'
    first_file.write_text('first saved file', encoding='utf-8')
    settings.editor_tabs[first.id] = [str(first_file)]
    repo.save_settings(settings)
    window = MainWindow(repo)
    assert set(window.workspaces) == {second.id}
    assert window._open_workspace_ids == [second.id]
    window.close()
    restored = MainWindow(ProjectRepository(tmp_path))
    assert set(restored.workspaces) == {second.id}
    select(restored, first)
    assert str(first_file.resolve()) in restored.workspaces[first.id].editor.open_paths()


def test_active_header_uses_small_current_cover_and_missing_cover_fallback(tmp_path):
    repo, first, _ = setup_profile(tmp_path)
    cover = repo.profile_dir(first.id) / 'cover.png'
    picture = QImage(100, 140, QImage.Format_RGB32); picture.fill(0xFFCC3355)
    assert picture.save(str(cover))
    first.cover_image_path = 'cover.png'; repo.save_profile(first)
    second = NovelProfile(name='No cover', cover_image_path='missing.png'); repo.save_profile(second)
    window = MainWindow(repo); select(window, first)
    header = window.workspaces[first.id].novel_header
    assert header.cover.property('coverPath') == str(cover.resolve())
    assert not header.cover.pixmap().isNull()
    assert header.cover.width() <= 48 and header.cover.height() <= 64
    assert header.title.toolTip() == first.name
    select(window, second)
    header = window.workspaces[second.id].novel_header
    assert header.title.toolTip() == second.name
    assert not header.cover.property('coverPath')
