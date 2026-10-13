"""Abrupt process-exit probe for the real durable export transaction."""
import os
import sys
import hashlib
from pathlib import Path
from novel_workflow.storage import ProjectRepository, write_json
from novel_workflow.recovery import commit_staged
import novel_workflow.recovery as recovery
from novel_workflow.workspace_window import _stage_bytes_file
from novel_workflow.translation_progress import record_translator_export

repo=ProjectRepository(sys.argv[1]); profile=repo.list_profiles()[0]
phase=sys.argv[2]
context=Path(profile.context_path)
target=Path(profile.main_folder)/'Context Exports'/'Translator 6-10.txt'
target.parent.mkdir(exist_ok=True)
folder=repo.profile_dir(profile.id)
journal=folder/'translator_export_transaction.json'
status=folder/'export_status.json'
real_replace=recovery.replace_with_retry
def replace_and_crash(source,destination):
    real_replace(source,destination)
    if phase=='after_context' and Path(destination)==context: os._exit(7)
    if phase=='after_statistics' and Path(destination)==status: os._exit(7)
recovery.replace_with_retry=replace_and_crash
real_link=os.link
def link_and_crash(*args,**kwargs):
    real_link(*args,**kwargs)
    if phase=='after_txt': os._exit(7)
os.link=link_and_crash
real_unlink=Path.unlink
def unlink_and_crash(path,*args,**kwargs):
    if phase=='after_commit' and path==journal: os._exit(7)
    return real_unlink(path,*args,**kwargs)
Path.unlink=unlink_and_crash
record_translator_export(profile,list(range(6,11)),source_path='Translator.txt',digest=hashlib.sha256(b'new translation').hexdigest(),
                         exported_path=str(target),event_id='crash-event')
staged_profile=_stage_bytes_file(folder/'profile.json',b'')
repo.save_profile(profile,destination=staged_profile)
staged_status=_stage_bytes_file(status,b'')
write_json(staged_status,{'success':True})
commit_staged([(target,_stage_bytes_file(target,b'new translation')),
               (context,_stage_bytes_file(context,b'new translation')),
               (folder/'profile.json',staged_profile),(status,staged_status)],
              create_backups=False,no_overwrite=(target,),journal_path=journal)
raise RuntimeError('Expected abrupt crash was not triggered')
