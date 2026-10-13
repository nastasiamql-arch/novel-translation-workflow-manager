"""Bounded file recovery and rollback for multi-file replacement.

Backups live beside the user's documents, never in application credentials.
A failed commit restores replaced destinations before reporting failure.
"""
from pathlib import Path
from datetime import datetime
import hashlib
import json
import os
import re
import tempfile
import shutil
import time
import uuid

BACKUP_LIMIT = 10

_CHAPTER_LINE = re.compile(
    r"(?im)^[ \t]*(?:#{1,6}[ \t]+)?(?:"
    r"บทที่\s*(\d+)(?:\s*[-–—~至]\s*(\d+))?"
    r"|第\s*(\d+)(?:\s*[-–—~至]\s*(\d+))?\s*章"
    r"|chapter\s+(\d+)(?:(?:\s*[-–—~]\s*|\s+to\s+)(\d+))?"
    r")"
)
_TRANSLATOR_CHAPTER_LINE = re.compile(
    r"(?im)^[ \t]*(?:\[[AB]\][ \t]*)?(?:"
    r"บทที่\s*(\d+)(?:\s*[-–—~至]\s*(\d+))?"
    r"|第\s*(\d+)(?:\s*[-–—~至]\s*(\d+))?\s*章"
    r"|chapter\s+(\d+)(?:(?:\s*[-–—~]\s*|\s+to\s+)(\d+))?"
    r")"
)
_PROGRESS_HEADING = re.compile(
    r"(?im)^[ \t]*(?:#{1,6}[ \t]+)?(?:chapter[ \t]+progress|translation[ \t]+progress|"
    r"ความคืบหน้า(?:การแปล)?|ความคืบหน้าบท|进度|章節進度|章节进度)[ \t]*[:：]?[ \t]*"
)
_EXAMPLE_HEADING = re.compile(
    r"(?im)^[ \t]*(?:#{1,6}[ \t]+)?(?:examples?|samples?|ตัวอย่าง|示例|例子)\b.*$"
)


def _context_identity(path):
    resolved = os.path.normcase(str(Path(path).expanduser().resolve()))
    return hashlib.sha256(resolved.encode("utf-8")).hexdigest()


def context_chapter_range(data):
    text = data.decode("utf-8-sig", errors="replace")
    sections = list(_PROGRESS_HEADING.finditer(text))
    if sections:
        text = text[sections[-1].end():]
        next_section = re.search(
            r"(?im)^#{1,6}[ \t]+(?!บทที่\s*\d|Chapter\s+\d|第\s*\d)", text
        )
        if next_section:
            text = text[:next_section.start()]
    else:
        examples = list(_EXAMPLE_HEADING.finditer(text))
        if examples:
            text = text[:examples[-1].start()]
    intervals = []
    for match in _CHAPTER_LINE.finditer(text):
        groups = match.groups()
        start = next((groups[index] for index in (0, 2, 4) if groups[index]), None)
        end = next((groups[index] for index in (1, 3, 5) if groups[index]), None)
        if start:
            first, last = int(start), int(end or start)
            if 0 < first <= last <= 2_147_483_647:
                intervals.append((first, last))
    if not intervals:
        return None
    intervals.sort()
    first, last = intervals[0]
    for next_first, next_last in intervals[1:]:
        if next_first > last + 1:
            return None
        last = max(last, next_last)
    return str(first) if first == last else f"{first}-{last}"


def translator_chapter_range(data):
    """Return the outer chapter span from headings in the complete Translator bytes."""
    text = data.decode("utf-8-sig", errors="replace")
    first = last = None
    for match in _TRANSLATOR_CHAPTER_LINE.finditer(text):
        groups = match.groups()
        start = next((groups[index] for index in (0, 2, 4) if groups[index]), None)
        end = next((groups[index] for index in (1, 3, 5) if groups[index]), None)
        if start:
            chapter_first, chapter_last = int(start), int(end or start)
            if 0 < chapter_first <= chapter_last <= 2_147_483_647:
                first = chapter_first if first is None else min(first, chapter_first)
                last = chapter_last if last is None else max(last, chapter_last)
    if first is None:
        return None
    return str(first) if first == last else f"{first}-{last}"


def _utf16_length(value):
    return len(str(value).encode("utf-16-le")) // 2


def _safe_backup_stem(value, max_length=80):
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value)).strip(" .") or "Translator"
    if stem.split(".")[0].upper() in {
        "CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }:
        stem = f"_{stem}"
    truncated = []
    length = 0
    for character in stem:
        units = _utf16_length(character)
        if length + units > max_length:
            break
        truncated.append(character)
        length += units
    return "".join(truncated).rstrip(" .") or "Translator"


def _metadata_path(backup):
    return Path(f"{backup}.meta")


def _read_backup_metadata(backup):
    try:
        value = json.loads(_metadata_path(backup).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def list_backups(path, *, profile_id=None):
    """Return backups safely associated with one Context, newest first."""
    path = Path(path).expanduser().resolve()
    directory = path.parent / ".palantir-recovery"
    key = hashlib.sha256(path.name.encode("utf-8")).hexdigest()[:16]
    backups = {item for item in directory.glob(f"{key}-*.bak") if item.is_file()}
    identity = _context_identity(path)
    for item in directory.glob("*.bak"):
        metadata = _read_backup_metadata(item)
        if (metadata and metadata.get("context_identity") == identity and item.is_file()
                and (profile_id is None or metadata.get("profile_id") == profile_id)):
            backups.add(item)
    return sorted(backups, key=lambda item: item.stat().st_mtime_ns, reverse=True)


def backup_matches_context(destination, backup, *, profile_id=None):
    destination, backup = Path(destination).expanduser().resolve(), Path(backup)
    expected_dir = destination.parent / ".palantir-recovery"
    try:
        if backup.resolve().parent != expected_dir.resolve() or not backup.is_file():
            return False
    except OSError:
        return False
    metadata = _read_backup_metadata(backup)
    if metadata is not None:
        return (
            metadata.get("context_identity") == _context_identity(destination)
            and (profile_id is None or metadata.get("profile_id") == profile_id)
        )
    key = hashlib.sha256(destination.name.encode("utf-8")).hexdigest()[:16]
    return backup.name.startswith(f"{key}-") and backup.suffix == ".bak"


def replace_with_retry(source, destination):
    """Allow short Windows watcher/scanner locks without abandoning a transaction."""
    for attempt in range(7):
        try:
            os.replace(source, destination)
            return
        except OSError as error:
            if getattr(error, 'winerror', None) not in (5, 32, 33) or attempt == 6:
                raise
            time.sleep(0.02 * (2 ** attempt))


def backup_file(path, *, display_name=None, metadata=None):
    path = Path(path)
    if not path.exists(): return None
    directory = path.parent / '.palantir-recovery'
    directory.mkdir(exist_ok=True)
    # A digest keeps very long document names within Windows path limits.
    key = hashlib.sha256(path.name.encode('utf-8')).hexdigest()[:16]
    # Windows may return the same wall-clock tick for consecutive saves. Keep
    # chronological names monotonic so pruning never discards a newer backup.
    previous = [int(item.name.split('-')[1]) for item in directory.glob(f'{key}-*.bak')
                if item.name.split('-')[1].isdigit()]
    stamp = max(time.time_ns(), max(previous, default=0) + 1)
    if display_name:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        chapter_range = (metadata or {}).get("chapter_range")
        parent_length = _utf16_length(directory.resolve()) + 1
        reserved = 30 + (len(str(chapter_range)) + 1 if chapter_range else 0)
        stem = _safe_backup_stem(display_name, max(1, min(80, 240 - parent_length - reserved)))
        label = f"{stem} {chapter_range}" if chapter_range else stem
        backup = directory / f"{label}_{timestamp}_{uuid.uuid4().hex[:8]}.bak"
        if _utf16_length(backup) > 240:
            raise OSError("พาธไฟล์สำรองยาวเกินข้อจำกัดของ Windows")
    else:
        backup = directory / f'{key}-{stamp:020d}-{uuid.uuid4().hex[:8]}.bak'
    created_backup = False
    try:
        with path.open('rb') as source, backup.open('xb') as output:
            created_backup = True
            shutil.copyfileobj(source, output)
            output.flush(); os.fsync(output.fileno())
        if display_name:
            info = dict(metadata or {})
            info["context_identity"] = _context_identity(path)
            fd, temp_meta = tempfile.mkstemp(dir=directory, suffix=".meta.part")
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as output:
                    json.dump(info, output, ensure_ascii=False, sort_keys=True)
                    output.flush(); os.fsync(output.fileno())
                os.replace(temp_meta, _metadata_path(backup))
            finally:
                Path(temp_meta).unlink(missing_ok=True)
    except OSError:
        if created_backup:
            backup.unlink(missing_ok=True)
            _metadata_path(backup).unlink(missing_ok=True)
        raise
    for old in list_backups(path)[BACKUP_LIMIT:]:
        old.unlink()
        _metadata_path(old).unlink(missing_ok=True)
    return backup


def commit_staged(staged_files, commit_metadata=None, *, backup_options=None,
                  create_backups=True, no_overwrite=(), journal_path=None, verify_before=None,
                  prepare_destination=None):
    destinations = [Path(path).resolve() for path, _ in staged_files]
    if len(set(destinations)) != len(destinations):
        raise ValueError('TXT และ Context ต้องเป็นคนละไฟล์')
    if journal_path and create_backups: raise ValueError('Durable export requires temporary rollback snapshots')
    backup_options = backup_options or {}
    backups = {}
    temporary_recovery = {}
    if create_backups:
        backups = {
            path: backup_file(path, **backup_options.get(path, {}))
            for path in destinations
        }
    else:
        try:
            for path in destinations:
                if path.is_file():
                    fd, name = tempfile.mkstemp(dir=path.parent, suffix=".transaction-recovery")
                    temporary_recovery[path] = Path(name)
                    with os.fdopen(fd, "wb") as output, path.open("rb") as source:
                        shutil.copyfileobj(source, output)
                        output.flush()
                        os.fsync(output.fileno())
        except Exception:
            for snapshot in temporary_recovery.values():
                snapshot.unlink(missing_ok=True)
            raise
    replaced = []
    no_overwrite = {Path(item).resolve() for item in no_overwrite}
    journal = None
    if journal_path:
        from .storage import write_json
        from .workflow_archive import file_digest
        intended = {Path(path).resolve(): file_digest(staged).hex() for path, staged in staged_files}
        original_digests = {path: file_digest(temporary_recovery[path]).hex() if path in temporary_recovery else None
                            for path in destinations}
        journal = {'phase': 'prepared', 'entries': [
            {'path': str(path), 'backup': str(temporary_recovery[path]) if path in temporary_recovery else None,
             'after_digest': intended.get(path)}
            for path in destinations]}
        write_json(Path(journal_path), journal)
    try:
        if verify_before: verify_before()
        for destination, staged in staged_files:
            destination = Path(destination).resolve()
            def check_original():
                if journal:
                    current = file_digest(destination).hex() if destination.exists() else None
                    if current != original_digests[destination]:
                        raise OSError(f'ไฟล์ถูกแก้จากภายนอกก่อนแทนที่ · ไม่เขียนทับ: {destination}')
            check_original()
            if prepare_destination and prepare_destination(destination, staged) is not False:
                if journal:
                    changed = False
                    for path, pending in staged_files:
                        path = Path(path).resolve()
                        if path not in replaced and Path(pending).exists():
                            digest = file_digest(pending).hex()
                            if intended[path] != digest:
                                intended[path] = digest
                                next(e for e in journal['entries'] if Path(e['path']) == path)['after_digest'] = digest
                                changed = True
                    if changed: write_json(Path(journal_path), journal)
                check_original()
            if destination in no_overwrite:
                os.link(staged, destination)
            else:
                replace_with_retry(staged, destination)
            replaced.append(destination)
        if commit_metadata:
            commit_metadata()
        if journal:
            journal['phase'] = 'committed'
            write_json(Path(journal_path), journal)
    except Exception as original:
        errors = []
        for destination in reversed(replaced):
            try:
                if journal and destination.exists():
                    current = file_digest(destination).hex()
                    backup = temporary_recovery.get(destination)
                    previous = file_digest(backup).hex() if backup else None
                    if current not in (intended.get(destination), previous):
                        raise OSError(f'พบการแก้จากภายนอกระหว่าง Export · เก็บไฟล์ไว้: {destination}')
                if not create_backups:
                    backup = temporary_recovery.get(destination)
                    if backup is None:
                        destination.unlink(missing_ok=True)
                    else:
                        if journal:
                            fd, restore = tempfile.mkstemp(dir=destination.parent, suffix='.restore')
                            os.close(fd)
                            try:
                                shutil.copyfile(backup, restore)
                                replace_with_retry(restore, destination)
                            finally: Path(restore).unlink(missing_ok=True)
                        else:
                            replace_with_retry(backup, destination)
                            temporary_recovery.pop(destination, None)
                else:
                    backup = backups[destination]
                    if backup is None: destination.unlink(missing_ok=True)
                    else:
                        fd, name = tempfile.mkstemp(dir=destination.parent, suffix='.restore')
                        os.close(fd)
                        try:
                            shutil.copyfile(backup, name)
                            replace_with_retry(name, destination)
                        finally: Path(name).unlink(missing_ok=True)
            except OSError as error: errors.append(str(error))
        if not errors:
            if journal_path: Path(journal_path).unlink(missing_ok=True)
            for snapshot in temporary_recovery.values():
                snapshot.unlink(missing_ok=True)
        if errors:
            locations = ", ".join(str(item) for item in temporary_recovery.values())
            raise OSError(f'{original}; กู้คืนอัตโนมัติไม่สำเร็จ: {errors}. ไฟล์กู้คืน: {locations}') from original
        raise
    else:
        if journal_path:
            # Once committed, failed cleanup must not turn a successful export
            # into a rollback. Startup will clean a committed journal safely.
            try: Path(journal_path).unlink(missing_ok=True)
            except OSError: return
        for snapshot in temporary_recovery.values():
            try: snapshot.unlink(missing_ok=True)
            except OSError: pass


def restore_backup(destination, backup, *, profile_id=None):
    destination, backup = Path(destination), Path(backup)
    if not backup_matches_context(destination, backup, profile_id=profile_id):
        raise OSError('ไฟล์สำรองไม่ได้ผูกกับเอกสารนี้')
    fd, name = tempfile.mkstemp(dir=destination.parent, suffix='.restore')
    try:
        with os.fdopen(fd, 'wb') as output, backup.open('rb') as source:
            shutil.copyfileobj(source, output); output.flush(); os.fsync(output.fileno())
        # Stage the chosen copy before pruning, which may remove the oldest backup.
        backup_file(destination)
        replace_with_retry(name, destination)
    finally: Path(name).unlink(missing_ok=True)
