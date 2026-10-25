import json
import time
from pathlib import Path

import pytest
from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication, QPushButton, QMessageBox, QLabel

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
    deadline = time.monotonic() + 15
    workers = [w._update_check_worker, w._update_download_worker, *w._history_workers]
    inspector = w._utility_pages.get('novel-inspector')
    if inspector is not None:
        workers.extend([inspector.worker, inspector.write_worker])
    workers = [worker for worker in workers if worker is not None]
    for worker in workers:
        if worker.isRunning():
            worker.requestInterruption()
    while any(worker.isRunning() for worker in workers) and time.monotonic() < deadline:
        QApplication.processEvents(); time.sleep(0.01)
    for worker in workers:
        worker.wait(100)
    w.close(); QApplication.processEvents()
    while w.isVisible() and time.monotonic() < deadline:
        QApplication.processEvents(); time.sleep(0.01)
    QTest.qWait(10)


@pytest.mark.parametrize('zipped', [False, True])
def test_named_stage_click_copies_immediately_without_snapshot(window, zipped):
    w, p, workspace, errors = window
    assert hasattr(workspace, 'history_range'), 'Missing compact chapter range input'
    workspace.history_range.setText('6-10')
    w.settings.copy_files_as_zip = zipped
    QApplication.clipboard().setText("keep this text")

    # Clicking the named stage itself must publish its files to the clipboard.
    workspace.stage_buttons[1].click()
    urls = QApplication.clipboard().mimeData().urls()
    assert len(urls) == 1
    copied = Path(urls[0].toLocalFile())
    assert copied.is_file()
    if zipped:
        import zipfile
        with zipfile.ZipFile(copied) as archive:
            assert len(archive.namelist()) == 2  # ZIP includes disabled attachments.
            assert any(name.endswith('/a.txt') for name in archive.namelist())
    else:
        assert copied.read_bytes() == (w.repo.profile_dir(p.id) / 'a.txt').read_bytes()

    assert w.si == 1 and workspace.step_index == 1 and not errors
    assert workspace.history_range.text() == '6-10'
    assert w.polish_history.list(p) == []
    assert p.verified_goal_count == 0 and p.verified_export_history == []

    # The explicit button remains usable, including on the already selected step.
    QApplication.clipboard().setText("replace me again")
    workspace.copy_step_button.click()
    assert len(QApplication.clipboard().mimeData().urls()) == 1
    assert w.si == 1 and not errors
    assert w.polish_history.list(p) == []


def test_other_stage_keeps_enabled_only_behavior(window):
    w, p, workspace, errors = window
    assert hasattr(w, 'polish_history'), 'History service missing'
    workspace.stage_buttons[0].click()
    workspace.copy_step_button.click()
    assert len(QApplication.clipboard().mimeData().urls()) == 1
    assert w.polish_history.list(p) == []


def test_vocabulary_custom_and_repeated_stage_clicks_copy_only_active_files(window):
    w, p, workspace, errors = window
    p.vocabulary_step.files = [StepFile(path='disabled.txt')]
    p.workflow.steps.append(WorkflowStep(name='ตรวจเพิ่ม', files=[StepFile(path='disabled.txt')]))
    w.refresh_steps()

    actions = [
        (workspace.vocabulary_button, 'หาศัพท์', b'disabled', None),
        (workspace.stage_buttons[0], 'Translate', b'original\t\n\n', 0),
        (workspace.stage_buttons[1], 'Polish', b'original\t\n\n', 1),
        (workspace.stage_buttons[2], 'ตรวจเพิ่ม', b'disabled', 2),
        (workspace.stage_buttons[2], 'ตรวจเพิ่ม', b'disabled', 2),
    ]
    for button, stage_name, expected, row in actions:
        QApplication.clipboard().setText('old clipboard')
        button.click()
        urls = QApplication.clipboard().mimeData().urls()
        assert len(urls) == 1, stage_name
        copied = Path(urls[0].toLocalFile())
        assert copied.read_bytes() == expected, stage_name
        assert w.step().name == stage_name
        assert workspace.vocabulary_mode == (row is None)
        if row is not None:
            assert w.si == row and workspace.step_index == row
        assert not errors

    assert w.polish_history.list(p) == []
    assert p.verified_goal_count == 0 and p.verified_export_history == []


def test_named_stage_copy_failure_keeps_previous_clipboard(window):
    w, p, workspace, errors = window
    p.workflow.steps[0].files = [StepFile(path='missing-file.txt')]
    QApplication.clipboard().setText('existing clipboard contents')
    workspace.stage_buttons[0].click()
    assert QApplication.clipboard().text() == 'existing clipboard contents'
    assert w.si == 0
    assert errors and 'missing-file.txt' in str(errors[-1])
    assert w.polish_history.list(p) == []


def test_history_page_copy_and_back_preserve_editor_and_stage(window):
    w, p, workspace, errors = window
    assert hasattr(w, 'open_polish_history'), 'History navigation missing'
    editor = workspace.editor.open_file(w.repo.profile_dir(p.id) / 'a.txt')
    editor.moveCursor(QTextCursor.End)
    position = editor.textCursor().position()
    workspace.history_range.setText('6-10'); workspace.stage_buttons[1].click(); workspace.save_for_review_button.click()
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
    wait_until(lambda: any(label.text() == '✓  คัดลอกแล้ว'
                           for label in page.findChildren(QLabel, 'historyCopyState')))
    assert all(path.read_bytes() != b'old context\n\n' for path in payload)
    assert Path(p.context_path).read_bytes() == b'new context'
    assert p.verified_goal_count == 0 and p.txt_export_settings.current == 1
    w.utility_back.click()
    assert w.workspace_stack.currentWidget() is workspace
    assert workspace.editor._current_editor() is editor
    assert editor.textCursor().position() == position and w.si == 1
    assert not errors


def test_history_copy_button_stays_left_of_the_row(window):
    w, p, workspace, errors = window
    workspace.history_range.setText('6-10')
    workspace.stage_buttons[1].click(); workspace.save_for_review_button.click()
    wait_until(lambda: not w.history_busy())
    w.open_polish_history()
    wait_until(lambda: not w.history_busy())
    page = w._utility_pages['polish-history:' + p.id]
    card = next(iter(page._cards_by_id.values()))
    card.show(); QApplication.processEvents()
    copy = card.findChild(QPushButton, 'polishHistoryCopy')
    delete = card.findChild(QPushButton, 'polishHistoryDelete')
    assert copy is not None and delete is not None
    assert copy.geometry().center().x() < card.width() * 0.45
    assert delete.geometry().center().x() > card.width() * 0.85


def test_copy_event_storage_error_is_reported_without_escaping_callback(window, monkeypatch):
    w, p, workspace, errors = window
    workspace.history_range.setText('6-10')
    workspace.stage_buttons[1].click(); workspace.save_for_review_button.click()
    wait_until(lambda: not w.history_busy())
    snapshot = w.polish_history.list(p)[0]
    monkeypatch.setattr(w, '_record_history_copy_success', lambda *args: (_ for _ in ()).throw(OSError('disk full')))
    w.copy_history_snapshot(p, snapshot)
    wait_until(lambda: not w.history_busy())
    assert 'บันทึกประวัติการคัดลอกไม่สำเร็จ' in w.statusBar().currentMessage()
    assert QApplication.clipboard().mimeData().urls()


def test_resume_and_previous_buttons_scroll_when_progress_is_at_last_snapshot(window):
    w, p, workspace, errors = window
    step = w._history_step_for_profile(p)
    snapshots = [w.polish_history.create(p, step, f'{start}-{start + 3}')
                 for start in range(1, 101, 4)]
    key = f'{p.id}:{step.id}'
    events = [
        {'event_id': f'event-{i}', 'profile_id': p.id, 'step_id': step.id,
         'snapshot_id': snapshot.manifest['snapshot_id'],
         'chapter_range': snapshot.manifest['chapter_range'],
         'timestamp': f'2026-10-25T00:{i:02d}:00+00:00',
         'result': 'clipboard_set'}
        for i, snapshot in enumerate(snapshots)
    ]
    w.settings.history_copy_events[key] = events
    w.settings.history_copy_state[key] = events[-1]
    w.settings.history_sort_modes[p.id] = 'chapter_asc'
    w.repo.save_settings(w.settings)

    w.open_polish_history()
    wait_until(lambda: not w.history_busy())
    page = w._utility_pages['polish-history:' + p.id]
    page.history_scroll.setFixedHeight(75)
    QApplication.processEvents()
    assert not page._recommended
    assert page.resume_button.isEnabled()

    bar = page.history_scroll.verticalScrollBar()
    bar.setValue(bar.minimum())
    page.resume_button.click()
    last_id = page._snapshot_id(snapshots[-1])
    wait_until(lambda: page._navigation_snapshot_id == last_id and bar.value() > bar.minimum())
    last_position = bar.value()

    page.previous_button.click()
    previous_id = page._snapshot_id(snapshots[-2])
    wait_until(lambda: page._navigation_snapshot_id == previous_id)
    assert bar.value() < last_position


@pytest.mark.parametrize('zipped', [False, True])
def test_history_copy_buttons_keep_position_for_repeat_and_advance_from_new_batch(window, zipped):
    w, p, workspace, errors = window
    step = w._history_step_for_profile(p)
    snapshots = [w.polish_history.create(p, step, f'{start}-{start + 3}')
                 for start in range(1, 101, 4)]
    key = f'{p.id}:{step.id}'
    first_event = {
        'event_id': 'already-copied', 'profile_id': p.id, 'step_id': step.id,
        'snapshot_id': snapshots[0].manifest['snapshot_id'], 'chapter_range': '1-4',
        'timestamp': '2026-10-25T10:00:00+00:00', 'file_count': 1,
        'mode': 'files', 'result': 'clipboard_set',
    }
    w.settings.history_copy_events[key] = [first_event]
    w.settings.history_copy_state[key] = first_event
    w.settings.history_sort_modes[p.id] = 'chapter_asc'
    w.settings.history_copy_as_zip = zipped
    w.repo.save_settings(w.settings)

    w.open_polish_history()
    wait_until(lambda: not w.history_busy())
    page = w._utility_pages[f'polish-history:{p.id}']
    page.history_scroll.setFixedHeight(110)
    QApplication.processEvents()
    bar = page.history_scroll.verticalScrollBar()
    wait_until(lambda: bar.maximum() > bar.minimum())
    bar.setValue(bar.maximum() // 2)
    QApplication.processEvents()
    initial_scroll = bar.value()
    assert initial_scroll > bar.minimum()

    # Copying a previously copied range records the repeat, updates its badge,
    # and must not dump a user who is browsing the middle of history at row 1.
    repeat_button = page._cards_by_id[page._snapshot_id(snapshots[0])].findChild(
        QPushButton, 'polishHistoryCopy')
    repeat_button.click()
    wait_until(lambda: len(w.repo.load_settings().history_copy_events[key]) == 2)
    QApplication.processEvents()
    assert abs(bar.value() - initial_scroll) <= 2
    assert any(label.text() == '✓  คัดลอกแล้ว'
               for label in page._cards_by_id[page._snapshot_id(snapshots[0])].findChildren(
                   QLabel, 'historyCopyState'))

    # A newly advanced range moves to the next real snapshot and marks it.
    next_button = page._cards_by_id[page._snapshot_id(snapshots[1])].findChild(
        QPushButton, 'polishHistoryCopy')
    next_button.click()
    wait_until(lambda: len(w.repo.load_settings().history_copy_events[key]) == 3)
    next_id = page._snapshot_id(snapshots[2])
    def next_row_visible():
        next_row = page._cards_by_id.get(next_id)
        if next_row is None:
            return False
        row_top = next_row.mapTo(page.history_scroll.viewport(), QPoint(0, 0)).y()
        return -next_row.height() < row_top < page.history_scroll.viewport().height()
    wait_until(lambda: page._navigation_snapshot_id == next_id and next_row_visible())
    next_row = page._cards_by_id[next_id]
    row_top = next_row.mapTo(page.history_scroll.viewport(), QPoint(0, 0)).y()
    assert -next_row.height() < row_top < page.history_scroll.viewport().height()
    assert next_row.property('recommendedNext') is True
    QTest.qWait(50)  # Drain the page's deferred layout/scroll callbacks before teardown.
    assert not errors


def test_range_required_focus_and_no_false_success(window):
    w, p, workspace, errors = window
    assert hasattr(workspace, 'history_range')
    workspace.stage_buttons[1].click(); workspace.save_for_review_button.click()
    wait_until(lambda: not w.history_busy())
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
    workspace.history_range.setText('1-5'); workspace.stage_buttons[1].click(); workspace.save_for_review_button.click()
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


def test_copying_older_history_updates_last_copied_without_moving_resume(window):
    w, p, workspace, errors = window
    step = w._history_step_for_profile(p)
    older = w.polish_history.create(p, step, '21-24')
    newer = w.polish_history.create(p, step, '37-40')
    w.open_polish_history()
    wait_until(lambda: not w.history_busy())
    page = w._utility_pages['polish-history:' + p.id]
    key = f'{p.id}:{step.id}'
    page.set_resume_position(newer)
    before_exports = (p.verified_goal_count, len(p.verified_export_history), p.txt_export_settings.current)

    w.settings.history_copy_as_zip = True
    w.copy_history_snapshot(p, older)
    wait_until(lambda: key in w.repo.load_settings().history_copy_state)
    state = w.repo.load_settings()
    assert state.history_copy_state[key]['chapter_range'] == '21-24'
    assert state.history_copy_state[key]['snapshot_id'] == older.manifest['snapshot_id']
    assert state.history_resume_positions[key]['chapter_range'] == '37-40'
    assert len(state.history_copy_events[key]) == 1
    assert (p.verified_goal_count, len(p.verified_export_history), p.txt_export_settings.current) == before_exports


def test_history_auto_resume_uses_successful_snapshot_events_and_ignores_display_sort(window):
    w, p, workspace, errors = window
    step = w._history_step_for_profile(p)
    older = w.polish_history.create(p, step, '101-104')
    copied = w.polish_history.create(p, step, '137-140')
    next_batch = w.polish_history.create(p, step, '141-144')
    page_key = f'polish-history:{p.id}'
    w.open_polish_history()
    wait_until(lambda: not w.history_busy())
    page = w._utility_pages[page_key]
    key = f'{p.id}:{step.id}'
    w.settings.history_copy_events[key] = [
        {'event_id': 'a', 'profile_id': p.id, 'step_id': step.id,
         'snapshot_id': older.manifest['snapshot_id'], 'chapter_range': '101-104',
         'timestamp': '2026-10-25T10:00:00+00:00', 'result': 'clipboard_set'},
        {'event_id': 'b', 'profile_id': p.id, 'step_id': step.id,
         'snapshot_id': copied.manifest['snapshot_id'], 'chapter_range': '137-140',
         'timestamp': '2026-10-25T11:00:00+00:00', 'result': 'clipboard_set'},
    ]
    w.settings.history_copy_state[key] = w.settings.history_copy_events[key][-1]
    page._sort_mode = 'manual'
    w.settings.history_manual_order[p.id] = [
        next_batch.manifest['snapshot_id'], copied.manifest['snapshot_id'], older.manifest['snapshot_id']
    ]
    page._update_progress_summary()
    page.render()
    assert page._recommended.manifest['snapshot_id'] == next_batch.manifest['snapshot_id']
    assert 'เคยคัดลอกแล้ว 2 ชุด' in page.progress_summary.text()
    assert page.findChildren(QPushButton, 'setHistoryResumePosition') == []
    assert page.previous_button.text() == '← ชุดก่อนหน้า'
    assert page.resume_button.text() == 'ไปจุดทำงานต่อ'
    active_rows = [page.card_layout.itemAt(i).widget() for i in range(page.card_layout.count())
                   if page.card_layout.itemAt(i).widget() is not None]
    assert len(active_rows) == 3


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
    editor = workspace.editor.open_file(w.repo.profile_dir(p.id) / 'a.txt')
    editor.insertPlainText('unsaved work')
    monkeypatch.setattr(workspace.editor, 'save_editor', lambda *args, **kwargs: False)
    workspace.stage_buttons[1].click(); workspace.save_for_review_button.click()
    assert w.polish_history.list(p) == []


def test_cached_history_follows_changed_main_folder(window, tmp_path):
    from dataclasses import asdict
    w, p, workspace, errors = window
    workspace.history_range.setText('6-10'); workspace.stage_buttons[1].click(); workspace.save_for_review_button.click()
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
    workspace.history_range.setText('6-10'); workspace.stage_buttons[1].click(); workspace.save_for_review_button.click()
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
    workspace.history_range.setText('6-10'); workspace.stage_buttons[1].click(); workspace.save_for_review_button.click()
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
    paths = w.polish_history.validate(p, old)  # Simulate pre-upgrade direct clipboard references.
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


def test_history_copy_button_shows_zip_scope_when_enabled(window):
    import zipfile
    w, p, workspace, errors = window
    workspace.history_range.setText('6-10')
    workspace.stage_buttons[1].click(); workspace.save_for_review_button.click()
    wait_until(lambda: not w.history_busy())
    w.open_polish_history()
    wait_until(lambda: not w.history_busy())
    page = w._utility_pages['polish-history:' + p.id]
    button = page.findChild(QPushButton, 'polishHistoryCopy')
    assert button.text() == 'คัดลอก'

    assert page.zip_mode.objectName() == 'historyCopyAsZip'
    page.zip_mode.setChecked(True)
    button = page.findChild(QPushButton, 'polishHistoryCopy')
    assert button.text() == 'คัดลอก ZIP'
    assert workspace.copy_step_button.text() == 'COPY STEP'
    assert w.repo.load_settings().history_copy_as_zip is True
    assert w.repo.load_settings().copy_files_as_zip is False
    button.click()
    wait_until(lambda: not w.history_busy())
    files = [Path(url.toLocalFile()) for url in QApplication.clipboard().mimeData().urls()]
    assert len(files) == 1
    with zipfile.ZipFile(files[0]) as archived:
        assert len(archived.namelist()) == 2
    assert not errors
