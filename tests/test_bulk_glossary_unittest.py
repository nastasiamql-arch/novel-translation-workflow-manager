import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from novel_workflow.models import NovelProfile, Workflow, WorkflowStep, StepFile
from novel_workflow.polish_history import PolishHistory
from novel_workflow.services import AssemblyService
from novel_workflow.storage import ProjectRepository


class BulkGlossaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.repo = ProjectRepository(root / 'data')
        main = root / 'novel'; main.mkdir()
        self.step = WorkflowStep(name='Polish')
        self.translation = WorkflowStep(name='แปล')
        self.profile = NovelProfile(main_folder=str(main), workflow=Workflow([self.translation, self.step]),
                                    polish_history_step_id=self.step.id)
        self.repo.save_profile(self.profile)
        self.source = self.repo.profile_dir(self.profile.id) / 'glossary' / 'terms.txt'
        self.source.write_bytes(b'old\r\n')
        prompt = self.repo.profile_dir(self.profile.id) / 'prompt.txt'
        prompt.write_bytes(b'prompt unchanged')
        self.step.files = [StepFile(path='glossary/terms.txt', file_type='glossary'),
                           StepFile(path='prompt.txt', order=1)]
        self.translation.files = [StepFile(path='glossary/terms.txt', file_type='glossary')]
        self.service = PolishHistory(self.repo, AssemblyService(self.repo))

    def test_many_snapshots_preserve_bytes_metadata_and_zip(self):
        snapshots = [self.service.create(self.profile, self.step, str(i)) for i in range(1, 21)]
        self.service.set_review_status(self.profile, snapshots[0].path, 'ตรวจแล้ว')
        snapshots[0].manifest = json.loads((snapshots[0].path / 'manifest.json').read_text(encoding='utf-8'))
        before = [(s, (s.path / s.manifest['files'][1]['snapshot_path']).read_bytes(),
                   json.loads((s.path / 'manifest.json').read_text(encoding='utf-8'))) for s in snapshots]
        new = b'\xef\xbb\xbf' + 'ไทย 中文 日本語'.encode() + b'\r\n\r\n \t\n'
        self.source.write_bytes(new)
        result = self.service.update_all_glossaries(self.profile, self.step.id)
        self.assertEqual((result['total'], result['updated'], result['errors']), (20, 20, []))
        for snap, prompt, old in before:
            paths = self.service.validate(self.profile, snap.path)
            self.assertEqual(paths[0].read_bytes(), new)
            self.assertEqual(paths[1].read_bytes(), prompt)
            now = json.loads((snap.path / 'manifest.json').read_text(encoding='utf-8'))
            for key in ('snapshot_id', 'chapter_range', 'history_number', 'review_status', 'context_hash', 'attachments'):
                self.assertEqual(now.get(key), old.get(key))
        archive = self.service.clipboard_paths(self.profile, snapshots[0].path, zipped=True)[0]
        with zipfile.ZipFile(archive) as z:
            self.assertIn(new, [z.read(name) for name in z.namelist()])
        second = self.service.update_all_glossaries(self.profile, self.step.id)
        self.assertEqual((second['updated'], second['unchanged']), (0, 20))
        self.assertFalse(list(Path(self.profile.main_folder).rglob('*.bak')))

    def test_ambiguous_source_does_not_write(self):
        snap = self.service.create(self.profile, self.step, '1')
        other = self.repo.profile_dir(self.profile.id) / 'other.txt'; other.write_bytes(b'other')
        self.translation.files.append(StepFile(path='other.txt', file_type='glossary'))
        self.source.write_bytes(b'new')
        before = (snap.path / 'manifest.json').read_bytes()
        with self.assertRaises(ValueError):
            self.service.update_all_glossaries(self.profile, self.step.id)
        self.assertEqual((snap.path / 'manifest.json').read_bytes(), before)
        self.service.validate(self.profile, snap.path)

    def test_prefixed_legacy_filename_bound_to_translation(self):
        source = Path(self.profile.main_folder) / 'NDRGlossary.txt'
        source.write_bytes(b'old')
        binding = dict(path=str(source), reference_type='external_file',
                       file_type='custom', label='NDRGlossary.txt')
        self.translation.files = [StepFile(**binding)]
        self.step.files = [StepFile(**binding)]
        snap = self.service.create(self.profile, self.step, '1')
        source.write_bytes(b'new\r\n')
        result = self.service.update_all_glossaries(self.profile, self.step.id)
        self.assertEqual((result['updated'], result['errors']), (1, []))
        self.assertEqual(self.service.validate(self.profile, snap.path)[0].read_bytes(), b'new\r\n')

    def test_multiple_legacy_glossary_names_are_ambiguous(self):
        self.translation.files = []
        for name in ('ABCGlossary.txt', 'OtherGlossary.txt'):
            path = Path(self.profile.main_folder) / name
            path.write_bytes(b'terms')
            self.translation.files.append(StepFile(path=str(path), reference_type='external_file'))
        with self.assertRaisesRegex(ValueError, 'หลายไฟล์'):
            self.service.glossary_source(self.profile)

    def test_working_file_fallback_for_current_profile(self):
        source = Path(self.profile.main_folder) / 'ABCGlossary.txt'
        source.write_bytes(b'old')
        binding = dict(path=str(source), reference_type='external_file', label=source.name)
        self.translation.files.clear()
        self.profile.working_files = [StepFile(**binding)]
        self.step.files = [StepFile(**binding)]
        snap = self.service.create(self.profile, self.step, '1')
        source.write_bytes(b'new')
        result = self.service.update_all_glossaries(self.profile, self.step.id)
        self.assertEqual((result['updated'], result['errors']), (1, []))
        self.assertEqual(self.service.validate(self.profile, snap.path)[0].read_bytes(), b'new')

    def test_only_translation_source_and_moved_snapshot_binding(self):
        snap = self.service.create(self.profile, self.step, '1')
        other = self.repo.profile_dir(self.profile.id) / 'other.txt'
        other.write_bytes(b'unrelated')
        self.profile.workflow.steps.append(WorkflowStep(name='ตรวจคำแปล', files=[
            StepFile(path='other.txt', file_type='glossary')]))
        moved = self.repo.profile_dir(self.profile.id) / 'moved.txt'
        moved.write_bytes(b'new source')
        self.translation.files = [StepFile(path='moved.txt', label='Glossary', file_type='custom')]
        result = self.service.update_all_glossaries(self.profile, self.step.id)
        self.assertEqual((result['updated'], result['errors']), (1, []))
        self.assertEqual(self.service.validate(self.profile, snap.path)[0].read_bytes(), b'new source')
        self.assertEqual(other.read_bytes(), b'unrelated')

    def test_missing_translation_glossary_never_uses_other_step(self):
        snap = self.service.create(self.profile, self.step, '1')
        before = (snap.path / 'manifest.json').read_bytes()
        self.translation.files.clear()
        with self.assertRaisesRegex(ValueError, 'ขั้นตอนแปล'):
            self.service.update_all_glossaries(self.profile, self.step.id)
        self.assertEqual((snap.path / 'manifest.json').read_bytes(), before)

    def test_external_source_and_duplicate_binding(self):
        snap = self.service.create(self.profile, self.step, '1')
        external = Path(self.temp.name) / 'new-terms.txt'
        external.write_bytes(b'external source')
        self.translation.files = [StepFile(path=str(external), reference_type='external_file', file_type='glossary'),
                                  StepFile(path=str(external), reference_type='external_file', file_type='glossary')]
        result = self.service.update_all_glossaries(self.profile, self.step.id)
        self.assertEqual((result['updated'], result['errors']), (1, []))
        self.assertEqual(self.service.validate(self.profile, snap.path)[0].read_bytes(), b'external source')

    def test_duplicate_translation_steps_are_rejected(self):
        self.profile.workflow.steps.append(WorkflowStep(name='แปล'))
        with self.assertRaisesRegex(ValueError, 'หลายขั้นตอน'):
            self.service.update_all_glossaries(self.profile, self.step.id)

    def test_manifest_write_failure_rolls_back(self):
        snap = self.service.create(self.profile, self.step, '1')
        payload = self.service.validate(self.profile, snap.path)[0]
        before = payload.read_bytes()
        manifest = (snap.path / 'manifest.json').read_bytes()
        self.source.write_bytes(b'new')
        with patch('novel_workflow.polish_history.write_json', side_effect=OSError('locked')):
            result = self.service.update_all_glossaries(self.profile, self.step.id)
        self.assertEqual(len(result['errors']), 1)
        self.assertEqual(payload.read_bytes(), before)
        self.assertEqual((snap.path / 'manifest.json').read_bytes(), manifest)
        self.service.validate(self.profile, snap.path)

    def test_corrupt_snapshot_is_not_modified(self):
        snap = self.service.create(self.profile, self.step, '1')
        payload = self.service.validate(self.profile, snap.path)[1]
        payload.write_bytes(b'corrupt')
        manifest = (snap.path / 'manifest.json').read_bytes()
        self.source.write_bytes(b'new')
        result = self.service.update_all_glossaries(self.profile, self.step.id)
        self.assertEqual(len(result['errors']), 1)
        self.assertEqual((snap.path / 'manifest.json').read_bytes(), manifest)
        self.assertEqual(payload.read_bytes(), b'corrupt')

    def test_missing_target_is_skipped_and_other_step_untouched(self):
        unrelated_step = WorkflowStep(name='Review', files=[StepFile(path='prompt.txt')])
        self.profile.workflow.steps.append(unrelated_step)
        other = self.service.create(self.profile, unrelated_step, '2')
        self.step.files = [self.step.files[1]]
        no_glossary = self.service.create(self.profile, self.step, '1')
        self.step.files.append(StepFile(path='glossary/terms.txt', file_type='glossary', order=2))
        original = (other.path / 'manifest.json').read_bytes()
        self.source.write_bytes(b'new')
        result = self.service.update_all_glossaries(self.profile, self.step.id)
        self.assertEqual((result['total'], result['updated'], len(result['skipped'])), (1, 0, 1))
        self.assertEqual((other.path / 'manifest.json').read_bytes(), original)
        self.service.validate(self.profile, no_glossary.path)

    def test_missing_source_stops_before_any_write(self):
        snap = self.service.create(self.profile, self.step, '1')
        manifest = (snap.path / 'manifest.json').read_bytes()
        self.source.unlink()
        with self.assertRaises(OSError):
            self.service.update_all_glossaries(self.profile, self.step.id)
        self.assertEqual((snap.path / 'manifest.json').read_bytes(), manifest)

    def test_recoverable_manifest_syntax_preserves_values(self):
        snap = self.service.create(self.profile, self.step, '1')
        path = snap.path / 'manifest.json'
        raw = path.read_text(encoding='utf-8')
        path.write_text(raw.rstrip()[:-1] + ',\n}', encoding='utf-8')
        self.source.write_bytes(b'updated')
        result = self.service.update_all_glossaries(self.profile, self.step.id)
        self.assertEqual((result['updated'], result['errors']), (1, []))
        self.assertEqual(self.service.validate(self.profile, snap.path)[0].read_bytes(), b'updated')

    def test_read_only_list_does_not_migrate_history_number(self):
        snap = self.service.create(self.profile, self.step, '1')
        path = snap.path / 'manifest.json'
        manifest = json.loads(path.read_text(encoding='utf-8'))
        manifest.pop('history_number')
        path.write_text(json.dumps(manifest), encoding='utf-8')
        before = path.read_bytes()
        self.service.list(self.profile, step_id=self.step.id, read_only=True)
        self.assertEqual(path.read_bytes(), before)

    def test_external_change_during_failure_is_never_overwritten(self):
        snap = self.service.create(self.profile, self.step, '1')
        payload = self.service.validate(self.profile, snap.path)[0]
        self.source.write_bytes(b'new')
        def changed_elsewhere(*args):
            payload.write_bytes(b'external edit')
            raise OSError('manifest failure')
        with patch('novel_workflow.polish_history.write_json', side_effect=changed_elsewhere):
            result = self.service.update_all_glossaries(self.profile, self.step.id)
        self.assertEqual(payload.read_bytes(), b'external edit')
        self.assertIn('ต้องตรวจความสมบูรณ์', result['errors'][0][1])

    def test_idempotent_run_does_not_touch_payload_or_manifest(self):
        snap = self.service.create(self.profile, self.step, '1')
        payload = self.service.validate(self.profile, snap.path)[0]
        manifest = snap.path / 'manifest.json'
        before = (payload.stat().st_mtime_ns, manifest.stat().st_mtime_ns, manifest.read_bytes())
        result = self.service.update_all_glossaries(self.profile, self.step.id)
        self.assertEqual(result['unchanged'], 1)
        self.assertEqual((payload.stat().st_mtime_ns, manifest.stat().st_mtime_ns, manifest.read_bytes()), before)

    def test_source_change_after_preflight_prevents_writes(self):
        snap = self.service.create(self.profile, self.step, '1')
        payload = self.service.validate(self.profile, snap.path)[0]
        original = payload.read_bytes()
        self.source.write_bytes(b'new')
        validate = self.service._validate_manifest
        changed = False
        def mutate(*args, **kwargs):
            nonlocal changed
            result = validate(*args, **kwargs)
            if not changed:
                changed = True
                self.source.write_bytes(b'changed again')
            return result
        with patch.object(self.service, '_validate_manifest', side_effect=mutate):
            result = self.service.update_all_glossaries(self.profile, self.step.id)
        self.assertEqual(result['updated'], 0)
        self.assertEqual(len(result['errors']), 1)
        self.assertEqual(payload.read_bytes(), original)

    @unittest.skipIf(__import__('os').name == 'nt', 'symlink permissions vary on Windows')
    def test_source_symlink_is_rejected(self):
        snap = self.service.create(self.profile, self.step, '1')
        alias = self.source.parent / 'alias.txt'
        alias.symlink_to(self.source)
        self.translation.files[0].path = 'glossary/alias.txt'
        with self.assertRaises(ValueError):
            self.service.update_all_glossaries(self.profile, self.step.id)
        self.service.validate(self.profile, snap.path)


if __name__ == '__main__':
    unittest.main()
