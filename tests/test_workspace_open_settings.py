import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from pathlib import Path
from PySide6.QtWidgets import QApplication, QCheckBox, QPushButton
from novel_workflow.models import NovelProfile, StepFile
from novel_workflow.storage import ProjectRepository
from novel_workflow.workspace_window import MainWindow
from test_release_36 import setup_profile


def app():
    return QApplication.instance() or QApplication([])


def select_novel(window, profile):
    index = next(i for i, value in enumerate(window.ps_list) if value.id == profile.id)
    window.select_profile(index)


def test_per_novel_working_tab_order_and_auto_open_restore(tmp_path):
    app()
    repo, first, _ = setup_profile(tmp_path)
    first.name = 'WESTPOINT'
    first_file = repo.profile_dir(first.id) / 'source' / 'WESTPOINT.txt'
    second_file = repo.profile_dir(first.id) / 'source' / 'WESTPOINTContext.md'
    first_file.write_text('prompt', encoding='utf-8')
    second_file.write_text('context', encoding='utf-8')
    first.working_files = [
        StepFile(label=second_file.name, path=str(second_file.relative_to(repo.profile_dir(first.id))), order=0),
        StepFile(label=first_file.name, path=str(first_file.relative_to(repo.profile_dir(first.id))), order=1),
    ]
    first.open_working_tabs_on_open = True
    repo.save_profile(first)

    second = NovelProfile(name='DRAGON')
    second_file_path = repo.profile_dir(second.id) / 'source' / 'DRAGON.txt'
    second_file_path.parent.mkdir(parents=True, exist_ok=True)
    second_file_path.write_text('dragon', encoding='utf-8')
    second.working_files = [StepFile(label=second_file_path.name, path='source/DRAGON.txt')]
    repo.save_profile(second)

    window = MainWindow(repo)
    select_novel(window, first)
    editor = window.workspaces[first.id].editor
    assert editor.open_paths() == [str(second_file.resolve()), str(first_file.resolve())]
    assert editor.tab_order() == [str(second_file.resolve()), str(first_file.resolve()), 'txt-export']
    window.close()

    restored = MainWindow(ProjectRepository(tmp_path))
    assert restored.workspaces[first.id].editor.open_paths() == [
        str(second_file.resolve()), str(first_file.resolve())
    ]
    assert all('DRAGON.txt' not in path for path in restored.workspaces[first.id].editor.open_paths())
    select_novel(restored, second)
    assert restored.workspaces[second.id].editor.open_paths() == []
    restored.close()


def test_working_files_can_be_reordered_per_novel_from_preferences(tmp_path):
    app()
    repo, profile, _ = setup_profile(tmp_path)
    profile.working_files = [
        StepFile(label='WESTPOINT.txt', path='source/WESTPOINT.txt', order=0),
        StepFile(label='WESTPOINTContext.md', path='source/WESTPOINTContext.md', order=1),
    ]
    repo.save_profile(profile)
    window = MainWindow(repo)
    select_novel(window, profile)
    window.settings_dialog()
    page = window._settings_page_state['page']
    page.select_category('Working Tabs')
    window.working_files.setCurrentRow(1)
    window.move_working_file(-1)
    assert [item.label for item in window.profile.working_files] == [
        'WESTPOINTContext.md', 'WESTPOINT.txt'
    ]
    persisted = next(value for value in repo.list_profiles() if value.id == profile.id)
    assert [item.label for item in persisted.working_files] == [
        'WESTPOINTContext.md', 'WESTPOINT.txt'
    ]
    assert page.findChild(QCheckBox, 'autoOpenWorkingTabs') is not None
    assert page.findChild(QPushButton, 'moveWorkingFileUp') is not None
    assert page.findChild(QPushButton, 'moveWorkingFileDown') is not None
    window.close()


def test_active_novel_can_close_without_deleting_profiles_or_reopening_previous(tmp_path):
    app()
    repo, first, _ = setup_profile(tmp_path)
    second = NovelProfile(name='DRAGON')
    repo.save_profile(second)
    window = MainWindow(repo)
    select_novel(window, first)
    select_novel(window, second)
    assert set(window.workspaces) == {second.id}
    window.workspaces[second.id].novel_header.close_button.click()
    assert second.id not in window._open_workspace_ids
    assert window.workspaces == {}
    assert second.id in window.settings.closed_workspace_profile_ids
    assert window.profile is None
    assert any(profile.id == second.id for profile in repo.list_profiles())
    window.close()

    restored = MainWindow(ProjectRepository(tmp_path))
    assert second.id not in restored._open_workspace_ids
    assert restored.workspaces == {}
    assert restored.main_pages.currentWidget() is restored.library_page
    assert any(profile.id == second.id for profile in restored.ps_list)
    restored.close()


def test_closing_last_novel_keeps_workspace_closed_after_restart(tmp_path):
    app()
    repo, profile, _ = setup_profile(tmp_path)
    window = MainWindow(repo)
    select_novel(window, profile)
    window._close_novel_tab(profile.id)
    assert window.profile is None
    assert profile.id in window.settings.closed_workspace_profile_ids
    window.close()

    restored = MainWindow(ProjectRepository(tmp_path))
    assert restored.profile is None
    assert restored.main_pages.currentWidget() is restored.library_page
    assert restored._open_workspace_ids == []
    restored.close()
