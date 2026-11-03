import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFrame, QGroupBox, QListWidget, QPushButton, QScrollArea
from novel_workflow.models import LaunchTarget, NovelProfile
from novel_workflow.storage import ProjectRepository
from novel_workflow.workspace_window import MainWindow
from test_release_36 import setup_profile


def app():
    return QApplication.instance() or QApplication([])


def test_advanced_chapter_panel_state_survives_reopen_and_restart(tmp_path):
    app()
    repo, profile, _ = setup_profile(tmp_path)
    before = (profile.auto_review_enabled, profile.auto_chapter_number_mode)
    window = MainWindow(repo)
    window.settings_dialog()
    panel = window._settings_page_state['page'].findChild(QGroupBox, 'advancedChapterOptions')
    assert not panel.isChecked()
    panel.setChecked(True)
    window._restore_settings_management()
    window.settings_dialog()
    panel = window._settings_page_state['page'].findChild(QGroupBox, 'advancedChapterOptions')
    assert panel.isChecked()
    window.close()
    window = MainWindow(ProjectRepository(repo.root))
    window.settings_dialog()
    panel = window._settings_page_state['page'].findChild(QGroupBox, 'advancedChapterOptions')
    assert panel.isChecked()
    panel.setChecked(False)
    assert not repo.load_settings().advanced_chapter_options_expanded
    saved = repo.load_profile(profile.id)
    assert (saved.auto_review_enabled, saved.auto_chapter_number_mode) == before
    window.close()


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
    sidebar = page.findChild(QFrame, 'preferencesSidebar')
    assert [categories.item(i).text() for i in range(categories.count())] == [
        'ข้อมูลนิยาย', 'ไฟล์และโฟลเดอร์', 'ขั้นตอนการแปล', 'แท็บทำงาน',
        'ส่งออก TXT', 'ทั่วไป', 'อัปเดตโปรแกรม'
    ]
    assert categories.currentItem().text() == 'ข้อมูลนิยาย'
    assert sidebar is not None
    assert sidebar.parentWidget() is page
    parent = sidebar.parentWidget()
    while parent is not page:
        assert not isinstance(parent, QScrollArea)
        parent = parent.parentWidget()
    assert window.profiles.wordWrap()
    assert window.profiles.textElideMode() == Qt.ElideNone
    assert window.profiles.iconSize().width() == 52
    assert window.profiles.viewport().height() > 0
    assert window.profiles.minimumHeight() == 0
    first_row = next(i for i, profile in enumerate(window.ps_list) if profile.id == first.id)
    assert window.profiles.item(first_row).text() == first.name
    assert window.profiles.item(first_row).sizeHint().height() >= 76
    assert window.profiles.viewport().height() > 0
    window.profiles.setCurrentRow(first_row)
    QTest.keyClick(window.profiles, Qt.Key_Down)
    assert window.profile.id == second.id
    window.profiles.selectionCommitted.emit(first_row)
    app().processEvents()
    assert window.settings_launch_targets.wordWrap()
    assert window.settings_launch_targets.textElideMode() == Qt.ElideNone
    target_row = window.settings_launch_targets.item(0)
    assert target_row.sizeHint().height() >= 44
    assert window.settings_launch_targets.viewport().height() >= 250
    assert target_row.toolTip() == first.launch_targets[0].target

    categories.setCurrentRow(1)
    assert window.settings_main_folder.isVisible()
    categories.setCurrentRow(2)
    assert window.steps.isVisible() and window.files.isVisible()
    categories.setCurrentRow(3)
    assert window.working_files.isVisible() and window.auto_open_working_tabs.isVisible()
    categories.setCurrentRow(4)
    assert page.findChild(QPushButton, 'openNovelTxtExport').isVisible()
    categories.setCurrentRow(0)

    second_index = next(i for i, item in enumerate(window.ps_list) if item.id == second.id)
    window.profiles.selectionCommitted.emit(second_index)
    assert window.profile.id == second.id
    assert categories.currentItem().text() == 'ข้อมูลนิยาย'
    categories.setCurrentRow(3)
    assert window.auto_open_working_tabs.isVisible()
    assert not window.auto_open_working_tabs.isChecked()
    window.close()
