import json
from pathlib import Path
from unittest.mock import patch

import pytest
from novel_workflow.models import NovelProfile, Workflow, WorkflowStep, StepFile
from test_polish_history import history


def legacy(service, profile, step, span='6-10'):
    snapshot = service.create(profile, step, span)
    parent = service.root(profile) / f'{step.id}-{profile.id}'
    parent.mkdir(exist_ok=True)
    path = parent / f'บท {span}__20261012-040000__{snapshot.manifest["snapshot_id"]}'
    snapshot.path.rename(path)
    return path


def test_flat_thai_name_without_visible_ids(history):
    service, p, s = history; s.name = 'ตรวจคำแปล'
    snap = service.create(p, s, '6-10')
    assert snap.path == service.root(p) / 'ตรวจคำแปล-บท 6-10'
    assert s.id not in snap.path.name and p.id not in snap.path.name
    assert len(snap.path.relative_to(service.root(p)).parts) == 1


def test_versions_and_same_second_collisions_never_overwrite(history):
    service, p, s = history; s.name = 'ตรวจคำแปล'
    first = service.create(p, s, '6-10')
    assert service.create(p, s, '6-10').path == first.path
    stamp = first.manifest['created_at']
    from datetime import datetime
    with patch('novel_workflow.polish_history.datetime') as clock:
        clock.now.return_value = datetime.fromisoformat(stamp)
        clock.fromisoformat = datetime.fromisoformat
        for value in (b'second', b'third'):
            Path(p.context_path).write_bytes(value)
            service.create(p, s, '6-10')
    paths = [x.path for x in service.list(p)]
    assert len(paths) == 3 and first.path in paths
    assert any(x.name.endswith('(2)') for x in paths)
    assert all(p.id not in x.name and s.id not in x.name for x in paths)


def test_verified_legacy_migrates_byte_for_byte_and_copies(history):
    service, p, s = history; s.name = 'ตรวจคำแปล'
    old = legacy(service, p, s)
    before = {str(x.relative_to(old)): x.read_bytes() for x in old.rglob('*') if x.is_file()}
    assert len(service.clipboard_paths(p, old, zipped=False)) == 5
    items = service.list(p)
    assert len(items) == 1 and not items[0].error
    new = items[0].path
    assert new.name == 'ตรวจคำแปล-บท 6-10' and new.parent == service.root(p)
    assert not old.exists()
    assert before == {str(x.relative_to(new)): x.read_bytes() for x in new.rglob('*') if x.is_file()}
    assert len(service.clipboard_paths(p, new, zipped=False)) == 5
    assert service.clipboard_paths(p, new, zipped=True)[0].is_file()
    assert service.list(p)[0].path == new


def test_clipboard_defers_migration_and_range_rename(history):
    service, p, s = history
    old = legacy(service, p, s)
    urls = service.clipboard_paths(p, old, zipped=False)
    item = service.list(p, clipboard_paths=urls)[0]
    assert item.path == old and item.warning and not item.error
    assert all(x.exists() for x in urls)
    with pytest.raises(ValueError, match='Clipboard'):
        service.rename(p, old, '11-15', clipboard_paths=urls)
    assert service.validate(p, old)
    assert service.list(p)[0].path.parent == service.root(p)


def test_failed_migration_preserves_legacy_and_reports_status(history, monkeypatch):
    service, p, s = history; old = legacy(service, p, s)
    raw = (old / 'manifest.json').read_bytes()
    import novel_workflow.polish_history as module
    monkeypatch.setattr(module.os, 'rename', lambda *args: (_ for _ in ()).throw(PermissionError('denied')))
    item = service.list(p)[0]
    assert item.path == old and item.warning and not item.error
    assert (old / 'manifest.json').read_bytes() == raw and service.validate(p, old)


def test_failed_post_move_verification_rolls_back(history, monkeypatch):
    service, p, s = history; old = legacy(service, p, s)
    original = service.validate
    def fail_new(profile, path):
        if Path(path).parent == service.root(p): raise OSError('verification interrupted')
        return original(profile, path)
    monkeypatch.setattr(service, 'validate', fail_new)
    item = service.list(p)[0]
    assert item.path == old and item.warning and old.exists()
    assert len(list(old.parent.iterdir())) == 1


def test_corrupt_and_wrong_step_legacy_never_migrates(history):
    service, p, s = history; old = legacy(service, p, s)
    manifest = json.loads((old / 'manifest.json').read_text(encoding='utf-8'))
    manifest['step_id'] = 'another-step'
    (old / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    assert service.list(p)[0].error and old.exists()


def test_range_rename_updates_directory_and_only_range_metadata(history):
    service, p, s = history; s.name = 'ตรวจคำแปล'
    old = service.create(p, s, '6-10')
    payload = [x.read_bytes() for x in service.validate(p, old.path)]
    new = service.rename(p, old.path, '11-15')
    assert new.name == 'ตรวจคำแปล-บท 11-15' and not old.path.exists()
    item = service.list(p)[0]
    assert item.path == new and item.manifest['chapter_range'] == '11-15'
    assert payload == [x.read_bytes() for x in service.validate(p, new)]
    assert {k:v for k,v in item.manifest.items() if k != 'chapter_range'} == {k:v for k,v in old.manifest.items() if k != 'chapter_range'}


def test_shared_main_folder_uses_readable_profile_suffix_and_stays_isolated(history):
    service, p, s = history; s.name = 'ตรวจคำแปล'; p.name = 'เรื่องแรก'
    first = service.create(p, s, '6-10')
    q = NovelProfile(name='เรื่องที่สอง', main_folder=p.main_folder, context_path=p.context_path,
                     workflow=Workflow([WorkflowStep(name=s.name)]))
    service.repo.save_profile(q)
    q.workflow.steps[0].files = [StepFile(reference_type='external_file', path=p.context_path)]
    other = service.create(q, q.workflow.steps[0], '6-10')
    assert 'เรื่องที่สอง' in other.path.name
    assert [x.path for x in service.list(p)] == [first.path]
    assert [x.path for x in service.list(q)] == [other.path]
    with pytest.raises(ValueError): service.validate(q, first.path)


@pytest.mark.parametrize('name', ['CON', 'NUL.', '../ตรวจ:คำแปล/中文 日本語', 'ไทย' * 120])
def test_safe_unicode_windows_folder_names(history, name):
    service, p, s = history; s.name = name
    snap = service.create(p, s, '6-10')
    assert snap.path.parent == service.root(p)
    assert not any(c in snap.path.name for c in '/\\:*?"<>|')
    assert not snap.path.name.endswith((' ', '.')) and len(snap.path.name) <= 180
    assert service.validate(p, snap.path)

def test_legacy_dedup_does_not_move_active_source_paths(history):
    service, p, s = history; old = legacy(service, p, s)
    assert service.create(p, s, '6-10').path == old
    assert old.exists()
    assert len(service.list(p, verify=False)) == 1


def test_range_rename_failure_restores_raw_manifest_and_original_folder(history, monkeypatch):
    service, p, s = history; snap = service.create(p, s, '6-10')
    raw = (snap.path / 'manifest.json').read_bytes()
    import novel_workflow.polish_history as module
    monkeypatch.setattr(module.os, 'rename', lambda *args: (_ for _ in ()).throw(PermissionError('denied')))
    with pytest.raises(PermissionError): service.rename(p, snap.path, '11-15')
    assert (snap.path / 'manifest.json').read_bytes() == raw
    assert service.validate(p, snap.path)


def test_restart_finishes_interrupted_range_directory_rename(history):
    service, p, s = history; snap = service.create(p, s, '6-10')
    manifest = dict(snap.manifest); manifest['chapter_range'] = '11-15'
    (snap.path / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    item = service.list(p)[0]
    assert not item.error and item.path.name == 'Custom polish-บท 11-15'
    assert not snap.path.exists() and service.validate(p, item.path)


def test_clipboard_blocks_flat_folder_rename_without_metadata_changes(history):
    service, p, s = history; snap = service.create(p, s, '6-10')
    raw = (snap.path / 'manifest.json').read_bytes()
    urls = service.clipboard_paths(p, snap.path, zipped=False)
    with pytest.raises(ValueError, match='Clipboard'):
        service.rename(p, snap.path, '11-15', clipboard_paths=urls)
    assert (snap.path / 'manifest.json').read_bytes() == raw
    assert all(x.is_file() for x in urls)

def test_delete_flat_history_requires_known_profile_ownership(history):
    service, p, s = history; snap = service.create(p, s, '6-10')
    other = NovelProfile(main_folder=p.main_folder)
    with pytest.raises(ValueError): service.delete(other, snap.path)
    assert snap.path.is_dir()
    (snap.path / 'manifest.json').write_bytes(b'{ damaged metadata')
    with pytest.raises(ValueError): service.delete(p, snap.path)
    assert snap.path.is_dir()
