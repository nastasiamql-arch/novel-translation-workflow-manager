"""Prepare immutable workflow attachments before publishing the clipboard."""
import tempfile
import shutil
from pathlib import Path

from .workflow_archive import resolve_attachment, _check_path, file_digest


def prepare_bundle(repo, assembler, profile, steps, editor_tabs=None, *, all_files=False):
    allowed = {s.id for s in profile.workflow.steps}
    if profile.vocabulary_step: allowed.add(profile.vocabulary_step.id)
    if not steps or any(s.id not in allowed for s in steps):
        raise ValueError('Steps do not belong to the active novel')
    from .polish_history import _files
    attachments = []
    plan = {}
    for step in steps:
        for item in sorted(step.files, key=lambda x: x.order):
            if not all_files and not item.enabled: continue
            source = resolve_attachment(repo, assembler, profile, item)
            files = _files(source)
            attachments.append((item, source, files))
            for path in files: plan.setdefault(path, None)
    if not plan: raise ValueError('No enabled files to copy')
    if editor_tabs:
        for index in range(editor_tabs.tabs.count()):
            editor = editor_tabs.tabs.widget(index)
            path = editor_tabs._path(editor)
            if path not in plan: continue
            # Compare actual text: a pending normalization flag is not proof
            # that the user has made no edits (recovery/restore can set it).
            if editor.toPlainText() != editor.property('documentSavedText'):
                if not editor_tabs.save_editor(editor, quiet=True, normalize=False):
                    raise OSError('ไฟล์ Translator ยังไม่ได้บันทึก หรือพบการเปลี่ยนแปลงจากภายนอก')
    cache = repo.root / 'cache' / 'clipboard'
    cache.mkdir(parents=True, exist_ok=True)
    bundle = Path(tempfile.mkdtemp(prefix='Files-', dir=cache))
    before = {path: file_digest(_check_path(path)) for path in plan}
    for index, path in enumerate(plan, 1):
        destination = bundle / f'{index:03d}' / path.name
        destination.parent.mkdir(parents=True)
        with path.open('rb') as source, destination.open('wb') as output:
            shutil.copyfileobj(source, output, 1024 * 1024)
        if file_digest(destination) != before[path]:
            raise OSError(f'Clipboard copy verification failed: {path}')
        plan[path] = destination
    for path in plan:
        if file_digest(_check_path(path)) != before[path]:
            raise OSError(f'Attachment changed while copying: {path}')
    for item, source, files in attachments:
        if resolve_attachment(repo, assembler, profile, item) != source or _files(source) != files:
            raise OSError(f'Attachment reference changed while copying: {source}')
    return plan
