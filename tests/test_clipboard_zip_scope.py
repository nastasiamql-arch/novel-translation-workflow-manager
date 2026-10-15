"""Clipboard ZIPs are scoped to the selected workflow step, not other steps."""
import zipfile
from pathlib import Path

from novel_workflow.clipboard_bundle import prepare_bundle
from novel_workflow.models import NovelProfile, StepFile, Workflow, WorkflowStep
from novel_workflow.services import AssemblyService
from novel_workflow.storage import ProjectRepository
from novel_workflow.workflow_archive import create_workflow_archive


def test_single_step_zip_includes_all_linked_files_but_no_other_step(tmp_path):
    repo = ProjectRepository(tmp_path / 'data')
    current = WorkflowStep(name='แปล', files=[
        StepFile(path='ต้นฉบับจีน.txt', order=0),
        StepFile(path='ศัพท์ไทย.tsv', enabled=False, order=1),
    ])
    other = WorkflowStep(name='ตรวจคำแปล', files=[
        StepFile(path='other.txt', order=0),
    ])
    profile = NovelProfile(workflow=Workflow([current, other]))
    repo.save_profile(profile)
    root = repo.profile_dir(profile.id)
    values = {
        'ต้นฉบับจีน.txt': '第一章\r\n\r\n中文'.encode('utf-8'),
        'ศัพท์ไทย.tsv': '\ufeffศัพท์\tคำแปล\r\n'.encode('utf-8'),
        'other.txt': b'NEVER IN THE CURRENT STEP ZIP',
    }
    for name, raw in values.items():
        (root / name).write_bytes(raw)

    assembler = AssemblyService(repo)
    frozen = prepare_bundle(repo, assembler, profile, [current], all_files=True)
    assert {path.name for path in frozen} == {'ต้นฉบับจีน.txt', 'ศัพท์ไทย.tsv'}
    archive = create_workflow_archive(repo, assembler, profile, [current], prepared=frozen)
    assert archive.name.startswith('แปล-')

    with zipfile.ZipFile(archive) as zipped:
        assert len(zipped.namelist()) == 2
        assert {Path(name).name: zipped.read(name) for name in zipped.namelist()} == {
            key: values[key] for key in ('ต้นฉบับจีน.txt', 'ศัพท์ไทย.tsv')
        }
        assert zipped.testzip() is None

    # Clipboard payloads remain usable after the live source changes.
    (root / 'ต้นฉบับจีน.txt').write_bytes(b'changed')
    (root / 'other.txt').write_bytes(b'changed too')
    with zipfile.ZipFile(archive) as zipped:
        assert any(zipped.read(name) == values['ต้นฉบับจีน.txt'] for name in zipped.namelist())

    # The non-ZIP mode retains the previous enabled-file-only behavior.
    normal = prepare_bundle(repo, assembler, profile, [current], all_files=False)
    assert {path.name for path in normal} == {'ต้นฉบับจีน.txt'}


def test_zip_preference_survives_settings_reload(tmp_path):
    repo = ProjectRepository(tmp_path / 'data')
    settings = repo.load_settings()
    settings.copy_files_as_zip = True
    repo.save_settings(settings)
    assert repo.load_settings().copy_files_as_zip is True
