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


def test_profile_switch_export_reminder_cancel_and_later_preserve_pending_state(tmp_path):
    repo, first, _ = setup_profile(tmp_path)
    second = NovelProfile(name='Second'); repo.save_profile(second)
    translator = repo.profile_dir(first.id) / 'source' / 'NovelTranslator.txt'
    translator.parent.mkdir(parents=True, exist_ok=True)
    translator.write_text('งานแปลเดิม', encoding='utf-8')
    window = MainWindow(repo); select(window, first)
    window._mark_export_pending(first.id, translator)
    choices = iter(('cancel', 'later'))
    window._export_reminder_choice = lambda _title, _details: next(choices)

    select(window, second)
    assert window.profile.id == first.id
    assert set(window.workspaces) == {first.id}

    select(window, second)
    assert window.profile.id == second.id
    assert set(window.workspaces) == {second.id}
    state = repo.profile_dir(first.id) / 'export_status.json'
    record = __import__('json').loads(state.read_text(encoding='utf-8'))[window._export_path_key(translator)]
    assert record['pending'] is True
    assert translator.read_text(encoding='utf-8') == 'งานแปลเดิม'
    window._close_export_reminder_accepted = True
    window.close()


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


def test_launch_from_settings_also_replaces_the_previous_workspace(tmp_path):
    repo, first, _ = setup_profile(tmp_path)
    second = NovelProfile(name='Second')
    repo.save_profile(second)
    second.main_folder = str(repo.profile_dir(second.id)); repo.save_profile(second)
    window = MainWindow(repo); select(window, first)
    window.settings_dialog(); select(window, second)
    window.launch_profile()
    assert set(window.workspaces) == {second.id}
    window.return_from_utility_page()
    assert window.profile.id == second.id


def test_failed_settings_switch_restores_active_profile_binding(tmp_path, monkeypatch):
    repo, first, _ = setup_profile(tmp_path)
    second = NovelProfile(name='Second'); repo.save_profile(second)
    window = MainWindow(repo); select(window, first)
    original = window.workspaces[first.id]
    window.settings_dialog(); select(window, second)
    monkeypatch.setattr(original.editor, 'save_all', lambda **kwargs: False)
    window.return_from_utility_page()
    assert set(window.workspaces) == {first.id}
    assert window.profile.id == first.id


def test_switch_reuses_recent_workspace_without_recreating_editor(tmp_path):
    repo, first, _ = setup_profile(tmp_path)
    second = NovelProfile(name='Second')
    repo.save_profile(second)
    window = MainWindow(repo)
    select(window, first)
    original = window.workspaces[first.id]
    select(window, second)
    assert set(window.workspaces) == {second.id}
    assert first.id in window._workspace_cache
    assert window.workspace_stack.count() == 2
    select(window, first)
    assert window.workspaces[first.id] is original
    assert set(window.workspaces) == {first.id}


def test_suspended_workspace_invalidated_after_external_file_change(tmp_path):
    repo, first, _ = setup_profile(tmp_path)
    second = NovelProfile(name='Second')
    repo.save_profile(second)
    source = repo.profile_dir(first.id) / 'source/Novel.txt'
    source.write_text('before', encoding='utf-8')
    window = MainWindow(repo)
    select(window, first)
    original = window.workspaces[first.id]
    original.editor.open_file(source)
    select(window, second)
    source.write_text('after externally edited', encoding='utf-8')
    select(window, first)
    assert window.workspaces[first.id] is not original
    assert 'after externally edited' in window.workspaces[first.id].editor._current_editor().toPlainText()


def test_batch_navigation_updates_sidebar_without_copy(tmp_path, monkeypatch):
    from novel_workflow.models import StepFile
    repo, profile, _ = setup_profile(tmp_path)
    vocabulary_file = repo.profile_dir(profile.id) / "reference" / "vocab.txt"
    translation_file = repo.profile_dir(profile.id) / "reference" / "translation.txt"
    vocabulary_file.write_text("ศัพท์", encoding="utf-8")
    translation_file.write_text("แปล", encoding="utf-8")
    profile.vocabulary_step.files = [StepFile(path="reference/vocab.txt", label="VOCAB_ONLY")]
    translation = next(step for step in profile.workflow.steps if step.name == "แปล")
    translation.files = [StepFile(path="reference/translation.txt", label="TRANSLATE_ONLY")]
    repo.save_profile(profile)
    window = MainWindow(repo)
    select(window, profile)
    workspace = window.workspaces[profile.id]
    copied = []
    monkeypatch.setattr(window, "copy_step", lambda *a, **kw: copied.append(True))
    try:
        window.open_txt_vocabulary(profile.id)
        assert workspace.vocabulary_mode
        assert "VOCAB_ONLY" in [workspace.files.item(i).text() for i in range(workspace.files.count())]
        window.open_translation_batches(profile.id)
        assert not workspace.vocabulary_mode
        assert window.step().name == "แปล"
        assert workspace.translation_batch_page is not None
        assert "TRANSLATE_ONLY" in [workspace.files.item(i).text() for i in range(workspace.files.count())]
        assert not copied
    finally:
        for worker in (getattr(workspace.translation_batch_page, "_load_worker", None),):
            if worker and worker.isRunning():
                worker.wait(20000)
        window.close()
