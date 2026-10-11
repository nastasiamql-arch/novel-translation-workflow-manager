import json
import zipfile
from pathlib import Path

import pytest

from novel_workflow.models import NovelProfile, Workflow, WorkflowStep, StepFile
from novel_workflow.services import AssemblyService
from novel_workflow.storage import ProjectRepository
from novel_workflow.polish_history import PolishHistory, RangeRequired, parse_range


@pytest.fixture
def history(tmp_path):
    repo = ProjectRepository(tmp_path / 'data')
    main = tmp_path / 'novel'; main.mkdir()
    context = main / 'Context.md'; context.write_bytes(b'old context\r\n\r\n')
    step = WorkflowStep(name='Custom polish')
    profile = NovelProfile(main_folder=str(main), context_path=str(context),
                           workflow=Workflow([step]))
    repo.save_profile(profile)
    for index, (name, data) in enumerate([
        ('Prompt.md', b'\xef\xbb\xbfPrompt\t \r\n\r\n'),
        ('\u8bcd\u6c47.txt', 'ไทย\t中文\t日本語\n\n'.encode()),
        ('rules.json', b'{"value": 1}\n'), ('binary.dat', bytes(range(256))),
    ]):
        path = repo.profile_dir(profile.id) / name; path.write_bytes(data)
        step.files.append(StepFile(path=name, enabled=index != 1, order=index))
    return PolishHistory(repo, AssemblyService(repo)), profile, step


def test_lossless_only_linked_attachments_and_restart(history):
    service, profile, step = history
    snapshot = service.create(profile, step, '6-10')
    assert snapshot.path.is_relative_to(Path(profile.main_folder) / 'Polish History')
    assert snapshot.manifest['file_count'] == 4
    assert [f['enabled'] for f in snapshot.manifest['files']] == [True, False, True, True]
    for entry, path in zip(snapshot.manifest['files'], service.validate(profile, snapshot.path)):
        assert path.read_bytes() == Path(entry['original_path']).read_bytes()
    Path(profile.context_path).write_bytes(b'new context')
    restarted = PolishHistory(service.repo, service.assembler)
    old = restarted.list(profile)[0]
    assert old.manifest['chapter_range'] == '6-10'
    assert all(path.read_bytes() != b'old context\r\n\r\n' for path in restarted.validate(profile, old.path))
    assert old.manifest['context_hash'] is None
    assert profile.verified_goal_count == 0 and profile.verified_export_history == []


def test_dedup_range_and_content_versions(history):
    service, p, s = history
    first = service.create(p, s, '1-5')
    assert first.path.name == 'Custom polish บท 1-5'
    assert service.create(p, s, '1-5').path == first.path
    second = service.create(p, s, '6-10')
    assert second.path != first.path
    Path(p.context_path).write_bytes(b'changed')
    assert service.create(p, s, '6-10').path == second.path
    assert len(service.list(p)) == 2


def test_zip_persistent_and_payload_only(history):
    service, p, s = history
    snap = service.create(p, s, '25-31')
    paths = service.clipboard_paths(p, snap.path, zipped=False)
    assert len(paths) == 4 and all(x.is_file() for x in paths)
    archive = service.clipboard_paths(p, snap.path, zipped=True)[0]
    with zipfile.ZipFile(archive) as z:
        assert len(z.namelist()) == 4
        assert 'manifest.json' not in z.namelist()
        assert sorted(z.read(n) for n in z.namelist()) == sorted(x.read_bytes() for x in paths)
    del service
    assert archive.is_file() and all(x.is_file() for x in paths)


def test_context_not_duplicated_and_filename_collision(history, tmp_path):
    service, p, s = history
    external = tmp_path / 'Prompt.md'; external.write_bytes(b'external')
    s.files += [StepFile(reference_type='external_file', path=str(external)),
                StepFile(reference_type='external_file', path=p.context_path, enabled=False)]
    snap = service.create(p, s, '21-24')
    files = service.validate(p, snap.path)
    assert len(files) == 6
    assert len({str(f).casefold() for f in files}) == 6
    assert sum(f['is_context'] for f in snap.manifest['files']) == 1


def test_folder_and_dynamic_reference(history):
    service, p, s = history
    root = service.repo.profile_dir(p.id)
    folder = root / 'references'; (folder / 'sub').mkdir(parents=True)
    (folder / 'sub' / 'a.md').write_bytes(b'folder')
    (root / 'reviewed' / 'chapter_1.txt').write_text('Chapter 100\ntext\nChapter 120\ntext')
    s.files += [StepFile(path='references'), StepFile(reference_type='dynamic', dynamic_reference='CURRENT_REVIEWED_CHAPTER')]
    snap = service.create(p, s)
    assert snap.manifest['chapter_range'] == '100-120'
    assert any(f['snapshot_path'].endswith('references/sub/a.md') for f in snap.manifest['files'])


def test_never_infer_chapters_from_context(history):
    service, p, s = history
    Path(p.context_path).write_text('Chapter 999\ntext')
    with pytest.raises(RangeRequired): service.create(p, s)
    assert service.list(p) == []


def test_export_may_keep_unresolved_range_and_later_assign_it(history):
    service, p, s = history
    pending = service.create(p, s, allow_unresolved=True)
    assert pending.manifest['chapter_range'] is None
    assert pending.manifest['review_status'] == 'รอตรวจ'
    assert pending.path.name.startswith('Custom polish รอระบุช่วงบท')
    assert len(service.validate(p, pending.path)) == 4
    updated = service.rename(p, pending.path, '101-150')
    assert updated.name == 'Custom polish บท 101-150'
    assert service.list(p)[0].manifest['chapter_range'] == '101-150'
    service.set_review_status(p, updated, 'ตรวจแล้ว')
    assert service.list(p)[0].manifest['review_status'] == 'ตรวจแล้ว'


def test_new_save_of_identical_snapshot_returns_it_to_pending(history):
    service, p, s = history
    saved = service.create(p, s, '6-10')
    service.set_review_status(p, saved.path, 'ตรวจแล้ว')
    again = service.create(p, s, '6-10')
    assert again.path == saved.path
    assert again.manifest['review_status'] == 'รอตรวจ'


@pytest.mark.parametrize('label', ['1-5', '6-10', '21-24', '25-31', '100-120', '100000-100123', '6'])
def test_unlimited_unequal_ranges(label):
    assert parse_range(label) == label


@pytest.mark.parametrize('label', ['5-1', '0', 'one', '1-2-3', '../6', ''])
def test_reject_invalid_range(label):
    with pytest.raises(ValueError): parse_range(label)


@pytest.mark.parametrize('fault', ['missing', 'hash', 'traversal', 'count', 'schema', 'type'])
def test_validate_rejects_corruption(history, fault):
    service, p, s = history
    snap = service.create(p, s, '6-10')
    manifest = snap.manifest
    payload = snap.path / manifest['files'][0]['snapshot_path']
    if fault == 'missing': payload.unlink()
    elif fault == 'hash':
        data = payload.read_bytes()
        payload.write_bytes(bytes([data[0] ^ 1]) + data[1:])
    elif fault == 'traversal': manifest['files'][0]['snapshot_path'] = '../outside'
    elif fault == 'count': manifest['file_count'] = 99
    elif fault == 'schema': manifest['schema_version'] = 999
    else: manifest['files'][0]['enabled'] = 'false'
    (snap.path / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises((ValueError, OSError)): service.clipboard_paths(p, snap.path, zipped=False)
    assert service.list(p)[0].error


def test_missing_source_leaves_no_success_and_preserves_originals(history):
    service, p, s = history
    s.files.append(StepFile(path='missing.txt', enabled=False))
    with pytest.raises(FileNotFoundError): service.create(p, s, '6-10')
    assert not any(not x.error for x in service.list(p))
    assert Path(p.context_path).read_bytes() == b'old context\r\n\r\n'


def test_no_main_folder(history):
    service, p, s = history; p.main_folder = ''
    with pytest.raises(ValueError, match='โฟลเดอร์หลัก'): service.create(p, s, '6-10')


def test_profile_and_stable_step_isolation(history):
    service, p, s = history
    first = service.create(p, s, '6-10')
    s.name = 'Renamed'; p.workflow.steps.insert(0, WorkflowStep())
    assert service.create(p, s, '6-10').path == first.path
    other = NovelProfile(main_folder=p.main_folder)
    assert service.list(other) == []
    with pytest.raises(ValueError): service.validate(other, first.path)


def test_rename_keeps_bytes_and_old_metadata_backup(history):
    service, p, s = history; snap = service.create(p, s, '6-10')
    before = [x.read_bytes() for x in service.validate(p, snap.path)]
    renamed = service.rename(p, snap.path, '11-15')
    assert service.list(p)[0].manifest['chapter_range'] == '11-15'
    assert [x.read_bytes() for x in service.validate(p, renamed)] == before
    assert list(renamed.glob('manifest.*.bak'))


def test_failed_write_and_staging_are_visible_not_success(history, monkeypatch):
    service, p, s = history
    original = Path.open
    def deny(path, *args, **kwargs):
        if '.staging-' in str(path) and args and args[0] == 'wb': raise PermissionError('denied')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', deny)
    with pytest.raises(PermissionError): service.create(p, s, '6-10')
    assert all(item.error for item in service.list(p))
    assert service.list(p)


def test_source_changed_while_copying_is_not_published(history, monkeypatch):
    service, p, s = history
    original = service._copy_file
    def change(source, destination):
        result = original(source, destination)
        source.write_bytes(b'changed externally')
        return result
    monkeypatch.setattr(service, '_copy_file', change)
    with pytest.raises(OSError): service.create(p, s, '6-10')
    assert all(x.error for x in service.list(p))


def test_symlink_and_traversal_blocked(history, tmp_path):
    service, p, s = history
    s.files.append(StepFile(path='../escape'))
    with pytest.raises(ValueError): service.create(p, s, '6-10')
    s.files.pop()
    link = service.repo.profile_dir(p.id) / 'link'
    try: link.symlink_to(tmp_path, target_is_directory=True)
    except OSError: pytest.skip('Symlink privileges unavailable')
    s.files.append(StepFile(path='link'))
    with pytest.raises(ValueError): service.create(p, s, '6-10')


def test_repair_trailing_comma_only_in_memory(history):
    service, p, s = history; snap = service.create(p, s, '6-10')
    path = snap.path / 'manifest.json'
    raw = path.read_text(encoding='utf-8').rstrip(); raw = raw[:-1] + ',}'
    path.write_text(raw, encoding='utf-8')
    assert len(service.validate(p, snap.path)) == 4
    assert path.read_text(encoding='utf-8') == raw


def test_metadata_preserves_duplicate_links_and_status(history):
    service, p, s = history
    s.files.append(StepFile(path='Prompt.md', enabled=False, order=10))
    snap = service.create(p, s, '6-10')
    assert len(snap.manifest['attachments']) == 5
    assert snap.manifest['attachments'][-1]['enabled'] is False
    assert snap.manifest['file_count'] == 4
    s.files[-1].enabled = True
    assert service.create(p, s, '6-10').path != snap.path


def test_manifest_repair_does_not_modify_comma_in_strings(history):
    service, p, s = history
    s.name = 'name with ,} text'
    snap = service.create(p, s, '6-10')
    manifest = snap.path / 'manifest.json'
    raw = manifest.read_text(encoding='utf-8').rstrip()[:-1] + ',}'
    manifest.write_text(raw, encoding='utf-8')
    assert service.list(p)[0].manifest['step_name'] == 'name with ,} text'
    assert manifest.read_text(encoding='utf-8') == raw


def test_delete_refuses_payload_still_on_clipboard(history):
    service, p, s = history; snap = service.create(p, s, '1-5')
    files = service.validate(p, snap.path)
    with pytest.raises(ValueError, match='Clipboard'): service.delete(p, snap.path, files)
    assert all(path.is_file() for path in files)
    service.delete(p, snap.path)
    assert service.list(p) == []


@pytest.mark.parametrize('headings', ['บทที่ 6\ntext\nบทที่ 10\ntext', 'Chapter 6\ntext\nChapter 10\ntext', '第6章\ntext\n第10章\ntext'])
def test_chapter_range_from_actual_content(history, headings):
    service, p, s = history
    source = service.repo.profile_dir(p.id) / 'Translator.txt'
    source.write_text(headings, encoding='utf-8')
    s.files.append(StepFile(path=source.name))
    assert service.create(p, s).manifest['chapter_range'] == '6-10'


def test_packaged_upgrade_probe_verifies_history_bytes(history, monkeypatch):
    import runpy
    import sys
    service, p, s = history
    snap = service.create(p, s, '6-10'); service.repo.save_profile(p)
    profile_path = service.repo.profile_dir(p.id) / 'profile.json'
    monkeypatch.setattr(sys, 'argv', ['Palantir', '--check-runtime', '--history-profile', str(profile_path)])
    probe = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'run_app.py'))['_check_packaged_qt_runtime']
    assert probe() == 0
    (snap.path / snap.manifest['files'][0]['snapshot_path']).write_bytes(b'corrupted after upgrade')
    assert probe() == 1


def test_malformed_metadata_remains_listable(history):
    service, p, s = history; snap = service.create(p, s, '1-5')
    manifest = snap.manifest; manifest['created_at'] = 123; manifest['chapter_range'] = 456
    (snap.path / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    assert service.list(p)[0].error


def test_schema_boolean_is_not_schema_one(history):
    service, p, s = history; snap = service.create(p, s, '1-5')
    manifest = snap.manifest; manifest['schema_version'] = True
    (snap.path / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(ValueError): service.validate(p, snap.path)


def test_windows_junction_blocked_before_traversal(history, tmp_path):
    import subprocess
    import sys
    if sys.platform != 'win32': pytest.skip('Windows junction test')
    service, p, s = history
    folder = service.repo.profile_dir(p.id) / 'folder'; folder.mkdir()
    junction = folder / 'loop'
    result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(junction), str(folder)], capture_output=True)
    assert result.returncode == 0, result.stderr
    s.files.append(StepFile(path='folder'))
    try:
        with pytest.raises(ValueError, match='junction'): service.create(p, s, '1-5')
    finally:
        junction.rmdir()  # Remove the junction itself, never its target.


def test_unreadable_subfolder_never_silently_omitted(history, monkeypatch):
    import os
    service, p, s = history
    folder = service.repo.profile_dir(p.id) / 'folder'; folder.mkdir()
    (folder / 'visible.txt').write_bytes(b'visible')
    s.files.append(StepFile(path='folder'))
    walk = os.walk
    def unreadable(path, *args, **kwargs):
        if Path(path) == folder:
            if kwargs.get('onerror'): kwargs['onerror'](PermissionError('unreadable subfolder'))
            return iter([(str(folder), [], ['visible.txt'])])
        return walk(path, *args, **kwargs)
    monkeypatch.setattr(os, 'walk', unreadable)
    with pytest.raises(PermissionError): service.create(p, s, '6-10')
    assert not any(not x.error for x in service.list(p))


def test_damaged_latest_metadata_does_not_block_new_snapshot(history):
    service, p, s = history; snap = service.create(p, s, '6-10')
    manifest = snap.manifest; manifest.pop('chapter_range')
    (snap.path / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    fresh = service.create(p, s, '6-10')
    assert fresh.path != snap.path
    items = service.list(p)
    assert len(items) == 2 and sum(bool(x.error) for x in items) == 1

def test_upgrade_fixture_accepts_unicode_history_on_legacy_windows_console(history):
    import os
    import subprocess
    import sys
    service, profile, _ = history
    folder = service.repo.profile_dir(profile.id)
    (folder / 'source' / 'chapter_1.txt').write_bytes('ไทย\n\n中文'.encode('utf-8'))
    service.repo.save_profile(profile)
    result = subprocess.run(
        [sys.executable, str(Path(__file__).with_name('upgrade_history_fixture.py')),
         str(folder / 'profile.json'), profile.main_folder],
        env={**os.environ, 'PYTHONIOENCODING': 'cp1252'}, capture_output=True)
    assert result.returncode == 0, result.stderr.decode('cp1252', errors='replace')
    snapshots = service.list(service.repo.list_profiles()[0])
    assert len(snapshots) == 1 and not snapshots[0].error
