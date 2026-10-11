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
    assert len(urls) == (1 if zipped else 3)
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
    assert payload[-1].read_bytes() == b'old context\n\n'
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
        assert len(content.namelist()) == 5
        assert any(name.startswith('01_Translate/') for name in content.namelist())
        assert any(name.startswith('02_Polish/') for name in content.namelist())
    assert '5 ไฟล์' in w.statusBar().currentMessage()
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
        assert files[-1].read_bytes() == b'old context\n\n'
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
    wait_until(lambda: not w.history_busy())
    assert len(w._utility_pages['polish-history:' + p.id].snapshots) == 1
