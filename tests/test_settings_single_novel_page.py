import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication, QListWidget, QPushButton
from novel_workflow.models import NovelProfile
from novel_workflow.storage import ProjectRepository
from novel_workflow.workspace_window import MainWindow
from test_release_36 import setup_profile


def app():
    return QApplication.instance() or QApplication([])


def test_novel_settings_are_one_page_and_profile_selection_stays_in_it(tmp_path):
    app()
    repo, first, _ = setup_profile(tmp_path)
    first.name = 'WESTPOINT'
    first.open_working_tabs_on_open = True
    repo.save_profile(first)
    second = NovelProfile(name='DRAGON')
    repo.save_profile(second)

    window = MainWindow(repo)
    window.settings_dialog()
    window.show()
    app().processEvents()
    page = window._settings_page_state['page']
    categories = page.findChild(QListWidget, 'preferencesCategory')
    assert [categories.item(i).text() for i in range(categories.count())] == [
        'General', 'Novel', 'Program Updates'
    ]
    assert categories.currentItem().text() == 'Novel'

    assert window.steps.isVisible()
    assert window.files.isVisible()
    assert window.working_files.isVisible()
    assert window.auto_open_working_tabs.isVisible()
    assert window.settings_main_folder.isVisible()
    assert page.findChild(QPushButton, 'openNovelTxtExport').isVisible()

    second_index = next(i for i, item in enumerate(window.ps_list) if item.id == second.id)
    window.profiles.selectionCommitted.emit(second_index)
    assert window.profile.id == second.id
    assert categories.currentItem().text() == 'Novel'
    assert window.auto_open_working_tabs.isVisible()
    assert not window.auto_open_working_tabs.isChecked()
    window.close()
