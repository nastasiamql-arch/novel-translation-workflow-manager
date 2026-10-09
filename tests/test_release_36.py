"""Regression coverage for the 3.6 content and workflow contract."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import hashlib
import zipfile
from datetime import date
from pathlib import Path
import pytest
from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionSpinBox, QMessageBox
from novel_workflow.models import NovelProfile, StepFile, WorkflowStep
from novel_workflow.storage import ProjectRepository
from novel_workflow.services import AssemblyService
from novel_workflow.workflow_archive import create_workflow_archive
from novel_workflow.workspace_editor import EditorTabs
from novel_workflow.translation_progress import latest_context_chapter
from test_txt_export import panel


def app():
    return QApplication.instance() or QApplication([])


def setup_profile(tmp_path):
    repo = ProjectRepository(tmp_path)
    profile = NovelProfile()
    repo.save_profile(profile)
    settings = repo.load_settings()
    settings.last_update_check_date = date.today().isoformat()
    repo.save_settings(settings)
    return repo, profile, AssemblyService(repo)


def test_zip_binary_unicode_nested_disabled_duplicate_and_multiple_steps(tmp_path):
    repo, p, assembler = setup_profile(tmp_path)
    folder = repo.profile_dir(p.id)
    file = folder / 'reference' / '中文 日本 ไทย.bin'
    raw = bytes(range(256)) * 8192
    file.write_bytes(raw)
    steps = [WorkflowStep(name='แปล', files=[StepFile(path='reference', enabled=False),
             StepFile(path='reference/' + file.name)]),
             WorkflowStep(name='ตรวจคำแปล', files=[StepFile(path='reference/' + file.name)])]
    before = hashlib.sha256(file.read_bytes()).digest()
    archive = create_workflow_archive(repo, assembler, p, steps)
    with zipfile.ZipFile(archive) as result:
        assert result.namelist() == ['01_แปล/reference/' + file.name,
                                    '02_ตรวจคำแปล/reference/' + file.name]
        assert all(result.read(name) == raw for name in result.namelist())
        assert result.testzip() is None
    assert hashlib.sha256(file.read_bytes()).digest() == before
    del repo
    assert archive.exists()  # Clipboard remains valid after the service/app exits.


@pytest.mark.parametrize('path', ['missing.txt', '../escape.txt', ''])
def test_zip_rejects_missing_or_unsafe_paths_without_publishing(tmp_path, path):
    repo, p, assembler = setup_profile(tmp_path)
    with pytest.raises((FileNotFoundError, ValueError)):
        create_workflow_archive(repo, assembler, p, [WorkflowStep(files=[StepFile(path=path)])])
    assert not list(tmp_path.rglob('Workflow-*.zip'))


def test_empty_steps_fail(tmp_path):
    repo, p, assembler = setup_profile(tmp_path)
    with pytest.raises(ValueError, match='Empty step'):
        create_workflow_archive(repo, assembler, p, [WorkflowStep()])


def test_recovery_order_is_stable_when_windows_clock_repeats(tmp_path, monkeypatch):
    from novel_workflow import recovery
    monkeypatch.setattr(recovery.time, 'time_ns', lambda: 1000000000000000000)
    path = tmp_path / 'Context.md'
    for index in range(recovery.BACKUP_LIMIT):
        path.write_text(f'Chapter {index + 1}', encoding='utf-8')
        recovery.backup_file(path)
    oldest = sorted((tmp_path / '.palantir-recovery').glob('*.bak'))[0]
    path.write_text('wrong', encoding='utf-8')
    recovery.restore_backup(path, oldest)
    assert path.read_text(encoding='utf-8') == 'Chapter 1'


def test_downloader_worker_does_not_overwrite_draft_and_workspace_preserves_binding(tmp_path):
    from test_downloader_service import setup
    repo, stale, source, service = setup(tmp_path)
    current = repo.list_profiles()[0]
    current.txt_export_draft = 'ไทย 中文 draft'
    current.verified_goal_count = 12
    repo.save_profile(current)
    service.download_range(stale, 1, 1)
    latest = repo.list_profiles()[0]
    assert latest.txt_export_draft == 'ไทย 中文 draft'
    assert latest.verified_goal_count == 12
    assert latest.source_binding.last_downloaded_chapter == 1
    current.name = 'Renamed during download'
    repo.save_profile(current)
    assert repo.list_profiles()[0].source_binding.last_downloaded_chapter == 1


def test_vocabulary_session_is_restored_without_translation_accounting(tmp_path):
    app()
    from novel_workflow.workspace_window import MainWindow
    repo, p, assembler = setup_profile(tmp_path)
    window = MainWindow(repo)
    window.refresh_profiles(p.id)
    window.set_vocabulary_mode(p.id, True)
    window.close()
    restored = MainWindow(ProjectRepository(tmp_path))
    assert restored.workspaces[p.id].vocabulary_mode
    assert restored.profile.verified_goal_count == 0
    assert restored.profile.translation_daily_activity == {}
    restored.close()


def test_novel_tabs_switch_same_named_files_and_restore_independent_sessions(tmp_path):
    app()
    from novel_workflow.workspace_window import MainWindow
    repo, p, assembler = setup_profile(tmp_path)
    p.name = 'WESTPOINT'
    q = NovelProfile(name='DRAGON')
    repo.save_profile(p)
    repo.save_profile(q)
    window = MainWindow(repo)
    for profile, value in ((p, 'A ไทย 中文'), (q, 'B 日本 English')):
        path = repo.profile_dir(profile.id) / 'source' / 'Novel.txt'
        path.write_text(value, encoding='utf-8')
        window.select_profile(next(i for i, item in enumerate(window.ps_list) if item.id == profile.id))
        window.workspaces[profile.id].editor.open_file(path)
    bar = window.workspaces[q.id].novel_tabs
    bar.setCurrentIndex(next(i for i in range(bar.count()) if bar.tabData(i) == p.id))
    assert window.profile.id == p.id
    assert window.workspaces[p.id].editor._current_editor().toPlainText() == 'A ไทย 中文'
    window.close()
    restored = MainWindow(ProjectRepository(tmp_path))
    bar = restored.workspaces[p.id].novel_tabs
    assert {bar.tabData(i) for i in range(bar.count())} == {p.id, q.id}
    bar.setCurrentIndex(next(i for i in range(bar.count()) if bar.tabData(i) == q.id))
    assert restored.workspaces[q.id].editor._current_editor().toPlainText() == 'B 日本 English'
    restored.close()


def test_settings_categories_keep_management_actions_accessible(tmp_path):
    app()
    from PySide6.QtWidgets import QListWidget, QCheckBox
    from novel_workflow.workspace_window import MainWindow
    repo, p, assembler = setup_profile(tmp_path)
    window = MainWindow(repo)
    window.settings_dialog()
    page = window._settings_page_state['page']
    categories = page.findChild(QListWidget, 'preferencesCategory')
    assert categories.count() == 3
    page.select_category('General')
    checkbox = page.findChild(QCheckBox, 'copyFilesAsZip')
    checkbox.setChecked(True)
    assert repo.load_settings().copy_files_as_zip
    page.select_category('Working Tabs')
    assert not window.working_files.isHidden()
    page.select_category('Workflow Files')
    assert not window.files.isHidden()
    window.return_from_utility_page()
    window.close()


def test_delayed_update_is_cancelled_when_window_closes(tmp_path):
    app()
    from novel_workflow.workspace_window import MainWindow
    repo, p, assembler = setup_profile(tmp_path)
    settings = repo.load_settings()
    settings.last_update_check_date = None
    repo.save_settings(settings)
    window = MainWindow(repo)
    assert window._automatic_update_timer.isActive()
    window.close()
    assert not window._automatic_update_timer.isActive()


def test_zip_rejects_case_insensitive_collision(tmp_path):
    repo, p, assembler = setup_profile(tmp_path)
    inside = repo.profile_dir(p.id) / 'notes' / 'same.txt'
    outside = tmp_path / 'external' / 'notes' / 'same.txt'
    outside.parent.mkdir(parents=True)
    inside.write_text('A')
    outside.write_text('B')
    step = WorkflowStep(files=[StepFile(path='notes/same.txt'),
        StepFile(reference_type='external_file', path=str(outside.parent))])
    with pytest.raises(ValueError, match='collision'):
        create_workflow_archive(repo, assembler, p, [step])


def test_dynamic_zero_padded_source_and_profile_isolation(tmp_path):
    repo, p, assembler = setup_profile(tmp_path)
    q = NovelProfile()
    repo.save_profile(q)
    for profile, raw in ((p, b'A'), (q, b'B')):
        (repo.profile_dir(profile.id) / 'source' / '0001 中文.txt').write_bytes(raw)
    step = WorkflowStep(files=[StepFile(reference_type='dynamic', dynamic_reference='CURRENT_SOURCE_CHAPTER')])
    for profile, raw in ((p, b'A'), (q, b'B')):
        with zipfile.ZipFile(create_workflow_archive(repo, assembler, profile, [step])) as result:
            assert result.read(result.namelist()[0]) == raw


@pytest.mark.parametrize('enabled', [False, True])
def test_existing_copy_step_clipboard_and_zip_setting(tmp_path, enabled):
    app()
    from novel_workflow.workspace_window import MainWindow
    repo, p, assembler = setup_profile(tmp_path)
    file = repo.profile_dir(p.id) / 'source' / 'same.txt'
    file.write_text('ไทย Chinese 中文', encoding='utf-8')
    p.workflow.steps[0].files = [StepFile(path='source/same.txt', enabled=not enabled)]
    repo.save_profile(p)
    settings = repo.load_settings()
    assert settings.copy_files_as_zip is False
    settings.copy_files_as_zip = enabled
    repo.save_settings(settings)
    assert repo.load_settings().copy_files_as_zip is enabled
    window = MainWindow(repo)
    window.refresh_profiles(p.id)
    window.copy_step(advance=False)
    urls = QApplication.clipboard().mimeData().urls()
    assert len(urls) == 1 and urls[0].isLocalFile()
    copied = Path(urls[0].toLocalFile())
    assert copied.exists()
    assert copied.suffix == ('.zip' if enabled else '.txt')
    export = window.workspaces[p.id].editor.export_tab
    export.editor.setPlainText('ไทย\n\n中文\n日本\nEnglish')
    export.copy_text()
    assert QApplication.clipboard().text() == export.editor.toPlainText()
    window.close()


def test_autosave_bom_crlf_unicode_undo_and_external_conflict(tmp_path):
    app()
    path = tmp_path / '中文.txt'
    raw = '\ufeffไทย\r\n\r\n中文 日本 English\r\n'.encode('utf-8')
    path.write_bytes(raw)
    tabs = EditorTabs()
    editor = tabs.open_file(path)
    assert tabs.save_editor(editor, quiet=True)
    assert path.read_bytes() == raw
    editor.moveCursor(editor.textCursor().MoveOperation.End)
    editor.insertPlainText('added')
    QTest.qWait(1100)
    assert path.read_bytes() == raw + b'added'
    assert editor.document().isUndoAvailable()
    path.write_text('external', encoding='utf-8')
    editor.insertPlainText('local')
    assert not tabs.save_editor(editor, quiet=True)
    assert path.read_text() == 'external'
    assert editor.property('saveState') == 'ไฟล์ถูกแก้ไขจากภายนอก'
    assert tabs.dirty_count() == 1
    editor.autosave_timer.stop()


def test_context_final_progress_ignores_earlier_example_and_later_history():
    text = 'Example\nChapter 999\n# Chapter Progress\nบทที่ 157–159\n# History\nChapter 900'
    assert latest_context_chapter(text) == 159
    assert latest_context_chapter('第125章') == 125
    assert latest_context_chapter('Chapter 125') == 125
    assert latest_context_chapter('Example\nChapter 999\nChapter Progress: Chapter 125') == 125
    assert latest_context_chapter('# Chapter Progress\n## บทที่ 125\n# History\nChapter 999') == 125


def test_control_borders_and_placeholders_meet_contrast():
    from test_theme import _contrast
    from novel_workflow.theme import theme_colors, qt_palette
    from PySide6.QtGui import QPalette
    for appearance in ('Light', 'Dark'):
        colors = theme_colors(appearance)
        for background in ('app', 'input', 'surface2'):
            assert _contrast(colors['control_border'], colors[background]) >= 3
        assert _contrast(colors['muted'], colors['input']) >= 4.5
        assert qt_palette(appearance).color(QPalette.PlaceholderText).name().upper() == colors['muted']


def test_spinbox_actual_up_down_hitboxes_typed_value_and_limits(tmp_path):
    app()
    export = panel(tmp_path)
    export.show()
    box = export.current
    box.setValue(50)
    app().processEvents()
    option = QStyleOptionSpinBox()
    box.initStyleOption(option)
    up = box.style().subControlRect(QStyle.CC_SpinBox, option, QStyle.SC_SpinBoxUp, box)
    down = box.style().subControlRect(QStyle.CC_SpinBox, option, QStyle.SC_SpinBoxDown, box)
    assert not up.isEmpty() and not down.isEmpty() and not up.intersects(down)
    QTest.mouseClick(box, Qt.LeftButton, pos=up.center())
    assert box.value() == 51
    QTest.mouseClick(box, Qt.LeftButton, pos=down.center())
    assert box.value() == 50
    box.lineEdit().selectAll()
    QTest.keyClicks(box.lineEdit(), '100')
    box.interpretText()
    assert box.value() == 100
    box.stepUp()
    assert box.value() == 100 and not box.wrapping()
    box.setValue(1)
    box.stepDown()
    assert box.value() == 1
    export.close()
