"""Disk-backed, byte-preserving stage snapshots. No editor/export side effects."""
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
import zipfile
import threading
from functools import wraps

_history_lock = threading.RLock()


def serialized(operation):
    @wraps(operation)
    def locked(*args, **kwargs):
        with _history_lock:
            return operation(*args, **kwargs)
    return locked

from .recovery import translator_chapter_range, _safe_backup_stem
from .storage import write_json
from .workflow_archive import _check_path, resolve_attachment, stream_digest


class RangeRequired(ValueError):
    pass


def parse_range(value):
    match = re.fullmatch(r'\s*([0-9]+)(?:\s*[-–]\s*([0-9]+))?\s*', str(value))
    if not match:
        raise ValueError('ระบุช่วงบท เช่น 6-10')
    first, last = int(match[1]), int(match[2] or match[1])
    if first < 1 or last < first:
        raise ValueError('ช่วงบทต้องเริ่มที่ 1 ขึ้นไป และเรียงจากน้อยไปมาก')
    return str(first) if first == last else f'{first}-{last}'


def default_history_step(workflow):
    # Only explicit, unambiguous polish names; never infer from row or review.
    names = {'เกลา', 'เกลาสำนวน', 'polish', 'polishing', 'ขั้นตอนเกลา'}
    matches = [s.id for s in workflow.steps if s.name.strip().casefold() in names]
    return matches[0] if len(matches) == 1 else None


def _hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _read_manifest(path):
    raw = path.read_text(encoding='utf-8')
    try: return json.loads(raw)
    except json.JSONDecodeError:
        # Remove only structural trailing commas; never alter quoted text.
        quoted = escaped = False
        remove = set()
        for index, character in enumerate(raw):
            if quoted:
                if escaped: escaped = False
                elif character == '\\': escaped = True
                elif character == '"': quoted = False
            elif character == '"': quoted = True
            elif character == ',':
                tail = raw[index + 1:].lstrip()
                if tail.startswith(('}', ']')): remove.add(index)
        if not remove: raise ValueError(f'Invalid JSON: {path}')
        fixed = ''.join(c for i, c in enumerate(raw) if i not in remove)
        # A temporary copy is parsed; raw damaged metadata stays untouched.
        with tempfile.TemporaryDirectory(prefix='polish-manifest-') as directory:
            copy = Path(directory) / 'manifest.json'; copy.write_text(fixed, encoding='utf-8')
            return json.loads(copy.read_text(encoding='utf-8'))


def _filename(value):
    value = str(value)
    suffix = Path(value).suffix
    safe = (_safe_backup_stem(Path(value).stem, 80) + '.' + _safe_backup_stem(suffix.lstrip('.'), 20)
            if suffix else _safe_backup_stem(value, 100))
    if safe != value:
        tail = hashlib.sha256(value.encode()).hexdigest()[:10]
        safe = Path(safe).stem + '-' + tail + Path(safe).suffix
    return safe


def _fingerprint(files, attachments):
    keys = ('original_path', 'snapshot_path', 'reference_type', 'attachment_id', 'order', 'enabled', 'sha256', 'is_context')
    identity = {'files': [{k: e[k] for k in keys} for e in files], 'attachments': attachments}
    return hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _token(value):
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', value):
        raise ValueError('Invalid stable ID')
    return value


def _files(source):
    source = _check_path(source)
    if source.is_file():
        return [source]
    if not source.is_dir():
        raise ValueError(f'Not a regular file or folder: {source}')
    result = []
    # Check directories BEFORE descending (junctions must never form loops).
    def unreadable(error): raise error
    for folder, directories, files in os.walk(source, followlinks=False, onerror=unreadable):
        for name in sorted(directories):
            _check_path(Path(folder) / name)
        for name in sorted(files):
            candidate = _check_path(Path(folder) / name)
            if not candidate.is_file():
                raise ValueError(f'Not a regular file: {candidate}')
            result.append(candidate)
    if not result:
        raise ValueError(f'Empty attachment folder: {source}')
    return sorted(result, key=lambda p: str(p).casefold())


@dataclass
class Snapshot:
    path: Path
    manifest: dict
    error: str = ''
    warning: str = ''


class PolishHistory:
    def __init__(self, repo, assembler):
        self.repo, self.assembler = repo, assembler

    def _number_ledger(self, profile):
        path = self.repo.profile_dir(profile.id) / 'history_numbers.json'
        if not path.exists(): return path, {'next': 1, 'numbers': {}}
        value = _read_manifest(_check_path(path))
        if (not isinstance(value, dict) or type(value.get('next')) is not int
                or value['next'] < 1 or not isinstance(value.get('numbers'), dict)
                or any(type(n) is not int or n < 1 for n in value['numbers'].values())
                or len(set(value['numbers'].values())) != len(value['numbers'])):
            raise ValueError('Invalid history number ledger; preserving history')
        return path, value

    def _allocate_number(self, profile, stable_id):
        path, ledger = self._number_ledger(profile)
        numbers = ledger['numbers']
        if stable_id not in numbers:
            number = max(ledger['next'], max(numbers.values(), default=0) + 1)
            numbers[stable_id] = number
            ledger['next'] = number + 1
            # Reserve before publishing: a crash may leave a gap, never reuse.
            write_json(path, ledger)
        return numbers[stable_id]

    def _migrate_numbers(self, profile, snapshots):
        path, ledger = self._number_ledger(profile)
        valid = [s for s in snapshots if not s.error]
        for snapshot in valid:
            manifest = snapshot.manifest
            number = manifest.get('history_number')
            stable_id = manifest.get('snapshot_id')
            if not isinstance(stable_id, str) or not isinstance(manifest.get('created_at'), str):
                snapshot.error = 'Invalid stable snapshot metadata'
                continue
            if number is not None:
                if type(number) is not int or number < 1:
                    snapshot.error = 'Invalid permanent history number'; continue
                existing = ledger['numbers'].get(stable_id)
                if existing is not None and existing != number:
                    snapshot.error = 'History number does not match ledger'; continue
                if any(n == number and sid != stable_id for sid, n in ledger['numbers'].items()):
                    snapshot.error = 'Duplicate permanent history number'; continue
                ledger['numbers'][stable_id] = number
                ledger['next'] = max(ledger['next'], number + 1)
        if valid: write_json(path, ledger)
        for snapshot in sorted([s for s in valid if not s.error], key=lambda s: (s.manifest['created_at'], s.manifest['snapshot_id'])):
            number = self._allocate_number(profile, snapshot.manifest['snapshot_id'])
            if snapshot.manifest.get('history_number') != number:
                snapshot.manifest['history_number'] = number
                write_json(snapshot.path / 'manifest.json', snapshot.manifest)

    def root(self, profile):
        if not profile.main_folder.strip():
            raise ValueError('กรุณาตั้งค่าโฟลเดอร์หลักของนิยายก่อนใช้ประวัติ')
        main = _check_path(Path(profile.main_folder).expanduser())
        if not main.is_dir():
            raise ValueError('โฟลเดอร์หลักของนิยายต้องเป็นโฟลเดอร์ที่มีอยู่จริง')
        root = main / 'Polish History'
        if root.exists(): _check_path(root)
        return root

    def _snapshot_path(self, profile, path):
        root = self.root(profile)
        if '..' in Path(path).parts: raise ValueError('Snapshot path traversal')
        path = _check_path(path)
        if not path.is_relative_to(root) or len(path.relative_to(root).parts) not in (1, 2):
            raise ValueError('Snapshot path outside novel history')
        return path

    @staticmethod
    def _directory_name(manifest):
        stem = _safe_backup_stem(manifest['step_name'], 80)
        chapter_range = manifest.get('chapter_range')
        if chapter_range:
            return stem + ' บท ' + parse_range(chapter_range)
        stamp = datetime.fromisoformat(manifest['created_at']).astimezone().strftime('%Y-%m-%d %H-%M-%S')
        return stem + ' รอระบุช่วงบท (' + stamp + ')'

    def _destination(self, profile, manifest, exclude=None):
        root = self.root(profile)
        base = self._directory_name(manifest)
        candidate = root / base
        if candidate == exclude or not candidate.exists(): return candidate
        try:
            owner = _read_manifest(_check_path(candidate / 'manifest.json'))
            if owner.get('profile_id') != profile.id:
                base += ' (' + _safe_backup_stem(profile.name, 35) + ')'
                candidate = root / base
                if candidate == exclude or not candidate.exists(): return candidate
        except (OSError, ValueError, TypeError, AttributeError): pass
        stamp = datetime.fromisoformat(manifest['created_at']).astimezone().strftime('%Y-%m-%d %H-%M-%S')
        base += f' ({stamp})'
        candidate = root / base
        number = 2
        while candidate != exclude and candidate.exists():
            candidate = root / f'{base} ({number})'; number += 1
        return candidate

    @staticmethod
    def _guard_clipboard(path, clipboard_paths):
        if any(Path(p).absolute().is_relative_to(path) for p in clipboard_paths):
            raise ValueError('Clipboard ยังใช้ไฟล์ชุดนี้อยู่ กรุณาคัดลอกชุดอื่นก่อนย้ายหรือเปลี่ยนชื่อ')

    def _relocate(self, profile, path, manifest, clipboard_paths=()):
        self._guard_clipboard(path, clipboard_paths)
        destination = self._destination(profile, manifest, exclude=path)
        if destination == path: return path
        # Windows rename never replaces an existing directory. Retry a collision
        # caused by another writer after the name was selected.
        while True:
            try:
                os.rename(path, destination)
                break
            except FileExistsError:
                destination = self._destination(profile, manifest, exclude=path)
        try:
            self.validate(profile, destination)
        except BaseException:
            os.rename(destination, path)
            raise
        return destination

    def _plan(self, profile, step):
        root = self.root(profile)
        context = None
        if profile.context_path:
            try: context = Path(profile.context_path).expanduser().absolute()
            except (OSError, ValueError): pass
        plan, seen = [], set()
        attachments = []
        for index, item in enumerate(sorted(step.files, key=lambda f: f.order)):
            source = resolve_attachment(self.repo, self.assembler, profile, item)
            if source == root or source.is_relative_to(root) or root.is_relative_to(source):
                raise ValueError('History cannot be attached to itself')
            candidates = _files(source)
            attachments.append((source, candidates))
            for candidate in candidates:
                if candidate in seen: continue
                seen.add(candidate)
                relative = candidate.relative_to(source) if source.is_dir() else Path()
                components = [_filename(part) for part in relative.parts]
                # Separate attachment containers keep identical basenames lossless.
                target = Path('files') / f'{index + 1:03d}' / _filename(source.name)
                if components: target = target.joinpath(*components)
                plan.append((candidate, target, item, candidate == context))
        if not plan: raise ValueError('ขั้นตอนนี้ไม่มีไฟล์สำหรับบันทึก')
        names = [str(p[1]).casefold() for p in plan]
        if len(names) != len(set(names)): raise ValueError('Snapshot filename collision')
        return plan, attachments

    @staticmethod
    def _copy_file(source, destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        with source.open('rb') as incoming, destination.open('wb') as output:
            shutil.copyfileobj(incoming, output, 1024 * 1024)
            output.flush(); os.fsync(output.fileno())

    @serialized
    def create(self, profile, step, chapter_range=None, *, allow_unresolved=False, prepared=None,
               prefer_pre_export=False, capture_reason=None):
        if not any(s.id == step.id for s in profile.workflow.steps):
            raise ValueError('Step does not belong to novel')
        plan, attachments = self._plan(profile, step)
        original_plan = plan
        if prepared is not None:
            plan = [(prepared[source], target, item, context) for source, target, item, context in plan]
        hashes = [_hash(source) for source, *_ in plan]
        # Infer only from explicitly identified novel-content attachments, not Context.
        ranges = []
        if not chapter_range and not allow_unresolved:
            for (source, _target, item, is_context), digest in zip(plan, hashes):
                if item and not is_context and (
                    item.reference_type == 'dynamic' or
                    item.file_type in {'source', 'translated', 'reviewed', 'polished', 'novel'} or
                    source.stem.casefold().endswith('translator')
                ) and source.suffix.casefold() in {'.txt', '.md', '.markdown'}:
                    content = source.read_bytes()
                    if hashlib.sha256(content).hexdigest() != digest:
                        raise OSError(f'Attachment changed while reading chapter headings: {source}')
                    span = translator_chapter_range(content)
                    if span: ranges.append(span)
            # Different attachment spans could be references, not one submitted batch.
            if ranges and len(set(ranges)) == 1:
                chapter_range = ranges[0]
            else:
                raise RangeRequired('ยืนยันช่วงบทไม่ได้ กรุณากรอกช่วงบทแล้วคลิกขั้นตอนอีกครั้ง')
        if chapter_range:
            chapter_range = parse_range(chapter_range)
        if prefer_pre_export and chapter_range:
            # The linked Context changes after Export. Reuse the verified
            # earlier capture instead of copying the new Context into review.
            context_hash = next((digest for (_source, _target, _item, is_context), digest
                                 in zip(plan, hashes) if is_context), None)
            if context_hash:
                candidates = [
                    previous for previous in self.list(profile, step_id=step.id)
                    if not previous.error
                    and previous.manifest.get('chapter_range') == chapter_range
                    and previous.manifest.get('context_hash')
                    and previous.manifest['context_hash'] != context_hash
                ]
                marked = [previous for previous in candidates
                          if previous.manifest.get('capture_reason') == 'translator_pre_export']
                # Recent tagged captures take priority; for legacy snapshots
                # prefer the earliest to avoid accidental later duplicates.
                ordered = marked if marked else list(reversed(candidates))
                for previous in ordered:
                    if not any(entry.get('is_context')
                               and Path(entry.get('original_path', '')).absolute()
                                   == Path(profile.context_path).expanduser().absolute()
                               for entry in previous.manifest.get('files', [])):
                        continue
                    try:
                        self.validate(profile, previous.path)
                        return previous
                    except (OSError, ValueError):
                        continue
                for (original, _target, _item, is_context), digest in zip(original_plan, hashes):
                    if (not is_context and digest == context_hash
                            and original.stem.casefold().endswith('translator')):
                        raise OSError(
                            'Context ตรงกับ Translator ที่ Export แล้ว '
                            'แต่ไม่พบประวัติก่อน Export สำหรับช่วงบทนี้ '
                            'กรุณาตรวจ Polish History เดิมก่อน'
                        )
        identity = [
            {'original_path': str(source), 'snapshot_path': target.as_posix(),
             'reference_type': item.reference_type if item else 'profile_context',
             'attachment_id': item.id if item else None, 'order': item.order if item else len(plan),
             'enabled': item.enabled if item else True, 'sha256': digest,
             'is_context': is_context}
            for (source, target, item, is_context), digest in zip(original_plan, hashes)
        ]
        links = [{'id': item.id, 'label': item.label, 'reference_type': item.reference_type,
                  'path': item.path, 'dynamic_reference': item.dynamic_reference,
                  'file_type': item.file_type, 'enabled': item.enabled, 'order': item.order}
                 for item in sorted(step.files, key=lambda f: f.order)]
        fingerprint = _fingerprint(identity, links)
        step_root = self.root(profile)
        step_root.mkdir(parents=True, exist_ok=True); _check_path(step_root)
        existing = self.list(profile, step_id=step.id, verify=False)
        latest = next((x for x in existing if not x.error), None)
        if latest and latest.manifest.get('chapter_range') == chapter_range and latest.manifest.get('content_hash') == fingerprint:
            try:
                self.validate(profile, latest.path)
                if latest.manifest.get('review_status', 'รอตรวจ') != 'รอตรวจ':
                    self.set_review_status(profile, latest.path, 'รอตรวจ')
                    latest.manifest['review_status'] = 'รอตรวจ'
                return latest
            except (OSError, ValueError):
                pass  # Keep damaged history and publish a fresh verified snapshot.
        snapshot_id = uuid.uuid4().hex
        # Keep the unpublished staging path short for Windows MAX_PATH users.
        staging = step_root / f'.staging-{snapshot_id[:12]}-{profile.id[:12]}'; staging.mkdir()
        entries = []
        try:
            for record, (source, target, _item, _ctx) in zip(identity, plan):
                self._copy_file(source, staging / target)
                if _hash(staging / target) != record['sha256']:
                    raise OSError(f'Attachment changed while copying: {source}')
                entries.append({**record, 'original_name': source.name, 'size': (staging / target).stat().st_size})
            for (source, *_), digest in zip(plan, hashes):
                if _hash(_check_path(source)) != digest:
                    raise OSError(f'Attachment changed while copying: {source}')
            if prepared is None:
                for source, candidates in attachments:
                    if _files(source) != candidates: raise OSError(f'Folder changed while copying: {source}')
            created = datetime.now(timezone.utc)
            manifest = {'schema_version': 1, 'profile_id': profile.id, 'step_id': step.id,
                        'step_name': step.name, 'chapter_range': chapter_range,
                        'created_at': created.isoformat(), 'snapshot_id': snapshot_id,
                        'file_count': len(entries), 'files': entries, 'content_hash': fingerprint,
                        'attachments': links,
                        'context_hash': next((e['sha256'] for e in entries if e['is_context']), None),
                        'complete': True, 'review_status': 'รอตรวจ',
                        'range_pending': chapter_range is None}
            if capture_reason:
                manifest['capture_reason'] = capture_reason
            manifest['history_number'] = self._allocate_number(profile, snapshot_id)
            write_json(staging / 'manifest.json', manifest)
            self._validate_manifest(profile, staging, manifest)
            destination = self._relocate(profile, staging, manifest)
            return Snapshot(destination, manifest)
        except BaseException:
            # Preserve partial payload for inspection after a crash/error; never publish it.
            raise

    def _validate_manifest(self, profile, path, manifest, *, allow_payload_edits=False):
        if (not isinstance(manifest, dict) or type(manifest.get('schema_version')) is not int
                or manifest['schema_version'] != 1):
            raise ValueError('Unsupported or damaged history schema')
        if manifest.get('complete') is not True or manifest.get('profile_id') != profile.id:
            raise ValueError('Incomplete snapshot or wrong novel')
        for key in ('step_id', 'step_name', 'created_at', 'snapshot_id', 'content_hash'):
            if not isinstance(manifest.get(key), str): raise ValueError(f'Invalid {key}')
        pending_range = manifest.get('range_pending', manifest.get('chapter_range') is None)
        chapter_range = manifest.get('chapter_range')
        if type(pending_range) is not bool: raise ValueError('Invalid range_pending')
        if pending_range:
            if chapter_range not in (None, ''): raise ValueError('Invalid pending chapter range')
        elif not isinstance(chapter_range, str):
            raise ValueError('Invalid chapter_range')
        if manifest.get('review_status', 'รอตรวจ') not in {'รอตรวจ', 'ตรวจแล้ว'}:
            raise ValueError('Invalid review status')
        _token(manifest['step_id']); _token(manifest['snapshot_id'])
        parts = path.relative_to(self.root(profile)).parts
        if path.name.startswith('.staging-'):
            expected_staging = f'.staging-{manifest["snapshot_id"][:12]}-{profile.id[:12]}'
            if path.name != expected_staging:
                raise ValueError('Snapshot ID mismatch')
        elif len(parts) == 2:
            if not path.name.endswith('__' + manifest['snapshot_id']):
                raise ValueError('Snapshot ID mismatch')
            if path.parent.name != f'{manifest["step_id"]}-{profile.id}':
                raise ValueError('Snapshot step identity mismatch')
        elif len(parts) != 1:
            raise ValueError('Snapshot path outside novel history')
        if not pending_range: parse_range(chapter_range)
        if datetime.fromisoformat(manifest['created_at']).tzinfo is None:
            raise ValueError('Snapshot time must include a timezone')
        entries = manifest.get('files')
        if not isinstance(entries, list) or not entries or type(manifest.get('file_count')) is not int or manifest['file_count'] != len(entries):
            raise ValueError('Snapshot file count mismatch')
        attachments = manifest.get('attachments', [])
        if not isinstance(attachments, list): raise ValueError('Invalid attachment metadata')
        for link in attachments:
            if (not isinstance(link, dict) or type(link.get('enabled')) is not bool
                    or type(link.get('order')) is not int or not isinstance(link.get('id'), str)):
                raise ValueError('Invalid attachment metadata')
        paths, names = [], set()
        for entry in entries:
            if not isinstance(entry, dict): raise ValueError('Invalid file record')
            relative = entry.get('snapshot_path')
            if not isinstance(relative, str) or '\\' in relative or ':' in relative:
                raise ValueError('Unsafe payload path')
            parts = PurePosixPath(relative)
            if (parts.is_absolute() or '..' in parts.parts or not parts.parts
                    or parts.parts[0] not in {'files', 'context'} or parts.as_posix() != relative
                    or any(p.endswith((' ', '.')) for p in parts.parts)):
                raise ValueError('Unsafe payload path')
            if relative.casefold() in names: raise ValueError('Duplicate payload path')
            names.add(relative.casefold())
            for key in ('enabled', 'is_context'):
                if type(entry.get(key)) is not bool: raise ValueError(f'Invalid {key}')
            for key in ('original_path', 'original_name', 'reference_type', 'sha256'):
                if not isinstance(entry.get(key), str): raise ValueError(f'Invalid {key}')
            if entry.get('attachment_id') is not None and not isinstance(entry['attachment_id'], str):
                raise ValueError('Invalid attachment ID')
            if 'attachment_id' not in entry: raise ValueError('Missing attachment ID')
            if type(entry.get('size')) is not int or entry['size'] < 0 or type(entry.get('order')) is not int:
                raise ValueError('Invalid file size/order')
            if not re.fullmatch(r'[0-9a-f]{64}', entry['sha256']): raise ValueError('Invalid file hash')
            payload = _check_path(path / relative)
            if not payload.is_relative_to(path) or not payload.is_file(): raise ValueError('Unsafe payload')
            if payload.stat().st_size != entry['size'] or _hash(payload) != entry['sha256']:
                if not allow_payload_edits:
                    raise ValueError(f'ไฟล์ในประวัติถูกแก้ไขหรือ Hash ไม่ตรง: {entry["original_name"]}')
            paths.append(payload)
        actual = []
        for folder in ('files', 'context'):
            if (path / folder).exists(): actual.extend(_files(path / folder))
        if set(actual) != set(paths): raise ValueError('Unlisted or missing payload files')
        context_hash = next((entry['sha256'] for entry in entries if entry['is_context']), None)
        if manifest.get('context_hash') != context_hash: raise ValueError('Context hash mismatch')
        if _fingerprint(entries, attachments) != manifest['content_hash']:
            raise ValueError('Manifest content hash mismatch')
        return paths

    def validate(self, profile, path):
        path = self._snapshot_path(profile, path)
        if path.name.startswith('.staging-'): raise ValueError('การบันทึกยังไม่สมบูรณ์')
        _check_path(path / 'manifest.json')
        manifest = _read_manifest(path / 'manifest.json')
        return self._validate_manifest(profile, path, manifest)

    @serialized
    def list(self, profile, step_id=None, *, verify=True, clipboard_paths=()):
        root = self.root(profile)
        if not root.exists(): return []
        result = []
        candidates = []
        for item in root.iterdir():
            if (not item.name.endswith('-' + profile.id)
                    and not item.name.startswith('.staging-') and ' บท ' not in item.name
                    and '-บท ' not in item.name
                    and ' รอระบุช่วงบท ' not in item.name
                    and not (item / 'manifest.json').exists()):
                continue
            # Legacy containers have no manifest of their own; never descend
            # through symlinks or another novel's container.
            if item.name.endswith('-' + profile.id) and not item.name.startswith('.staging-'):
                try:
                    _check_path(item)
                    if item.is_dir() and not (item / 'manifest.json').exists():
                        candidates.extend((path, True) for path in item.iterdir())
                        continue
                except (OSError, ValueError) as exc:
                    result.append(Snapshot(item, {}, str(exc))); continue
            candidates.append((item, False))
        for path, legacy in candidates:
            manifest = {}
            try:
                _check_path(path)
                if not path.is_dir(): continue
                if not legacy:
                    if path.name.startswith('.staging-'):
                        if not path.name.endswith('-' + profile.id[:12]): continue
                    else:
                        manifest = _read_manifest(_check_path(path / 'manifest.json'))
                        if not isinstance(manifest, dict) or manifest.get('profile_id') != profile.id: continue
                if path.name.startswith('.staging-'): raise ValueError('การบันทึกไม่สมบูรณ์ · เก็บไฟล์ไว้เพื่อกู้คืน')
                manifest = _read_manifest(_check_path(path / 'manifest.json'))
                if verify: self._validate_manifest(profile, path, manifest)
                elif (not isinstance(manifest, dict) or manifest.get('complete') is not True
                      or manifest.get('profile_id') != profile.id
                      or (legacy and path.parent.name != f'{manifest.get("step_id")}-{profile.id}')):
                    raise ValueError('Invalid manifest')
                warning = ''
                expected = self._directory_name(manifest)
                needs_move = legacy or not (path.name == expected or path.name.startswith(expected + ' ('))
                if needs_move and verify:
                    old = path
                    try:
                        if not any(s.id == manifest['step_id'] for s in profile.workflow.steps):
                            raise ValueError('ขั้นตอนเดิมไม่อยู่ใน Workflow · คงประวัติเดิมไว้')
                        path = self._relocate(profile, path, manifest, clipboard_paths)
                        # Remove only a verified, now-empty legacy container.
                        if legacy:
                            try: old.parent.rmdir()
                            except OSError: pass
                    except (OSError, ValueError) as exc:
                        warning = 'ยังย้ายประวัติเดิมไม่ได้ · ' + str(exc)
                        if not old.exists():
                            # A failed rollback leaves the complete data at its
                            # new location, discoverable on the next refresh.
                            raise OSError('การย้ายถูกขัดจังหวะ · กรุณา Refresh เพื่อตรวจตำแหน่งไฟล์') from exc
                result.append(Snapshot(path, manifest, warning=warning))
            except (OSError, ValueError, TypeError, KeyError) as exc:
                result.append(Snapshot(path, manifest if isinstance(manifest, dict) else {}, str(exc)))
        self._migrate_numbers(profile, result)
        if step_id: result = [x for x in result if x.manifest.get('step_id') == step_id]
        return sorted(result, key=lambda x: (str(x.manifest.get('created_at', x.path.name)),
                                            str(x.manifest.get('snapshot_id', ''))), reverse=True)

    @serialized
    def accept_snapshot_edits(self, profile, path):
        """Explicitly accept changed *existing* History payloads after user confirmation.

        Never substitutes the current Context or silently repairs missing,
        unexpected, symlinked, or structurally damaged snapshot files.
        """
        path = self._snapshot_path(profile, path)
        if path.name.startswith('.staging-'):
            raise ValueError('ไม่สามารถยืนยันประวัติที่บันทึกไม่สมบูรณ์')
        manifest_path = _check_path(path / 'manifest.json')
        raw = manifest_path.read_bytes()
        manifest = _read_manifest(manifest_path)
        # Verify all metadata, listed paths, ownership, and the original
        # fingerprint before allowing any payload digest to change.
        payloads = self._validate_manifest(
            profile, path, manifest, allow_payload_edits=True
        )
        changes = []
        for entry, payload in zip(manifest['files'], payloads):
            stat_size = payload.stat().st_size
            digest = _hash(payload)
            if (stat_size, digest) != (entry['size'], entry['sha256']):
                changes.append((entry, payload, stat_size, digest))
        if not changes:
            self.validate(profile, path)
            return 0
        # Preserve the exact old manifest, including its original hashes, so
        # a later audit can distinguish intentional revisions from originals.
        backup = path / f'manifest.{uuid.uuid4().hex}.bak'
        with backup.open('xb') as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        for entry, _payload, size, digest in changes:
            entry['size'] = size
            entry['sha256'] = digest
        manifest['context_hash'] = next(
            (e['sha256'] for e in manifest['files'] if e['is_context']), None
        )
        manifest['content_hash'] = _fingerprint(
            manifest['files'], manifest.get('attachments', [])
        )
        manifest['review_status'] = 'รอตรวจ'
        manifest['revision_count'] = int(manifest.get('revision_count', 0)) + 1
        manifest['revised_at'] = datetime.now(timezone.utc).isoformat()
        manifest['revision_reason'] = 'user_confirmed_history_edit'
        try:
            write_json(manifest_path, manifest)
            self.validate(profile, path)
        except BaseException:
            # Restore metadata atomically; do not delete the user's edits.
            fd, temporary = tempfile.mkstemp(dir=path, suffix='.tmp')
            try:
                with os.fdopen(fd, 'wb') as out:
                    out.write(raw)
                    out.flush()
                    os.fsync(out.fileno())
                os.replace(temporary, manifest_path)
            finally:
                Path(temporary).unlink(missing_ok=True)
            raise
        return len(changes)

    @serialized
    def clipboard_paths(self, profile, path, *, zipped):
        path = self._snapshot_path(profile, path)
        paths = self.validate(profile, path)
        if not zipped:
            # Independent immutable copies let users recycle history while its
            # clipboard payload remains available, including after app exit.
            cache = self.repo.root / 'cache' / 'clipboard'; cache.mkdir(parents=True, exist_ok=True)
            bundle = Path(tempfile.mkdtemp(prefix='History-', dir=cache))
            frozen = []
            for i, payload in enumerate(paths, 1):
                target = bundle / str(i) / payload.name
                self._copy_file(payload, target)
                if _hash(target) != _hash(payload): raise OSError('History clipboard verification failed')
                frozen.append(target)
            self.validate(profile, path)
            return frozen
        cache = self.repo.root / 'cache' / 'clipboard'; cache.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='Polish-', suffix='.zip', dir=cache); os.close(fd)
        archive = Path(name)
        try:
            with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, allowZip64=True) as output:
                for payload in paths: output.write(payload, payload.relative_to(path).as_posix())
            with zipfile.ZipFile(archive) as output:
                if len(output.infolist()) != len(paths) or output.testzip() is not None:
                    raise OSError('ZIP payload verification failed')
                for payload in paths:
                    with output.open(payload.relative_to(path).as_posix()) as content:
                        digest = stream_digest(content).hex()
                    if digest != _hash(payload):
                        raise OSError('ZIP snapshot hash verification failed')
            # Validate again before publishing clipboard paths.
            self.validate(profile, path)
            return [archive]
        except BaseException:
            archive.unlink(missing_ok=True); raise

    @serialized
    def rename(self, profile, path, chapter_range, clipboard_paths=()):
        path = self._snapshot_path(profile, path); self.validate(profile, path)
        self._guard_clipboard(path, clipboard_paths)
        manifest = _read_manifest(path / 'manifest.json')
        chapter_range = parse_range(chapter_range)
        backup = path / f'manifest.{uuid.uuid4().hex}.bak'
        shutil.copyfile(path / 'manifest.json', backup)
        raw = backup.read_bytes()
        manifest['chapter_range'] = chapter_range
        manifest['range_pending'] = False
        try:
            # Updating metadata first leaves a readable snapshot if the process
            # is interrupted before the atomic directory move.
            write_json(path / 'manifest.json', manifest)
            destination = self._relocate(profile, path, manifest, clipboard_paths)
            if path.parent != self.root(profile):
                try: path.parent.rmdir()
                except OSError: pass
            return destination
        except BaseException:
            if path.exists():
                fd, temporary = tempfile.mkstemp(dir=path, suffix='.tmp')
                try:
                    with os.fdopen(fd, 'wb') as output:
                        output.write(raw); output.flush(); os.fsync(output.fileno())
                    os.replace(temporary, path / 'manifest.json')
                finally: Path(temporary).unlink(missing_ok=True)
            raise

    @serialized
    def set_review_status(self, profile, path, status):
        path = self._snapshot_path(profile, path)
        if status not in {'รอตรวจ', 'ตรวจแล้ว'}:
            raise ValueError('Invalid review status')
        self.validate(profile, path)
        manifest = _read_manifest(path / 'manifest.json')
        manifest['review_status'] = status
        write_json(path / 'manifest.json', manifest)
        self.validate(profile, path)
        return manifest

    @serialized
    def delete(self, profile, path, clipboard_paths=()):
        path = self._snapshot_path(profile, path)
        # Legacy/staging paths encode ownership. Flat folders must identify
        # their owner in metadata, even when payload corruption permits cleanup.
        parts = path.relative_to(self.root(profile)).parts
        if len(parts) == 2:
            if not path.parent.name.endswith('-' + profile.id):
                raise ValueError('Snapshot belongs to another novel')
        elif path.name.startswith('.staging-'):
            if not path.name.endswith('-' + profile.id):
                raise ValueError('Snapshot belongs to another novel')
        else:
            try:
                manifest = _read_manifest(_check_path(path / 'manifest.json'))
                if not isinstance(manifest, dict) or manifest.get('profile_id') != profile.id:
                    raise ValueError('Snapshot belongs to another novel')
            except (OSError, ValueError) as exc:
                raise ValueError('ยืนยันเจ้าของประวัติไม่ได้ · คงไฟล์ไว้เพื่อให้ตรวจสอบ') from exc
        if any(Path(p).absolute().is_relative_to(path) for p in clipboard_paths):
            raise ValueError('Clipboard ยังใช้ไฟล์ชุดนี้อยู่ กรุณาคัดลอกชุดอื่นก่อนลบ')
        active_files = list(profile.working_files)
        for step in profile.workflow.steps: active_files.extend(step.files)
        if profile.vocabulary_step: active_files.extend(profile.vocabulary_step.files)
        for item in active_files:
            try: current = resolve_attachment(self.repo, self.assembler, profile, item)
            except (OSError, ValueError, KeyError): continue
            if current == path or current.is_relative_to(path):
                raise ValueError('ประวัตินี้มีไฟล์ที่ผูกอยู่กับ Workflow · กรุณายกเลิกการผูกก่อนลบ')
        if profile.context_path:
            context = Path(profile.context_path).expanduser().resolve()
            if context == path or context.is_relative_to(path):
                raise ValueError('ประวัตินี้ถูกใช้เป็น Context จริง · ไม่สามารถลบได้')
        # Reject unsafe descendants even in damaged/staging snapshots.
        def unreadable(error): raise error
        for folder, directories, files in os.walk(path, followlinks=False, onerror=unreadable):
            for name in directories + files: _check_path(Path(folder) / name)
        if os.name != 'nt':
            raise OSError('Windows Recycle Bin is unavailable; history was preserved')
        from .recycle_bin import recycle_snapshot
        return recycle_snapshot(path)
