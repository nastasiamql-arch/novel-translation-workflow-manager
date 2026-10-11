import json
import time
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication, QPushButton, QMessageBox

from novel_workflow.models import NovelProfile, StepFile, Workflow, WorkflowStep
from novel_workflow.storage import ProjectRepository
from novel_workflow.workspace_window import MainWindow


def wait_until(predicate):
    end = time.monotonic() + 15
    while not predicate() and time.monotonic() < end:
        QApplication.processEvents(); time.sleep(0.01)
    assert predicate()


@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    repo = ProjectRepository(tmp_path / 'data')
    main = tmp_path / 'novel'; main.mkdir()
    ctx = main / 'Context.md'; ctx.write_bytes(b'old context\n\n')
    first = WorkflowStep(name='Translate', files=[StepFile(path='a.txt'), StepFile(path='disabled.txt', enabled=False)])
    polish = WorkflowStep(name='Polish', files=[StepFile(path='a.txt'), StepFile(path='disabled.txt', enabled=False)])
    profile = NovelProfile(workflow=Workflow([first, polish]), main_folder=str(main), context_path=str(ctx))
    # Set through persisted document so this test catches missing model deserialization.
    repo.save_profile(profile)
    profile_path = repo.profile_dir(profile.id) / 'profile.json'
    data = json.loads(profile_path.read_text(encoding='utf-8')); data['polish_history_step_id'] = polish.id
    profile_path.write_text(json.dumps(data), encoding='utf-8')
    (profile_path.parent / 'a.txt').write_bytes(b'original\t\n\n')
    (profile_path.parent / 'disabled.txt').write_bytes(b'disabled')
    errors = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: errors.append(args[-1]))
    w = MainWindow(repo); w.refresh_profiles(profile.id)
    w._automatic_update_timer.stop(); w.show()
    yield w, w.profile, w.workspaces[profile.id], errors
    w._close_export_reminder_accepted = True
    w.close(); QApplication.processEvents()


@pytest.mark.parametrize('zipped', [False, True])
def test_named_stage_click_snapshot_then_native_clipboard(window, zipped):
    w, p, workspace, errors = window
    assert hasattr(workspace, 'history_range'), 'Missing compact chapter range input'
    workspace.history_range.setText('6-10'); w.settings.copy_files_as_zip = zipped
    workspace.stage_buttons[1].click()
    wait_until(lambda: not w.history_busy())
    urls = QApplication.clipboard().mimeData().urls()
    assert len(urls) == (1 if zipped else 2)
    assert all(Path(u.toLocalFile()).is_file() for u in urls)
    assert w.si == 1 and not errors
    assert len(w.polish_history.list(p)) == 1
    assert p.verified_goal_count == 0 and p.verified_export_history == []


def test_other_stage_keeps_enabled_only_behavior(window):
    w, p, workspace, errors = window
    assert hasattr(w, 'polish_history'), 'History service missing'
    workspace.stage_buttons[0].click()
    assert len(QApplication.clipboard().mimeData().urls()) == 1
    assert w.polish_history.list(p) == []


def test_history_page_copy_and_back_preserve_editor_and_stage(window):
    w, p, workspace, errors = window
    assert hasattr(w, 'open_polish_history'), 'History navigation missing'
    editor = workspace.editor.open_file(w.repo.profile_dir(p.id) / 'a.txt')
    editor.moveCursor(QTextCursor.End)
    position = editor.textCursor().position()
    workspace.history_range.setText('6-10'); workspace.stage_buttons[1].click()
    wait_until(lambda: not w.history_busy())
    Path(p.context_path).write_bytes(b'new context')
    w.open_polish_history()
    wait_until(lambda: not w.history_busy())
    page = w._utility_pages['polish-history:' + p.id]
    assert w.main_pages.currentWidget() is w.utility_page
    buttons = [b for b in page.findChildren(QPushButton) if b.text() == 'คัดลอก']
    assert len(buttons) == 1
    QTest.mouseClick(buttons[0], Qt.LeftButton)
    wait_until(lambda: not w.history_busy())
    payload = [Path(u.toLocalFile()) for u in QApplication.clipboard().mimeData().urls()]
    assert all(path.read_bytes() != b'old context\n\n' for path in payload)
    assert Path(p.context_path).read_bytes() == b'new context'
    assert p.verified_goal_count == 0 and p.txt_export_settings.current == 1
    w.utility_back.click()
    assert w.workspace_stack.currentWidget() is workspace
    assert workspace.editor._current_editor() is editor
    assert editor.textCursor().position() == position and w.si == 1
    assert not errors


def test_range_required_focus_and_no_false_success(window):
    w, p, workspace, errors = window
    assert hasattr(workspace, 'history_range')
    workspace.stage_buttons[1].click(); wait_until(lambda: not w.history_busy())
    assert not w.polish_history.list(p)
    assert 'ช่วงบท' in w.statusBar().currentMessage()


def test_settings_store_stable_step_id_and_disable(window):
    w, p, workspace, errors = window
    w.settings_dialog()
    assert hasattr(w, 'settings_history_step'), 'History profile setting missing'
    combo = w.settings_history_step
    assert combo.currentData() == p.workflow.steps[1].id
    combo.setCurrentIndex(0)
    assert w.repo.list_profiles()[0].polish_history_step_id is None


@pytest.mark.parametrize('names, expected', [(['แปล', 'เกลาสำนวน'], 'polish'), (['แปล', 'ตรวจคำแปล'], None), (['เกลา', 'Polish'], None)])
def test_legacy_default_only_clear_polish_name(names, expected):
    data = {'workflow': {'steps': [{'id': 'translate' if i == 0 else 'polish', 'name': name} for i, name in enumerate(names)]}}
    p = NovelProfile.from_dict(data)
    assert hasattr(p, 'polish_history_step_id')
    assert p.polish_history_step_id == expected
    data['polish_history_step_id'] = None
    assert NovelProfile.from_dict(data).polish_history_step_id is None


def test_history_copy_survives_window_close(window):
    w, p, workspace, errors = window
    assert hasattr(workspace, 'history_range')
    workspace.history_range.setText('1-5'); workspace.stage_buttons[1].click()
    wait_until(lambda: not w.history_busy())
    paths = [Path(u.toLocalFile()) for u in QApplication.clipboard().mimeData().urls()]
    w._close_export_reminder_accepted = True; w.close()
    assert all(path.is_file() for path in paths)


def test_save_for_review_does_not_copy_or_advance(window):
    w, p, workspace, errors = window
    workspace.history_range.setText('101-150')
    clipboard_before = [url.toLocalFile() for url in QApplication.clipboard().mimeData().urls()]
    selection_before = w.si
    counter_before = p.verified_goal_count
    workspace.save_for_review_button.click()
    wait_until(lambda: not w.history_busy())
    items = w.polish_history.list(p)
    assert len(items) == 1 and items[0].manifest['review_status'] == 'รอตรวจ'
    assert items[0].path.name == 'Polish บท 101-150'
    assert w.si == selection_before and p.verified_goal_count == counter_before
    assert [url.toLocalFile() for url in QApplication.clipboard().mimeData().urls()] == clipboard_before


def test_successful_txt_export_creates_pending_snapshot_without_reexport(window, tmp_path):
    w, p, workspace, errors = window
    export = workspace.editor.export_tab
    export.directory.setText(str(tmp_path))
    export.editor.setPlainText('บทที่ 51\nเนื้อหาที่ส่งออก')
    assert export.export()
    wait_until(lambda: not w.history_busy())
    persisted = next(item for item in w.repo.list_profiles() if item.id == p.id)
    items = w.polish_history.list(persisted)
    assert len(items) == 1
    assert items[0].manifest['chapter_range'] == '51'
    assert items[0].manifest['review_status'] == 'รอตรวจ'
    assert (tmp_path / 'segverified1.txt').is_file()
    persisted = next(item for item in w.repo.list_profiles() if item.id == p.id)
    assert persisted.verified_goal_count == 1
    assert len(persisted.verified_export_history) == 1
    assert not errors


def test_export_without_verifiable_chapter_range_is_kept_unresolved(window, tmp_path):
    w, p, workspace, errors = window
    export = workspace.editor.export_tab
    export.directory.setText(str(tmp_path))
    export.editor.setPlainText('ข้อความที่ไม่มีหัวบท')
    assert export.export()
    wait_until(lambda: not w.history_busy())
    item = w.polish_history.list(p)[0]
    assert item.manifest['chapter_range'] is None
    assert item.path.name.startswith('Polish รอระบุช่วงบท')
    assert item.manifest['review_status'] == 'รอตรวจ'
    assert not errors


def test_failed_save_blocks_stage_snapshot(window, monkeypatch):
    w, p, workspace, errors = window
    assert hasattr(w, 'polish_history')
    monkeypatch.setattr(workspace.editor, 'save_all', lambda **kwargs: False)
    workspace.stage_buttons[1].click()
    assert w.polish_history.list(p) == []


def test_cached_history_follows_changed_main_folder(window, tmp_path):
    from dataclasses import asdict
    w, p, workspace, errors = window
    workspace.history_range.setText('6-10'); workspace.stage_buttons[1].click()
    wait_until(lambda: not w.history_busy())
    w.open_polish_history(); wait_until(lambda: not w.history_busy())
    w.utility_back.click()
    # Reloaded profiles are new objects; the cached page must follow the active one.
    other = tmp_path / 'new-main'; other.mkdir()
    w.profile = NovelProfile.from_dict({**asdict(p), 'main_folder': str(other)})
    w.open_polish_history(); wait_until(lambda: not w.history_busy())
    page = w._utility_pages['polish-history:' + p.id]
    assert page.snapshots == []


def test_multistage_zip_keeps_all_stages_and_snapshot_context(window):
    import zipfile
    w, p, workspace, errors = window
    workspace.history_range.setText('6-10'); w.settings.copy_files_as_zip = True
    w.copy_step(advance=False, selected_steps=p.workflow.steps)
    wait_until(lambda: not w.history_busy())
    archive = Path(QApplication.clipboard().mimeData().urls()[0].toLocalFile())
    with zipfile.ZipFile(archive) as content:
        assert len(content.namelist()) == 4
        assert any(name.startswith('01_Translate/') for name in content.namelist())
        assert any(name.startswith('02_Polish/') for name in content.namelist())
    assert '4 ไฟล์' in w.statusBar().currentMessage()
    assert not errors


def test_reopened_window_recovers_old_context_from_disk(window):
    w, p, workspace, errors = window
    workspace.history_range.setText('6-10'); workspace.stage_buttons[1].click()
    wait_until(lambda: not w.history_busy())
    w._close_export_reminder_accepted = True; w.close()
    Path(p.context_path).write_bytes(b'latest context after restart')
    reopened = MainWindow(ProjectRepository(w.repo.root))
    reopened._automatic_update_timer.stop(); reopened.refresh_profiles(p.id)
    try:
        reopened.open_polish_history(); wait_until(lambda: not reopened.history_busy())
        page = reopened._utility_pages['polish-history:' + p.id]
        assert len(page.snapshots) == 1
        copy = next(b for b in page.findChildren(QPushButton) if b.text() == 'คัดลอก')
        copy.click(); wait_until(lambda: not reopened.history_busy())
        files = [Path(u.toLocalFile()) for u in QApplication.clipboard().mimeData().urls()]
        assert all(path.read_bytes() != b'old context\n\n' for path in files)
        assert Path(p.context_path).read_bytes() == b'latest context after restart'
        assert reopened.profile.verified_export_history == []
    finally:
        reopened._close_export_reminder_accepted = True; reopened.close()


def test_history_opened_during_snapshot_loads_after_job_finishes(window, monkeypatch):
    from threading import Event
    w, p, workspace, errors = window
    ready = Event(); create = w.polish_history.create
    def pending(*args, **kwargs):
        assert ready.wait(3)
        return create(*args, **kwargs)
    monkeypatch.setattr(w.polish_history, 'create', pending)
    workspace.history_range.setText('6-10'); workspace.stage_buttons[1].click()
    w.open_polish_history(); ready.set()
    page = w._utility_pages['polish-history:' + p.id]
    wait_until(lambda: not w.history_busy() and len(page.snapshots) == 1)

def test_history_refresh_preserves_clipboard_then_migrates_legacy(window):
    from PySide6.QtCore import QMimeData, QUrl
    w, p, workspace, errors = window
    step = p.workflow.steps[1]
    snapshot = w.polish_history.create(p, step, '6-10')
    legacy_root = w.polish_history.root(p) / f'{step.id}-{p.id}'
    legacy_root.mkdir()
    old = legacy_root / f'บท 6-10__20261012-040000__{snapshot.manifest["snapshot_id"]}'
    snapshot.path.rename(old)
    paths = w.polish_history.clipboard_paths(p, old, zipped=False)
    mime = QMimeData(); mime.setUrls([QUrl.fromLocalFile(str(x)) for x in paths])
    QApplication.clipboard().setMimeData(mime)
    w.open_polish_history(); wait_until(lambda: not w.history_busy())
    page = w._utility_pages['polish-history:' + p.id]
    assert page.snapshots[0].path == old and page.snapshots[0].warning
    assert all(x.is_file() for x in paths)
    assert any(b.isEnabled() for b in page.findChildren(QPushButton) if b.text() == 'คัดลอก')
    QApplication.clipboard().clear()
    page.refresh(); wait_until(lambda: not w.history_busy())
    assert page.snapshots[0].path.parent == w.polish_history.root(p)
    assert not old.exists() and not errors
