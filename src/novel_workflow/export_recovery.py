"""Recover a prepared Translator Export before loading its profile/statistics."""
import os
import shutil
import tempfile
from pathlib import Path
from .workflow_archive import _check_path


class ExportRecoveryConflict(ValueError):
    pass


def recover_export(repo, profile_id):
    from .storage import read_json
    from .recovery import replace_with_retry
    folder = repo.profile_dir(profile_id)
    journal_path = folder / 'translator_export_transaction.json'
    if not journal_path.exists(): return False
    journal = read_json(_check_path(journal_path), {})
    if journal.get('phase') not in {'prepared','committed'} or not isinstance(journal.get('entries'), list):
        raise ValueError('Invalid export recovery journal; data preserved')
    profile_path = _check_path(folder / 'profile.json')
    profile_entry = next((e for e in journal['entries'] if Path(e['path']).resolve() == profile_path), None)
    if not profile_entry or not profile_entry.get('backup'): raise ValueError('Missing original export profile')
    backup_path = Path(profile_entry['backup'])
    if ('..' in backup_path.parts or backup_path.parent.resolve() != folder.resolve()
            or not backup_path.name.endswith('.transaction-recovery')):
        raise ValueError('Unsafe original profile backup')
    backup_path = _check_path(backup_path)
    profile = read_json(backup_path, {})
    if profile.get('id') != profile_id: raise ValueError('Recovery profile ownership mismatch')
    from .workflow_archive import file_digest
    if journal['phase'] == 'prepared' and file_digest(profile_path).hex() not in (
            profile_entry.get('after_digest'), file_digest(backup_path).hex()):
        raise ExportRecoveryConflict(f'Export ค้างและ Profile ถูกแก้จากภายนอก · เก็บไฟล์ทั้งหมดไว้: {profile_path}')
    context = Path(profile.get('context_path') or '').expanduser().resolve()
    root = Path(profile.get('main_folder') or folder).expanduser().resolve()
    allowed = {context, profile_path, (folder / 'export_status.json').resolve()}
    export_folder = root / 'Context Exports'
    entries = []
    for entry in journal['entries']:
        path = Path(entry['path'])
        if '..' in path.parts: raise ValueError('Unsafe recovery path')
        path = path.resolve()
        if path not in allowed and not (path.parent == export_folder and path.suffix == '.txt'):
            raise ValueError('Recovery path outside this novel')
        if path.exists(): _check_path(path)
        else:
            ancestor = path.parent
            while not ancestor.exists(): ancestor = ancestor.parent
            _check_path(ancestor)
        backup = Path(entry['backup']) if entry.get('backup') else None
        if backup:
            backup = _check_path(backup)
            if backup.parent != path.parent or not backup.name.endswith('.transaction-recovery'):
                raise ValueError('Unsafe recovery backup')
        entries.append((path, backup, entry.get('after_digest')))
    if journal['phase'] == 'prepared':
        from .workflow_archive import file_digest
        for path, backup, expected in entries:
            if path.exists():
                current = file_digest(path).hex()
                original = file_digest(backup).hex() if backup else None
                if current not in (expected, original):
                    raise ExportRecoveryConflict(f'Export ค้างและพบไฟล์ที่แก้จากภายนอก · เก็บไฟล์ทั้งหมดไว้: {path}')
            elif backup:
                raise ExportRecoveryConflict(f'Export ค้างและไฟล์เดิมถูกย้ายหรือลบ · เก็บสำเนากู้คืนไว้: {path}')
        for path, backup, _ in reversed(entries):
            if backup is None: path.unlink(missing_ok=True)
            else:
                if path.is_file() and file_digest(path) == file_digest(backup): continue
                fd, name = tempfile.mkstemp(dir=path.parent, suffix='.restore')
                try:
                    with os.fdopen(fd,'wb') as output, backup.open('rb') as source:
                        shutil.copyfileobj(source,output); output.flush(); os.fsync(output.fileno())
                    replace_with_retry(name,path)
                finally: Path(name).unlink(missing_ok=True)
    journal_path.unlink()
    for _, backup, _ in entries:
        if backup: backup.unlink(missing_ok=True)
    return True
