"""Lossless workflow archives; published clipboard files survive application exit.

Archives are retained in the application cache until the user removes them.
Only an unsuccessful, unpublished archive is automatically removed.
"""
from pathlib import Path
import os
import re
import tempfile
import zipfile


def _safe_name(value):
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(value)).strip(' .')
    return value or 'Step'


def _check_path(path):
    path = Path(path).expanduser().absolute()
    for parent in (path, *path.parents):
        reparse = parent.exists() and getattr(parent.lstat(), 'st_file_attributes', 0) & 0x400
        if parent.is_symlink() or reparse or (hasattr(parent, 'is_junction') and parent.is_junction()):
            raise ValueError(f'Symbolic links and junctions are not archived: {path}')
    if not path.exists():
        raise FileNotFoundError(path)
    return path.resolve()


def resolve_attachment(repo, assembler, profile, item):
    if item.reference_type == 'dynamic':
        return _check_path(assembler.resolve(profile, item.dynamic_reference))
    if not item.path:
        raise ValueError(f'Missing attachment path: {item.label}')
    if item.reference_type == 'external_file':
        return _check_path(item.path)
    repo.resolve_project_path(profile.id, item.path)  # Validate containment first.
    return _check_path(repo.profile_dir(profile.id) / item.path)


def create_workflow_archive(repo, assembler, profile, steps):
    """Validate every attachment before publishing a single ZIP64 archive."""
    if not steps:
        raise ValueError('No workflow steps selected')
    profile_root = repo.profile_dir(profile.id).resolve()
    plan = []
    names = set()
    for index, step in enumerate(steps, 1):
        prefix = f'{index:02d}_{_safe_name(step.name)}'
        resolved = [resolve_attachment(repo, assembler, profile, item)
                    for item in sorted(step.files, key=lambda item: item.order)]
        if not resolved:
            raise ValueError(f'Empty step: {step.name}')
        external = [path for path in resolved if not path.is_relative_to(profile_root)]
        external_root = None
        if external:
            try:
                external_root = Path(os.path.commonpath([str(p.parent) for p in external]))
            except ValueError:
                pass  # Different drives: collisions are explicitly rejected below.
        seen = set()
        for source in resolved:
            if source.is_dir():
                files = [p for p in source.rglob('*') if not p.is_dir() or p.is_symlink()]
                if not files:
                    raise ValueError(f'Empty directory: {source}')
            else:
                files = [source]
            for candidate in files:
                path = _check_path(candidate)
                if not path.is_file():
                    raise ValueError(f'Not a regular file: {path}')
                if path in seen:
                    continue
                seen.add(path)
                base = profile_root if path.is_relative_to(profile_root) else external_root
                relative = path.relative_to(base) if base else Path(path.name)
                if '..' in relative.parts or relative.is_absolute():
                    raise ValueError(f'Unsafe archive path: {relative}')
                member = prefix + '/' + relative.as_posix()
                if member.casefold() in names:
                    raise ValueError(f'Archive filename collision: {member}')
                names.add(member.casefold())
                # Permission errors are detected now and again during streaming.
                with path.open('rb'):
                    pass
                stat = path.stat()
                plan.append((path, member, (stat.st_size, stat.st_mtime_ns, stat.st_ino)))
    cache = repo.root / 'cache' / 'clipboard'
    cache.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='Workflow-', suffix='.zip', dir=cache)
    os.close(fd)
    archive = Path(name)
    try:
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, allowZip64=True) as output:
            for path, member, before in plan:
                output.write(path, member)
                stat = path.stat()
                if before != (stat.st_size, stat.st_mtime_ns, stat.st_ino):
                    raise OSError(f'Attachment changed during archive creation: {path}')
        return archive
    except BaseException:
        archive.unlink(missing_ok=True)
        raise
