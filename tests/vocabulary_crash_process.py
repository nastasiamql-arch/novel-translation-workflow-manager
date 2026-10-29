"""Crash after replacing a transaction participant for recovery testing."""
import os
import sys
from pathlib import Path
from novel_workflow.storage import ProjectRepository, write_json
from novel_workflow.workspace_window import _stage_bytes_file
from novel_workflow.recovery import commit_staged
import novel_workflow.recovery as recovery

repo = ProjectRepository(sys.argv[1])
profile = repo.list_profiles()[0]
folder = repo.profile_dir(profile.id)
source = folder / 'ExampleTranslator.txt'
context = Path(profile.context_path)
queue = folder / 'pending_vocabulary.json'
target = Path(profile.main_folder) / 'Context Exports' / 'new.txt'
target.parent.mkdir(exist_ok=True)
profile_path = folder / 'profile.json'
journal = folder / 'translator_export_transaction.json'
clean = b'clean novel'
queue_stage = _stage_bytes_file(queue, b'')
write_json(queue_stage, {'version': 1, 'items': [{'id': 'one', 'profile_id': profile.id,
           'text': 'test', 'count': 1, 'source_digest': 'digest'}]})
real_replace = recovery.replace_with_retry
def replace_and_exit(src, dst):
    real_replace(src, dst)
    if Path(dst) == {'queue': queue, 'source': source, 'profile': profile_path}.get(sys.argv[2]):
        os._exit(7)
recovery.replace_with_retry = replace_and_exit
real_unlink = Path.unlink
def unlink_and_exit(path, *args, **kwargs):
    if sys.argv[2] == 'committed' and path == journal:
        os._exit(7)
    return real_unlink(path, *args, **kwargs)
Path.unlink = unlink_and_exit
commit_staged([(target, _stage_bytes_file(target, clean)),
               (context, _stage_bytes_file(context, clean)), (queue, queue_stage),
               (source, _stage_bytes_file(source, clean)),
               (profile_path, _stage_bytes_file(profile_path, profile_path.read_bytes()))],
              create_backups=False, no_overwrite=(target,), journal_path=journal)
raise RuntimeError('crash not triggered')
