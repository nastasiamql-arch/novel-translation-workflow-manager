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

from .recovery import translator_chapter_range, _safe_backup_stem
from .storage import write_json
from .workflow_archive import _check_path, resolve_attachment


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


class PolishHistory:
    def __init__(self, repo, assembler):
        self.repo, self.assembler = repo, assembler

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
        path = _check_path(path)
        if not path.is_relative_to(root) or len(path.relative_to(root).parts) != 2:
            raise ValueError('Snapshot path outside novel history')
        return path

    def _plan(self, profile, step):
        root = self.root(profile)
        context = _check_path(profile.context_path) if profile.context_path else None
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
        if context and context not in seen:
            if not context.is_file(): raise ValueError('Context must be a file')
            plan.append((context, Path('context') / _filename(context.name), None, True))
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

    def create(self, profile, step, chapter_range=None):
        if not any(s.id == step.id for s in profile.workflow.steps):
            raise ValueError('Step does not belong to novel')
        plan, attachments = self._plan(profile, step)
        hashes = [_hash(source) for source, *_ in plan]
        # Infer only from explicitly identified novel-content attachments, not Context.
        ranges = []
        if not chapter_range:
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
            if not ranges or len(set(ranges)) != 1:
                raise RangeRequired('ยืนยันช่วงบทไม่ได้ กรุณากรอกช่วงบทแล้วคลิกขั้นตอนอีกครั้ง')
            chapter_range = ranges[0]
        chapter_range = parse_range(chapter_range)
        identity = [
            {'original_path': str(source), 'snapshot_path': target.as_posix(),
             'reference_type': item.reference_type if item else 'profile_context',
             'attachment_id': item.id if item else None, 'order': item.order if item else len(plan),
             'enabled': item.enabled if item else True, 'sha256': digest,
             'is_context': is_context}
            for (source, target, item, is_context), digest in zip(plan, hashes)
        ]
        links = [{'id': item.id, 'label': item.label, 'reference_type': item.reference_type,
                  'path': item.path, 'dynamic_reference': item.dynamic_reference,
                  'file_type': item.file_type, 'enabled': item.enabled, 'order': item.order}
                 for item in sorted(step.files, key=lambda f: f.order)]
        fingerprint = _fingerprint(identity, links)
        step_root = self.root(profile) / f'{_token(step.id)}-{_token(profile.id)}'
        step_root.mkdir(parents=True, exist_ok=True); _check_path(step_root)
        existing = self.list(profile, step_id=step.id, verify=False)
        latest = next((x for x in existing if not x.error), None)
        if latest and latest.manifest.get('chapter_range') == chapter_range and latest.manifest.get('content_hash') == fingerprint:
            try:
                self.validate(profile, latest.path)
                return latest
            except (OSError, ValueError):
                pass  # Keep damaged history and publish a fresh verified snapshot.
        snapshot_id = uuid.uuid4().hex
        staging = step_root / f'.staging-{snapshot_id}'; staging.mkdir()
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
            for source, candidates in attachments:
                if _files(source) != candidates: raise OSError(f'Folder changed while copying: {source}')
            created = datetime.now(timezone.utc)
            manifest = {'schema_version': 1, 'profile_id': profile.id, 'step_id': step.id,
                        'step_name': step.name, 'chapter_range': chapter_range,
                        'created_at': created.isoformat(), 'snapshot_id': snapshot_id,
                        'file_count': len(entries), 'files': entries, 'content_hash': fingerprint,
                        'attachments': links,
                        'context_hash': next((e['sha256'] for e in entries if e['is_context']), None),
                        'complete': True}
            write_json(staging / 'manifest.json', manifest)
            self._validate_manifest(profile, staging, manifest)
            destination = step_root / f'บท {chapter_range}__{created.strftime("%Y%m%d-%H%M%S")}__{snapshot_id}'
            os.rename(staging, destination)
            return Snapshot(destination, manifest)
        except BaseException:
            # Preserve partial payload for inspection after a crash/error; never publish it.
            raise

    def _validate_manifest(self, profile, path, manifest):
        if (not isinstance(manifest, dict) or type(manifest.get('schema_version')) is not int
                or manifest['schema_version'] != 1):
            raise ValueError('Unsupported or damaged history schema')
        if manifest.get('complete') is not True or manifest.get('profile_id') != profile.id:
            raise ValueError('Incomplete snapshot or wrong novel')
        for key in ('step_id', 'step_name', 'chapter_range', 'created_at', 'snapshot_id', 'content_hash'):
            if not isinstance(manifest.get(key), str): raise ValueError(f'Invalid {key}')
        _token(manifest['step_id']); _token(manifest['snapshot_id'])
        if (path.name != '.staging-' + manifest['snapshot_id']
                and not path.name.endswith('__' + manifest['snapshot_id'])):
            raise ValueError('Snapshot ID mismatch')
        if path.parent.name != f'{manifest["step_id"]}-{profile.id}':
            raise ValueError('Snapshot step identity mismatch')
        parse_range(manifest['chapter_range'])
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
                raise ValueError(f'ไฟล์หายหรือ Hash ไม่ตรง: {entry["original_name"]}')
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

    def list(self, profile, step_id=None, *, verify=True):
        root = self.root(profile)
        if not root.exists(): return []
        result = []
        for step in root.iterdir():
            if not step.name.endswith('-' + profile.id): continue
            if step_id and step.name != f'{_token(step_id)}-{profile.id}': continue
            try: _check_path(step)
            except (OSError, ValueError) as exc:
                result.append(Snapshot(step, {}, str(exc))); continue
            if not step.is_dir(): continue
            for path in step.iterdir():
                manifest = {}
                try:
                    _check_path(path)
                    if not path.is_dir(): continue
                    if path.name.startswith('.staging-'): raise ValueError('การบันทึกไม่สมบูรณ์ · เก็บไฟล์ไว้เพื่อกู้คืน')
                    manifest = _read_manifest(_check_path(path / 'manifest.json'))
                    if verify: self._validate_manifest(profile, path, manifest)
                    elif (not isinstance(manifest, dict) or manifest.get('complete') is not True
                          or manifest.get('profile_id') != profile.id or manifest.get('step_id') != step.name.removesuffix('-' + profile.id)):
                        raise ValueError('Invalid manifest')
                    result.append(Snapshot(path, manifest))
                except (OSError, ValueError, TypeError, KeyError) as exc:
                    result.append(Snapshot(path, manifest if isinstance(manifest, dict) else {}, str(exc)))
        return sorted(result, key=lambda x: str(x.manifest.get('created_at', x.path.name)), reverse=True)

    def clipboard_paths(self, profile, path, *, zipped):
        path = self._snapshot_path(profile, path)
        paths = self.validate(profile, path)
        if not zipped: return paths
        cache = self.repo.root / 'cache' / 'clipboard'; cache.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='Polish-', suffix='.zip', dir=cache); os.close(fd)
        archive = Path(name)
        try:
            with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, allowZip64=True) as output:
                for payload in paths: output.write(payload, payload.relative_to(path).as_posix())
            with zipfile.ZipFile(archive) as output:
                if len(output.infolist()) != len(paths) or output.testzip() is not None:
                    raise OSError('ZIP payload verification failed')
            # Validate again before publishing clipboard paths.
            self.validate(profile, path)
            return [archive]
        except BaseException:
            archive.unlink(missing_ok=True); raise

    def rename(self, profile, path, chapter_range):
        path = self._snapshot_path(profile, path); self.validate(profile, path)
        manifest = _read_manifest(path / 'manifest.json')
        chapter_range = parse_range(chapter_range)
        shutil.copyfile(path / 'manifest.json', path / f'manifest.{uuid.uuid4().hex}.bak')
        manifest['chapter_range'] = chapter_range
        write_json(path / 'manifest.json', manifest)

    def delete(self, profile, path, clipboard_paths=()):
        path = self._snapshot_path(profile, path)
        if any(Path(p).absolute().is_relative_to(path) for p in clipboard_paths):
            raise ValueError('Clipboard ยังใช้ไฟล์ชุดนี้อยู่ กรุณาคัดลอกชุดอื่นก่อนลบ')
        # Reject unsafe descendants even in damaged/staging snapshots.
        def unreadable(error): raise error
        for folder, directories, files in os.walk(path, followlinks=False, onerror=unreadable):
            for name in directories + files: _check_path(Path(folder) / name)
        shutil.rmtree(path)
