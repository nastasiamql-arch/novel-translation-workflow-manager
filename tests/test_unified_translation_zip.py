import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtWidgets import QApplication
from novel_workflow.workspace_window import MainWindow
from test_release_36 import setup_profile


@pytest.mark.parametrize('global_zip,legacy_zip', [(True, False), (False, True)])
def test_global_zip_overrides_legacy_batch_mode(tmp_path, global_zip, legacy_zip):
    app = QApplication.instance() or QApplication([])
    repo, profile, _ = setup_profile(tmp_path)
    settings = repo.load_settings()
    settings.copy_files_as_zip = global_zip
    settings.translation_batch_profiles[profile.id] = {'zip': legacy_zip}
    repo.save_settings(settings)
    window = MainWindow(repo)
    try:
        index = next(i for i, item in enumerate(window.ps_list) if item.id == profile.id)
        window.select_profile(index)
        page = window.workspaces[profile.id].open_translation_batches()
        assert page.copy_mode.currentData() is global_zip
    finally:
        window.close()
        app.processEvents()


def test_two_way_sync_and_restart_preserves_other_preferences(tmp_path):
    from PySide6.QtWidgets import QCheckBox
    app = QApplication.instance() or QApplication([])
    repo, profile, _ = setup_profile(tmp_path)
    settings = repo.load_settings()
    settings.copy_files_as_zip = False
    settings.history_copy_as_zip = True
    settings.translation_batch_profiles[profile.id] = {'zip': True, 'size': 7}
    repo.save_settings(settings)
    window = MainWindow(repo)
    try:
        index = next(i for i, item in enumerate(window.ps_list) if item.id == profile.id)
        window.select_profile(index)
        batch = window.workspaces[profile.id].open_translation_batches()
        window.settings_dialog()
        check = window._settings_page_state['page'].findChild(QCheckBox, 'copyFilesAsZip')
        check.setChecked(True)
        assert batch.copy_mode.currentData() is True
        assert window.workspaces[profile.id].copy_step_button.text() == 'COPY ZIP'
        batch.copy_mode.setCurrentIndex(0)
        assert not check.isChecked()
        assert not window.settings.copy_files_as_zip
        assert window.workspaces[profile.id].copy_step_button.text() == 'COPY STEP'
        batch.copy_mode.setCurrentIndex(1)
        assert check.isChecked()
        assert repo.load_settings().copy_files_as_zip
        assert repo.load_settings().history_copy_as_zip
        assert batch.state['size'] == 7
    finally:
        window.close()
        app.processEvents()
    restored = MainWindow(repo)
    try:
        assert restored.settings.copy_files_as_zip
        assert restored.settings.history_copy_as_zip
    finally:
        restored.close()
        app.processEvents()


def test_batch_zip_clipboard_contains_only_selected_chapters(tmp_path):
    import zipfile
    from pathlib import Path
    from novel_workflow.models import NovelProfile
    from novel_workflow.storage import ProjectRepository
    from novel_workflow.translation_batch_page import TranslationBatchPage
    app = QApplication.instance() or QApplication([])
    repo = ProjectRepository(tmp_path / 'repo')
    profile = NovelProfile()
    folder = tmp_path / 'source'
    folder.mkdir()
    originals = {}
    for i in range(1, 5):
        data = f'第{i}章\nเนื้อหา {i}'.encode()
        (folder / f'{i:04d}.txt').write_bytes(data)
        originals[f'source/{i:04d}.txt'] = data
    page = TranslationBatchPage(repo, lambda: profile, object(),
        {'mode': 'folder', 'path': str(folder), 'size': 2, 'zip': True},
        lambda _state: None, lambda: None)
    try:
        assert page._load_worker.wait(20000)
        app.processEvents()
        page.copy_group(page._groups[0])
        if page._copy_worker is not None:
            assert page._copy_worker.wait(20000)
        app.processEvents()
        urls = app.clipboard().mimeData().urls()
        assert len(urls) == 1
        archive = Path(urls[0].toLocalFile())
        assert archive.suffix == '.zip' and archive.is_file()
        with zipfile.ZipFile(archive) as z:
            assert z.testzip() is None
            assert sorted(z.namelist()) == sorted(list(originals)[:2])
            assert all(z.read(name) == originals[name] for name in z.namelist())
        assert 'ZIP 1 ไฟล์' in page.summary.text()
    finally:
        if page._copy_worker and page._copy_worker.isRunning():
            page._copy_worker.wait(20000)
        page.close()
        app.processEvents()


def test_changing_mode_cancels_pending_copy_without_losing_selection(tmp_path, monkeypatch):
    from novel_workflow.models import NovelProfile
    from novel_workflow.storage import ProjectRepository
    from novel_workflow.translation_batch_page import TranslationBatchPage
    app = QApplication.instance() or QApplication([])
    repo = ProjectRepository(tmp_path / 'repo')
    profile = NovelProfile()
    folder = tmp_path / 'source'
    folder.mkdir()
    (folder / '0001.txt').write_text('第1章\n正文', encoding='utf-8')
    page = TranslationBatchPage(repo, lambda: profile, object(),
        {'mode': 'folder', 'path': str(folder), 'size': 1},
        lambda _state: None, lambda: None)
    try:
        assert page._load_worker.wait(20000)
        app.processEvents()
        worker = page._copy_worker
        page._invalidate_prepared()
        if worker:
            assert worker.wait(20000)
            app.processEvents()
        monkeypatch.setattr(page, '_schedule_prewarm', lambda *_: None)
        page.copy_group(page._groups[0])
        assert page._copy_pending is not None
        selected = page._selected_group
        page.set_copy_as_zip(True)
        assert page._copy_pending is None
        assert not page._ready_bundles
        assert page._selected_group == selected
        assert page.batch_workspace.copy.isEnabled()
        assert not page._history
    finally:
        page.close()
        app.processEvents()
