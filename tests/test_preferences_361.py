import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QListWidget, QCheckBox, QLineEdit, QPushButton
from test_release_36 import app, setup_profile
from novel_workflow.workspace_window import MainWindow


def test_preferences_sidebar_and_consolidated_general(tmp_path):
    app()
    repo, profile, _ = setup_profile(tmp_path)
    window = MainWindow(repo)
    window.settings_dialog()
    page = window._settings_page_state['page']
    categories = page.findChild(QListWidget, 'preferencesCategory')
    assert categories is not None
    assert [categories.item(i).text() for i in range(categories.count())] == [
        'General', 'Novel', 'Program Updates'
    ]
    assert categories.currentRow() == 1
    assert not any(b.text() == 'ตั้งค่าโปรแกรม' for b in page.findChildren(QPushButton))
    separator = page.findChild(QLineEdit, 'assemblySeparator')
    categories.setCurrentRow(0)
    separator.setText('--- {FILE_NAME} ---')
    separator.editingFinished.emit()
    for name in ('show_filename_heading', 'confirm_before_deleting', 'open_last_profile'):
        checkbox = page.findChild(QCheckBox, name)
        assert checkbox is not None
        checkbox.setChecked(not checkbox.isChecked())
        assert getattr(repo.load_settings(), name) == checkbox.isChecked()
    assert repo.load_settings().separator == '--- {FILE_NAME} ---'
    categories.setCurrentRow(2)
    assert window.files.isHidden() or not window.files.isVisibleTo(page)
    assert window.steps.isHidden() or not window.steps.isVisibleTo(page)
    categories.setCurrentRow(1)
    assert window.files.isVisibleTo(page)
    assert window.steps.isVisibleTo(page)
    assert window.working_files.isVisibleTo(page)
    assert page.findChild(QCheckBox, 'autoOpenWorkingTabs').isVisibleTo(page)
    window.program_settings_dialog()
    assert window._settings_page_state['page'] is page
    assert categories.currentRow() == 0
    window.close()
