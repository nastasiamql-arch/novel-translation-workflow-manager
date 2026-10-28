import hashlib
import json
import os
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
from PySide6.QtWidgets import QApplication, QPushButton, QMessageBox
from PySide6.QtGui import QTextCursor
from test_polish_history import history
from test_polish_history_ui import window, wait_until


def test_stale_pending_is_repaired_after_restart(window):
    w, p, ws, errors = window
    path = w.repo.profile_dir(p.id) / 'a.txt'
    w._record_successful_export(p.id, path, hashlib.sha256(path.read_bytes()).digest(), path)
    w._mark_export_pending(p.id, path)
    w._export_status_cache.clear()
    assert w._pending_export_for_profile(p.id) is None
    assert w._pending_export_profiles() == []
    assert not json.loads(w._export_status_path(p.id).read_text(encoding='utf-8'))[w._export_path_key(path)]['pending']


def test_external_change_with_same_timestamp_is_pending(window):
    w, p, ws, errors = window
    path = w.repo.profile_dir(p.id) / 'a.txt'
    raw = path.read_bytes()
    w._record_successful_export(p.id, path, hashlib.sha256(raw).digest(), path)
    editor = ws.editor.open_file(path)
    stamp = path.stat()
    path.write_bytes(b'x' * len(raw))
    os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    assert w._translator_export_status(p.id, path, editor) == 'not_exported'


def test_invalid_export_status_is_reported_without_overwriting_original(window):
    w, p, ws, errors = window
    path = w.repo.profile_dir(p.id) / 'a.txt'
    status_path = w._export_status_path(p.id)
    status_path.write_bytes(b'{"broken":')
    original = status_path.read_bytes()
    w._export_status_cache.pop(p.id, None)
    w._export_status_errors.pop(p.id, None)
    assert w._translator_export_status(p.id, path) == 'error'
    assert w._export_status_errors[p.id]
    w._mark_export_pending(p.id, path)
    assert status_path.read_bytes() == original


def test_normalization_open_and_undo_export_status(window):
    w, p, ws, errors = window
    path = w.repo.profile_dir(p.id) / 'a.txt'
    raw = b'\xef\xbb\xbffirst\r\n\r\nsecond\r\n'
    path.write_bytes(raw)
    w._record_successful_export(p.id, path, hashlib.sha256(raw).digest(), path)
    editor = ws.editor.open_file(path)
    assert w._translator_export_status(p.id, path, editor) == 'exported'
    editor.moveCursor(QTextCursor.End); editor.insertPlainText('changed')
    assert w._translator_export_status(p.id, path, editor) == 'not_exported'
    editor.undo()
    assert w._translator_export_status(p.id, path, editor) == 'exported'
    assert path.read_bytes() == raw


def test_undo_normalized_baseline_then_autosave_preserves_export(window):
    w, p, ws, errors = window
    path = w.repo.profile_dir(p.id) / 'a.txt'
    raw = b'\xef\xbb\xbfline\r\n\r\nnext\r\n'
    path.write_bytes(raw)
    w._record_successful_export(p.id, path, hashlib.sha256(raw).digest(), path)
    editor = ws.editor.open_file(path)
    editor.insertPlainText('change'); editor.undo()
    ws.editor._autosave_editor(editor)
    assert path.read_bytes() == raw
    assert w._translator_export_status(p.id, path, editor) == 'exported'


def test_copy_normal_files_are_frozen_and_latest(window):
    w, p, ws, errors = window
    path = w.repo.profile_dir(p.id) / 'a.txt'
    editor = ws.editor.open_file(path)
    editor.insertPlainText('latest')
    ws.stage_buttons[0].click()
    ws.copy_step_button.click()
    payload = Path(QApplication.clipboard().mimeData().urls()[0].toLocalFile())
    expected = path.read_bytes()
    path.write_bytes(b'changed later')
    assert payload != path
    assert payload.name == path.name
    assert payload.read_bytes() == expected


def test_copy_conflict_preserves_clipboard_and_step(window):
    w, p, ws, errors = window
    path = w.repo.profile_dir(p.id) / 'a.txt'
    editor = ws.editor.open_file(path); editor.insertPlainText('unsaved')
    path.write_bytes(b'external')
    QApplication.clipboard().setText('unrelated clipboard')
    old = w.si
    w.copy_step()
    assert QApplication.clipboard().text() == 'unrelated clipboard'
    assert w.si == old
    assert path.read_bytes() == b'external'


def test_history_numbers_survive_deletion_restart_and_migration(history):
    service, p, s = history
    first = service.create(p, s, '1-5')
    second = service.create(p, s, '6-10')
    assert first.manifest['history_number'] == 1
    assert second.manifest['history_number'] == 2
    service.delete(p, second.path)
    third = service.create(p, s, '11-15')
    assert third.manifest['history_number'] == 3
    manifest = json.loads((first.path / 'manifest.json').read_text(encoding='utf-8'))
    manifest.pop('history_number')
    (first.path / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    migrated = service.list(p)
    assert len({x.manifest['history_number'] for x in migrated}) == 2
    assert service.validate(p, first.path)


@pytest.mark.skipif(os.name != 'nt', reason='Native Windows Recycle Bin')
def test_native_recycle_bin_receives_snapshot(history):
    service, p, s = history
    snapshot = service.create(p, s, '1-5')
    # Native shell API, no mock. Recycle Bin contents verified through Shell COM.
    original = (snapshot.path / 'manifest.json').read_bytes()
    recycled = service.delete(p, snapshot.path)
    assert not snapshot.path.exists()
    assert '$recycle.bin' in str(recycled).lower()
    assert (recycled / 'manifest.json').read_bytes() == original
    assert Path(p.context_path).is_file()


def test_compact_history_delete_has_no_confirmation(window, monkeypatch):
    w, p, ws, errors = window
    ws.history_range.setText('6-10'); ws.stage_buttons[1].click(); w.save_for_review()
    wait_until(lambda: not w.history_busy())
    w.open_polish_history(); wait_until(lambda: not w.history_busy())
    page = w._utility_pages['polish-history:' + p.id]
    buttons = page.findChildren(QPushButton, 'polishHistoryDelete')
    assert len(buttons) == 1
    assert 'ลำดับ 1' in buttons[0].accessibleName()
    monkeypatch.setattr(QMessageBox, 'question', lambda *a: pytest.fail('No confirmation allowed'))
    buttons[0].click(); wait_until(lambda: not w.history_busy())
    wait_until(lambda: not page.snapshots)
    assert not errors


@pytest.mark.parametrize('zipped', [False, True])
@pytest.mark.parametrize('stage', ['vocabulary', 0, 1, 'multiple'])
def test_copy_every_entry_point_latest_bytes(window, zipped, stage):
    import zipfile
    from novel_workflow.models import StepFile
    w, p, ws, errors = window
    path = w.repo.profile_dir(p.id) / 'a.txt'
    p.vocabulary_step.files = [StepFile(path='a.txt')]
    editor = ws.editor.open_file(path)
    editor.insertPlainText('Thai 中文 latest')
    # Exercise an incorrectly retained normalization flag, as restored editors
    # must use actual text rather than skipping user changes based on this flag.
    editor.setProperty('normalizationPending', True)
    ws.history_range.setText('6-10')
    w.settings.copy_files_as_zip = zipped
    if stage == 'multiple': w.copy_step(advance=False, selected_steps=p.workflow.steps)
    else:
        w.copy_named_stage(p.id, stage)
    wait_until(lambda: not w.history_busy())
    payloads = [Path(u.toLocalFile()) for u in QApplication.clipboard().mimeData().urls()]
    expected = path.read_bytes()
    assert b'latest' in expected
    if zipped:
        with zipfile.ZipFile(payloads[0]) as archive:
            matches = [archive.read(n) for n in archive.namelist() if n.endswith('/a.txt')]
            assert matches and all(raw == expected for raw in matches)
    else:
        assert any(raw.read_bytes() == expected for raw in payloads)
    assert not errors


def test_copy_untouched_normalization_preserves_bom_crlf(window):
    w, p, ws, errors = window
    path = w.repo.profile_dir(p.id) / 'a.txt'
    raw = b'\xef\xbb\xbfline\r\n\r\nnext\r\n'
    path.write_bytes(raw); ws.editor.open_file(path)
    ws.stage_buttons[0].click(); ws.copy_step_button.click()
    payload = Path(QApplication.clipboard().mimeData().urls()[0].toLocalFile())
    assert payload.read_bytes() == path.read_bytes() == raw


def test_copy_external_and_dynamic_reference(window, tmp_path, monkeypatch):
    from novel_workflow.models import StepFile
    w, p, ws, errors = window
    external = tmp_path / '中文 Context.md'; external.write_bytes(b'chapter 1-5')
    dynamic = tmp_path / 'Source.txt'; dynamic.write_bytes(b'chapter 6-10')
    p.workflow.steps[0].files = [StepFile(reference_type='external_file', path=str(external)),
                               StepFile(reference_type='dynamic', dynamic_reference='latest')]
    monkeypatch.setattr(w.assembler, 'resolve', lambda *args: dynamic)
    ws.stage_buttons[0].click(); ws.copy_step_button.click()
    paths = [Path(u.toLocalFile()) for u in QApplication.clipboard().mimeData().urls()]
    assert {path.read_bytes() for path in paths} == {b'chapter 1-5', b'chapter 6-10'}
    assert not errors


def test_copy_multiple_edited_tabs(window):
    from novel_workflow.models import StepFile
    w, p, ws, errors = window
    folder = w.repo.profile_dir(p.id)
    second = folder / 'second.md'; second.write_bytes(b'second')
    p.workflow.steps[0].files.append(StepFile(path='second.md'))
    first = ws.editor.open_file(folder / 'a.txt')
    other = ws.editor.open_file(second)
    first.insertPlainText('latest first'); other.insertPlainText('latest second')
    ws.stage_buttons[0].click()
    paths = [Path(u.toLocalFile()) for u in QApplication.clipboard().mimeData().urls()]
    assert len(paths) == 2
    assert all(b'latest' in path.read_bytes() for path in paths)


def test_recycle_failure_preserves_history_and_unrelated_clipboard(window, monkeypatch):
    import novel_workflow.recycle_bin as recycle
    w, p, ws, errors = window
    snapshot = w.polish_history.create(p, p.workflow.steps[1], '6-10')
    monkeypatch.setattr(recycle, 'recycle_snapshot', lambda path: (_ for _ in ()).throw(OSError('unavailable')))
    QApplication.clipboard().setText('unrelated')
    w.open_polish_history(); wait_until(lambda: not w.history_busy())
    page = w._utility_pages['polish-history:' + p.id]
    button = page.findChildren(QPushButton, 'polishHistoryDelete')[0]
    button.click(); wait_until(lambda: not w.history_busy())
    assert snapshot.path.exists() and len(page.snapshots) == 1
    button = page.findChildren(QPushButton, 'polishHistoryDelete')[0]
    assert button.isEnabled()
    assert QApplication.clipboard().text() == 'unrelated'
    assert 'unavailable' in page.status.text()


def test_copy_history_then_recycle_keeps_old_clipboard_bytes(history):
    service, p, s = history
    snapshot = service.create(p, s, '6-10')
    frozen = service.clipboard_paths(p, snapshot.path, zipped=False)
    before = [path.read_bytes() for path in frozen]
    service.delete(p, snapshot.path, clipboard_paths=frozen)
    assert [path.read_bytes() for path in frozen] == before


def test_recycle_refuses_snapshot_payload_bound_to_workflow(history):
    from novel_workflow.models import StepFile
    service, p, s = history
    snapshot = service.create(p, s, '6-10')
    payload = service.validate(p, snapshot.path)[0]
    s.files.append(StepFile(reference_type='external_file', path=str(payload)))
    with pytest.raises(ValueError, match='Workflow'): service.delete(p, snapshot.path)
    assert payload.is_file()


def test_migration_orders_equal_timestamps_by_stable_id(history):
    service, p, s = history
    snapshots = [service.create(p, s, span) for span in ['1-5', '6-10']]
    original_payload = {}
    for snapshot in snapshots:
        original_payload[snapshot.path] = [path.read_bytes() for path in service.validate(p, snapshot.path)]
        manifest = snapshot.manifest.copy(); manifest.pop('history_number')
        manifest['created_at'] = '2026-10-13T00:00:00+00:00'
        (snapshot.path / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    (service.repo.profile_dir(p.id) / 'history_numbers.json').unlink()
    migrated = service.list(p)
    ordered = sorted(migrated, key=lambda x: x.manifest['snapshot_id'])
    assert [x.manifest['history_number'] for x in ordered] == [1, 2]
    for snapshot in migrated:
        assert [path.read_bytes() for path in service.validate(p, snapshot.path)] == original_payload[snapshot.path]


def test_bad_history_number_does_not_block_other_snapshots(history):
    service, p, s = history
    bad = service.create(p, s, '1-5')
    good = service.create(p, s, '6-10')
    manifest = bad.manifest.copy(); manifest['history_number'] = 'invalid'
    (bad.path / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    listed = service.list(p)
    assert len(listed) == 2
    assert next(x for x in listed if x.path == bad.path).error
    assert not next(x for x in listed if x.path == good.path).error
    new = service.create(p, s, '11-15')
    assert new.manifest['history_number'] == 3


def test_history_numbers_survive_status_rename_and_other_profile(history):
    from dataclasses import replace
    service, p, s = history
    first = service.create(p, s, '1-5')
    renamed = service.rename(p, first.path, '6-10')
    service.set_review_status(p, renamed, 'ตรวจแล้ว')
    item = service.list(p)[0]
    assert item.manifest['history_number'] == first.manifest['history_number'] == 1
    other = replace(p, id='f' * 32)
    service.repo.save_profile(other)
    for file in s.files:
        source = service.repo.profile_dir(p.id) / file.path
        (service.repo.profile_dir(other.id) / file.path).write_bytes(source.read_bytes())
    snapshot = service.create(other, s, '1-5')
    assert snapshot.manifest['history_number'] == 1
    with pytest.raises(ValueError): service.delete(other, renamed)
    assert renamed.exists()


def test_history_delete_waits_for_snapshot_writer(history, monkeypatch):
    from threading import Thread, Event
    service, p, s = history
    old = service.create(p, s, '1-5')
    entered, release, deleted = Event(), Event(), Event()
    copy_file = service._copy_file
    def blocked_copy(*args):
        entered.set(); assert release.wait(5)
        return copy_file(*args)
    monkeypatch.setattr(service, '_copy_file', blocked_copy)
    errors = []
    def write():
        try: service.create(p, s, '6-10')
        except Exception as exc: errors.append(exc)
    def delete():
        try: service.delete(p, old.path); deleted.set()
        except Exception as exc: errors.append(exc)
    writer = Thread(target=write); writer.start(); assert entered.wait(5)
    deleter = Thread(target=delete); deleter.start()
    assert not deleted.wait(.1) and old.path.exists()
    release.set(); writer.join(5); deleter.join(5)
    assert not errors and deleted.is_set()
    assert service.list(p)[0].manifest['chapter_range'] == '6-10'


def test_startup_reminder_does_not_open_dialog_for_matching_hash(window, monkeypatch):
    w, p, ws, errors = window
    path = w.repo.profile_dir(p.id) / 'a.txt'
    w._record_successful_export(p.id, path, hashlib.sha256(path.read_bytes()).digest(), path)
    w._mark_export_pending(p.id, path)
    monkeypatch.setattr(QMessageBox, 'exec', lambda *a: pytest.fail('False startup warning'))
    w._startup_export_reminder_shown = False
    w._show_startup_export_reminder(p.id)
    assert not w._startup_export_reminder_shown


def test_real_saved_change_remains_pending_after_restart(window):
    w, p, ws, errors = window
    path = w.repo.profile_dir(p.id) / 'a.txt'
    w._record_successful_export(p.id, path, hashlib.sha256(path.read_bytes()).digest(), path)
    editor = ws.editor.open_file(path); editor.insertPlainText('new translation')
    ws.editor._autosave_editor(editor)
    w._export_status_cache.clear()
    assert w._pending_export_for_profile(p.id) == path


def test_copy_busy_job_does_not_publish_clipboard(window):
    from threading import Event
    w, p, ws, errors = window
    release = Event()
    w.run_history_job(lambda: release.wait(5), lambda _: None)
    QApplication.clipboard().setText('unrelated')
    old = w.si
    w.copy_step()
    assert w.si == old and QApplication.clipboard().text() == 'unrelated'
    release.set(); wait_until(lambda: not w.history_busy())


@pytest.mark.parametrize('appearance', ['Light', 'Dark'])
@pytest.mark.parametrize('width', [420, 1000])
def test_compact_history_geometry_themes(window, appearance, width):
    from PySide6.QtWidgets import QFrame
    from novel_workflow.theme import application_stylesheet
    w, p, ws, errors = window
    w.setStyleSheet(application_stylesheet(appearance))
    w.polish_history.create(p, p.workflow.steps[1], '322-323')
    w.open_polish_history(); wait_until(lambda: not w.history_busy())
    page = w._utility_pages['polish-history:' + p.id]
    page.setParent(None); page.resize(width, 400); page.show(); QApplication.processEvents()
    try:
        row = page.findChild(QFrame, 'polishHistoryRow')
        buttons = row.findChildren(QPushButton)
        assert row.height() <= (100 if width < 600 else 60)
        assert all(b.geometry().right() < row.width() for b in buttons)
        assert all(not a.geometry().intersects(b.geometry()) for i, a in enumerate(buttons) for b in buttons[i + 1:])
    finally: page.hide(); page.setParent(w)


def test_history_visible_numbers_renumber_after_delete_without_mutating_ids(window, monkeypatch, tmp_path):
    import re
    from PySide6.QtWidgets import QLabel
    import novel_workflow.recycle_bin as recycle
    w, profile, ws, errors = window
    step = profile.workflow.steps[1]
    for span in ('320-321', '322-323', '324'):
        w.polish_history.create(profile, step, span)
    w.open_polish_history()
    wait_until(lambda: not w.history_busy())
    page = w._utility_pages['polish-history:' + profile.id]
    def active_rows():
        # Qt defers deleteLater(): inspect layout rows, not all children.
        return [page.card_layout.itemAt(index).widget()
                for index in range(page.card_layout.count())
                if page.card_layout.itemAt(index).widget() is not None]
    def titles():
        return [label.text() for row in active_rows()
                for label in row.findChildren(QLabel, 'historyRangeTitle')]
    def numbers():
        return [label.text() for row in active_rows()
                for label in row.findChildren(QLabel, 'historySequenceNumber')]
    assert titles() == ['บท 324', 'บท 322–323', 'บท 320–321']
    assert numbers() == ['1', '2', '3']
    original_ids = {s.manifest['snapshot_id']: s.manifest['history_number'] for s in page.snapshots}
    trash_folder = tmp_path / 'recycled'
    monkeypatch.setattr(recycle, 'recycle_snapshot', lambda folder: Path(folder).rename(trash_folder))
    buttons = page.findChildren(QPushButton, 'polishHistoryDelete')
    buttons[1].click()
    wait_until(lambda: not w.history_busy())
    # Page refresh may queue its own worker on the next event-loop tick.
    wait_until(lambda: len(page.snapshots) == 2)
    assert titles() == ['บท 324', 'บท 320–321']
    assert numbers() == ['1', '2']
    for snap in page.snapshots:
        assert snap.manifest['history_number'] == original_ids[snap.manifest['snapshot_id']]


def test_copy_intentionally_revised_history_payload_with_explicit_confirmation(window, monkeypatch):
    w, profile, ws, errors = window
    step = profile.workflow.steps[1]
    snapshot = w.polish_history.create(profile, step, '325')
    entry = snapshot.manifest['files'][0]
    payload = snapshot.path / entry['snapshot_path']
    edited = payload.read_bytes() + b' corrected'
    payload.write_bytes(edited)
    w.open_polish_history()
    wait_until(lambda: not w.history_busy())
    page = w._utility_pages['polish-history:' + profile.id]
    assert page.snapshots[0].error
    monkeypatch.setattr(QMessageBox, 'question', lambda *_args: QMessageBox.Yes)
    button = page.findChildren(QPushButton, 'polishHistoryCopy')[0]
    assert button.isEnabled()
    button.click()
    wait_until(lambda: not w.history_busy())
    clipboard = [Path(url.toLocalFile()) for url in QApplication.clipboard().mimeData().urls()]
    assert any(item.read_bytes() == edited for item in clipboard)
    assert not w.polish_history.list(profile)[0].error



@pytest.mark.parametrize('appearance', ['Light', 'Dark'])
@pytest.mark.parametrize('width', [420, 1000])
def test_history_number_sits_immediately_before_copy_in_both_themes(window, appearance, width):
    from PySide6.QtWidgets import QFrame, QLabel
    from novel_workflow.theme import application_stylesheet
    w, profile, ws, errors = window
    w.setStyleSheet(application_stylesheet(appearance))
    w.polish_history.create(profile, profile.workflow.steps[1], '322-323')
    w.open_polish_history()
    wait_until(lambda: not w.history_busy())
    page = w._utility_pages['polish-history:' + profile.id]
    page.setParent(None); page.resize(width, 400); page.show(); QApplication.processEvents()
    try:
        row = page.findChild(QFrame, 'polishHistoryRow')
        chapter = row.findChild(QLabel, 'historyRangeTitle')
        ordinal = row.findChild(QLabel, 'historySequenceNumber')
        copy = row.findChild(QPushButton, 'polishHistoryCopy')
        assert chapter.text() == 'บท 322–323'
        assert ordinal.text() == '1'
        assert ordinal.objectName() == 'historySequenceNumber'
        # The number is now a compact leading marker, not a distant badge.
        assert ordinal.width() == 36
        assert ordinal.height() == 36
        assert 'font-size: 12pt; font-weight: 700' in w.styleSheet()
        assert ordinal.geometry().right() < chapter.geometry().left()
        assert chapter.geometry().right() < copy.geometry().left()
        assert copy.geometry().left() - chapter.geometry().right() < 90
        assert ordinal.geometry().left() >= 0
        assert ordinal.geometry().right() < row.width()
        assert copy.geometry().right() < row.width()
        assert row.height() <= (100 if width < 600 else 60)
    finally:
        page.hide(); page.setParent(w)


def test_history_numerical_sort_requires_selection_and_persists_per_novel(window):
    from PySide6.QtWidgets import QLabel, QComboBox
    from novel_workflow.polish_history_page import PolishHistoryPage
    w, profile, _ws, errors = window
    step = profile.workflow.steps[1]
    for chapter in ('430', '429', '403-404'):
        w.polish_history.create(profile, step, chapter)
    w.open_polish_history()
    wait_until(lambda: not w.history_busy())
    page = w._utility_pages['polish-history:' + profile.id]
    selector = page.findChild(QComboBox, 'polishHistorySort')
    def shown():
        rows = [page.card_layout.itemAt(i).widget()
                for i in range(page.card_layout.count())
                if page.card_layout.itemAt(i).widget() is not None]
        return [
            (row.findChild(QLabel, 'historySequenceNumber').text(),
             row.findChild(QLabel, 'historyRangeTitle').text())
            for row in rows
        ]
    # Default stays newest-first until the reader chooses a sort.
    assert selector.currentData() == 'recent'
    assert shown() == [('1', 'บท 403–404'), ('2', 'บท 429'), ('3', 'บท 430')]
    selector.setCurrentIndex(selector.findData('chapter_desc'))
    assert shown() == [('1', 'บท 430'), ('2', 'บท 429'), ('3', 'บท 403–404')]
    selector.setCurrentIndex(selector.findData('chapter_asc'))
    assert shown() == [('1', 'บท 403–404'), ('2', 'บท 429'), ('3', 'บท 430')]
    assert w.repo.load_settings().history_sort_modes[profile.id] == 'chapter_asc'
    # New History window uses persisted selection for this same profile.
    next_page = PolishHistoryPage(w, profile)
    next_page.snapshots = list(page.snapshots)
    next_page.render()
    assert next_page.sort_selector.currentData() == 'chapter_asc'
    assert [s.manifest['chapter_range'] for s in next_page._ordered_snapshots()] == [
        '403-404', '429', '430'
    ]
    next_page.deleteLater()
    assert not errors


def test_history_manual_move_and_copy_target_remain_stable(window):
    from PySide6.QtWidgets import QLabel, QComboBox, QToolButton
    w, profile, _ws, errors = window
    step = profile.workflow.steps[1]
    for chapter in ('430', '429', '403-404'):
        w.polish_history.create(profile, step, chapter)
    w.open_polish_history()
    wait_until(lambda: not w.history_busy())
    page = w._utility_pages['polish-history:' + profile.id]
    selector = page.findChild(QComboBox, 'polishHistorySort')
    selector.setCurrentIndex(selector.findData('chapter_desc'))
    selector.setCurrentIndex(selector.findData('manual'))
    def row_list():
        return [page.card_layout.itemAt(i).widget()
                for i in range(page.card_layout.count())
                if page.card_layout.itemAt(i).widget() is not None]
    assert [row.findChild(QLabel, 'historyRangeTitle').text() for row in row_list()] == [
        'บท 430', 'บท 429', 'บท 403–404'
    ]
    middle = row_list()[1]
    middle.findChild(QToolButton, 'polishHistoryMoveUp').click()
    assert [row.findChild(QLabel, 'historyRangeTitle').text() for row in row_list()] == [
        'บท 429', 'บท 430', 'บท 403–404'
    ]
    assert [row.findChild(QLabel, 'historySequenceNumber').text() for row in row_list()] == [
        '1', '2', '3'
    ]
    assert w.repo.load_settings().history_manual_order[profile.id] == [
        page._snapshot_id(s) for s in page._ordered_snapshots()
    ]
    page.search.setText('429')
    assert len(row_list()) == 1
    assert not row_list()[0].findChild(QToolButton, 'polishHistoryMoveUp').isEnabled()
    page.search.clear()
    assert row_list()[0].findChild(QPushButton, 'polishHistoryCopy').accessibleName().startswith('ลำดับ 1 บท 429')
    assert not errors
