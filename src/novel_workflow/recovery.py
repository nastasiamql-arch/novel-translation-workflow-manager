"""Bounded file recovery and rollback for multi-file replacement.

Backups live beside the user's documents, never in application credentials.
A failed commit restores replaced destinations before reporting failure.
"""
from pathlib import Path
import os
import tempfile
import shutil
import time
import uuid

BACKUP_LIMIT = 10


def backup_file(path):
    path = Path(path)
    if not path.exists(): return None
    directory = path.parent / '.palantir-recovery'
    directory.mkdir(exist_ok=True)
    # A digest keeps very long document names within Windows path limits.
    import hashlib
    key = hashlib.sha256(path.name.encode('utf-8')).hexdigest()[:16]
    backup = directory / f'{key}-{time.time_ns()}-{uuid.uuid4().hex[:8]}.bak'
    try:
        with path.open('rb') as source, backup.open('xb') as output:
            shutil.copyfileobj(source, output)
            output.flush(); os.fsync(output.fileno())
    except OSError:
        backup.unlink(missing_ok=True)
        raise
    for old in sorted(directory.glob(f'{key}-*.bak'), reverse=True)[BACKUP_LIMIT:]:
        old.unlink()
    return backup


def commit_staged(staged_files, commit_metadata=None):
    destinations = [Path(path).resolve() for path, _ in staged_files]
    if len(set(destinations)) != len(destinations):
        raise ValueError('TXT และ Context ต้องเป็นคนละไฟล์')
    backups = {path: backup_file(path) for path in destinations}
    replaced = []
    try:
        for destination, staged in staged_files:
            destination = Path(destination).resolve()
            os.replace(staged, destination)
            replaced.append(destination)
        if commit_metadata: commit_metadata()
    except Exception as original:
        errors = []
        for destination in reversed(replaced):
            try:
                backup = backups[destination]
                if backup is None: destination.unlink(missing_ok=True)
                else:
                    fd, name = tempfile.mkstemp(dir=destination.parent, suffix='.restore')
                    os.close(fd)
                    try:
                        shutil.copyfile(backup, name)
                        os.replace(name, destination)
                    finally: Path(name).unlink(missing_ok=True)
            except OSError as error: errors.append(str(error))
        if errors:
            raise OSError(f'{original}; กู้คืนอัตโนมัติไม่สำเร็จ: {errors}. ดู .palantir-recovery') from original
        raise


def restore_backup(destination, backup):
    destination, backup = Path(destination), Path(backup)
    if not backup.is_file(): raise OSError('ไม่พบไฟล์สำรอง')
    fd, name = tempfile.mkstemp(dir=destination.parent, suffix='.restore')
    try:
        with os.fdopen(fd, 'wb') as output, backup.open('rb') as source:
            shutil.copyfileobj(source, output); output.flush(); os.fsync(output.fileno())
        # Stage the chosen copy before pruning, which may remove the oldest backup.
        backup_file(destination)
        os.replace(name, destination)
    finally: Path(name).unlink(missing_ok=True)
