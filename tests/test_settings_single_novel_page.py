import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QListWidget, QPushButton
from novel_workflow.models import LaunchTarget, NovelProfile
from novel_workflow.storage import ProjectRepository
from novel_workflow.workspace_window import MainWindow
from test_release_36 import setup_profile


def app():
    return QApplication.instance() or QApplication([])


def test_novel_settings_are_one_page_and_profile_selection_stays_in_it(tmp_path):
    app()
    repo, first, _ = setup_profile(tmp_path)
    first.name = 'ย้อนเวลาสู่ 1985 กลับมาเปลี่ยนเส้นทางของผู้แปลนิยาย'
    first.open_working_tabs_on_open = True
    first.launch_targets = [LaunchTarget(
        label='WESTPOINTGlossary.txt', kind='file',
        target='E:/WebNovel/WESTPOINT/Reference/WESTPOINTGlossary.txt',
    )]
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
    assert window.profiles.wordWrap()
    assert window.profiles.textElideMode() == Qt.ElideNone
    assert window.profiles.iconSize().width() >= 64
    first_row = next(i for i, profile in enumerate(window.ps_list) if profile.id == first.id)
    assert window.profiles.item(first_row).text() == first.name
    assert window.profiles.item(first_row).sizeHint().height() >= 100
    window.profiles.selectionCommitted.emit(first_row)
    app().processEvents()
    assert window.settings_launch_targets.wordWrap()
    assert window.settings_launch_targets.textElideMode() == Qt.ElideNone
    target_row = window.settings_launch_targets.item(0)
    assert target_row.sizeHint().height() >= 56
    assert target_row.toolTip() == first.launch_targets[0].target

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
