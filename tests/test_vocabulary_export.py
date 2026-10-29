import os
from pathlib import Path
import pytest
from PySide6.QtWidgets import QApplication
from test_translator_completion import translator
from test_polish_history_ui import window
from novel_workflow.vocabulary_queue import load_queue


@pytest.mark.parametrize('section,expected', [
    ('คำศัพท์ใหม่\n李来福\tหลี่ไหลฝู\tชาย\tเด็กหนุ่ม\n来福\tไหลฝู', 2),
    ('คำศัพท์ใหม่\n[-]', 0),
    ('', 0),
])
def test_export_cleans_and_queues(translator, section, expected):
    w, p, ws, source, errors = translator
    editor = ws.editor._current_editor()
    novel = 'บทที่ 6\nเนื้อเรื่อง 李来福\n[จบบท]'
    editor.setPlainText(novel + ('\n\n' + section if section else ''))
    QApplication.clipboard().setText('keep clipboard')
    assert w.update_context_from_translator(ws)
    assert source.read_text(encoding='utf-8').rstrip('\n') == novel
    assert editor.toPlainText().rstrip('\n') == novel
    assert Path(p.context_path).read_bytes() == source.read_bytes()
    exports = list((Path(p.main_folder) / 'Context Exports').glob('*.txt'))
    assert exports[-1].read_bytes() == source.read_bytes()
    items = load_queue(w.repo, p.id)['items']
    assert sum(x['count'] for x in items) == expected
    assert QApplication.clipboard().text() == (items[0]['text'] if expected else 'keep clipboard')
    assert w.update_context_from_translator(ws)
    assert len(load_queue(w.repo, p.id)['items']) == bool(expected)
    assert ws.export_status_label.text() == 'Exported'


def test_ambiguous_export_preserves_source_and_context(translator):
    w, p, ws, source, errors = translator
    text = 'บทที่ 6\nนิยาย\nคำศัพท์ใหม่\nข้อความที่แยกไม่ได้'
    ws.editor._current_editor().setPlainText(text)
    old_context = Path(p.context_path).read_bytes()
    assert not w.update_context_from_translator(ws)
    assert source.read_text(encoding='utf-8').rstrip('\n') == text
    assert Path(p.context_path).read_bytes() == old_context
    assert not load_queue(w.repo, p.id)['items']


def test_queue_copy_and_delete(translator, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from novel_workflow.vocabulary_queue_dialog import VocabularyQueueDialog
    w, p, ws, source, errors = translator
    editor = ws.editor._current_editor()
    for chapter, word in [(6, '李来福\tหลี่ไหลฝู'), (7, '来福\tไหลฝู')]:
        editor.setPlainText(f'บทที่ {chapter}\nเนื้อหา\n\nคำศัพท์ใหม่\n{word}')
        assert w.update_context_from_translator(ws)
    dialog = VocabularyQueueDialog(w.repo, p, ws, changed=ws.refresh_vocabulary_queue)
    assert ws.vocabulary_queue_button.text() == 'คำศัพท์รอตรวจ (2)'
    dialog.copy_all()
    assert QApplication.clipboard().text() == '李来福\tหลี่ไหลฝู\n来福\tไหลฝู'
    monkeypatch.setattr(QMessageBox, 'question', lambda *a: QMessageBox.No)
    dialog.remove(dialog.data['items'][0])
    assert len(load_queue(w.repo, p.id)['items']) == 2
    monkeypatch.setattr(QMessageBox, 'question', lambda *a: QMessageBox.Yes)
    dialog.remove(dialog.data['items'][0])
    assert len(load_queue(w.repo, p.id)['items']) == 1
    assert ws.vocabulary_queue_button.text() == 'คำศัพท์รอตรวจ (1)'
    dialog.clear_all()
    assert load_queue(w.repo, p.id)['items'] == []
    assert ws.vocabulary_queue_button.text() == 'คำศัพท์รอตรวจ (0)'
    dialog.close()


def test_clipboard_failure_keeps_successful_queue(translator, monkeypatch):
    from PySide6.QtGui import QClipboard
    w, p, ws, source, errors = translator
    ws.editor._current_editor().setPlainText('บทที่ 6\nนิยาย\n\nคำศัพท์ใหม่\n李来福\tหลี่ไหลฝู')
    def fail(*args): raise RuntimeError('clipboard unavailable')
    with monkeypatch.context() as patch:
        patch.setattr(QClipboard, 'setText', fail)
        assert w.update_context_from_translator(ws)
        assert 'คัดลอกคำศัพท์อัตโนมัติไม่สำเร็จ' in w.statusBar().currentMessage()
    assert load_queue(w.repo, p.id)['items'][0]['text'] == '李来福\tหลี่ไหลฝู'


def test_snapshot_preserves_original_even_when_step_does_not_link_translator(translator):
    w, p, ws, source, errors = translator
    p.workflow.steps[1].files = [p.workflow.steps[1].files[1]]
    w.repo.save_profile(p)
    text = 'บทที่ 6\nนิยาย\n\nคำศัพท์ใหม่\n李来福\tหลี่ไหลฝู'
    ws.editor._current_editor().setPlainText(text)
    assert w.update_context_from_translator(ws)
    snapshot = w.polish_history.list(w.profile)[0]
    entry = next(x for x in snapshot.manifest['files'] if Path(x['original_path']) == source)
    assert (snapshot.path / entry['snapshot_path']).read_text(encoding='utf-8').rstrip('\n') == text
    assert len(w.repo.list_profiles()[0].workflow.steps[1].files) == 1


def test_queue_button_only_in_translator_and_focus_mode(translator):
    w, p, ws, source, errors = translator
    w.resize(900, 600)
    QApplication.processEvents()
    assert ws.vocabulary_queue_button.isVisible()
    assert not ws.vocabulary_queue_button.geometry().intersects(ws.update_context_button.geometry())
    assert ws.vocabulary_queue_button.accessibleName()
    ws.set_focus_mode(True)
    QApplication.processEvents()
    assert ws.vocabulary_queue_button.isVisible()
    assert not ws.vocabulary_queue_button.geometry().intersects(ws.update_context_button.geometry())
    context_editor = ws.editor.open_file(p.context_path)
    QApplication.processEvents()
    assert ws.vocabulary_queue_button.isHidden()
    ws.editor.tabs.setCurrentWidget(ws.editor.open_file(source))
    QApplication.processEvents()
    assert ws.vocabulary_queue_button.isVisible()


def test_queue_write_failure_rolls_back_export(translator, monkeypatch):
    w, p, ws, source, errors = translator
    text = 'บทที่ 6\nนิยาย\n\nคำศัพท์ใหม่\n李来福\tหลี่ไหลฝู'
    ws.editor._current_editor().setPlainText(text)
    old_context = Path(p.context_path).read_bytes()
    import novel_workflow.workspace_window as module
    original = module.commit_staged
    def fail(staged, **kwargs):
        def fail_verify(): raise OSError('injected failure')
        kwargs['commit_metadata'] = fail_verify
        return original(staged, **kwargs)
    monkeypatch.setattr(module, 'commit_staged', fail)
    assert not w.update_context_from_translator(ws)
    assert source.read_text(encoding='utf-8').rstrip('\n') == text
    assert Path(p.context_path).read_bytes() == old_context
    assert not load_queue(w.repo, p.id)['items']


def test_broken_queue_blocks_vocabulary_but_not_plain_export(translator):
    from novel_workflow.vocabulary_queue import queue_path
    w, p, ws, source, errors = translator
    path = queue_path(w.repo, p.id)
    path.write_text('broken', encoding='utf-8')
    editor = ws.editor._current_editor()
    editor.setPlainText('บทที่ 6\nนิยาย\n\nคำศัพท์ใหม่\n李来福\tหลี่ไหลฝู')
    assert not w.update_context_from_translator(ws)
    assert 'คำศัพท์ใหม่' in source.read_text(encoding='utf-8')
    assert path.read_text(encoding='utf-8') == 'broken'
    editor.setPlainText('บทที่ 6\nนิยาย')
    assert w.update_context_from_translator(ws)
    assert path.read_text(encoding='utf-8') == 'broken'


@pytest.mark.parametrize('phase', ['queue', 'source', 'profile', 'committed'])
def test_crash_recovers_translator_and_queue_together(tmp_path, phase):
    import subprocess, sys
    from novel_workflow.models import NovelProfile, StepFile
    from novel_workflow.storage import ProjectRepository
    context = tmp_path / 'Context.md'
    context.write_bytes(b'old context')
    repo = ProjectRepository(tmp_path / 'data')
    profile = NovelProfile(context_path=str(context), main_folder=str(tmp_path))
    profile.working_files = [StepFile(path='ExampleTranslator.txt')]
    repo.save_profile(profile)
    source = repo.profile_dir(profile.id) / 'ExampleTranslator.txt'
    source.write_bytes(b'original translator with vocabulary')
    result = subprocess.run([sys.executable, str(Path(__file__).with_name('vocabulary_crash_process.py')),
                             str(repo.root), phase], timeout=30)
    assert result.returncode == 7
    repo.list_profiles()
    assert not repo.export_recovery_errors
    if phase == 'committed':
        assert source.read_bytes() == context.read_bytes() == b'clean novel'
        assert load_queue(repo, profile.id)['items'][0]['id'] == 'one'
        assert len(list((tmp_path / 'Context Exports').glob('*.txt'))) == 1
    else:
        assert source.read_bytes() == b'original translator with vocabulary'
        assert context.read_bytes() == b'old context'
        assert not load_queue(repo, profile.id)['items']
        assert not list((tmp_path / 'Context Exports').glob('*.txt'))


@pytest.mark.parametrize('ending', ['[จบตอน]', '[จบบท]'])
@pytest.mark.parametrize('section, expected', [
    ('李来福\tหลี่ไหลฝู\tชาย\tตัวละคร\n来福\tไหลฝู\tชาย\tชื่อเรียก', 2),
    ('[-]', 0),
])
def test_export_after_chapter_end_without_blank_line(translator, ending, section, expected):
    w, p, ws, source, errors = translator
    novel = f'บทที่ 6\nเนื้อเรื่อง 李来福\n{ending}'
    original = novel + '\nคำศัพท์ใหม่\n' + section
    ws.editor._current_editor().setPlainText(original)

    assert w.update_context_from_translator(ws)
    cleaned = source.read_text(encoding='utf-8').rstrip('\n')
    assert cleaned == novel
    assert ws.editor._current_editor().toPlainText().rstrip('\n') == novel
    assert Path(p.context_path).read_bytes() == source.read_bytes()
    exports = list((Path(p.main_folder) / 'Context Exports').glob('*.txt'))
    assert len(exports) == 1
    assert exports[0].read_bytes() == source.read_bytes()
    items = load_queue(w.repo, p.id)['items']
    assert sum(item['count'] for item in items) == expected
    if expected:
        assert items[0]['text'] == section
    assert w.update_context_from_translator(ws)
    assert sum(item['count'] for item in load_queue(w.repo, p.id)['items']) == expected


def test_export_accepts_mixed_vocabulary_format_from_user_screenshot(translator):
    w, p, ws, source, errors = translator
    novel = 'บทที่ 750\nเนื้อเรื่อง 李来福\n[จบตอน]'
    rows = ('枪支弹药 อาวุธปืนและกระสุน - อาวุธปืนและเครื่องกระสุน\n'
            '领导包间 ห้องอาหารส่วนตัว - ห้องรับประทานอาหาร\n'
            '李来福\tหลี่ไหลฝู\tชาย\tตัวละคร')
    editor = ws.editor._current_editor()
    editor.setPlainText(novel + '\nคำศัพท์ใหม่\n' + rows)
    assert w.update_context_from_translator(ws)
    assert source.read_text(encoding='utf-8').rstrip('\n') == novel
    assert editor.toPlainText().rstrip('\n') == novel
    assert Path(p.context_path).read_bytes() == source.read_bytes()
    exports = list((Path(p.main_folder) / 'Context Exports').glob('*.txt'))
    assert len(exports) == 1 and exports[0].read_bytes() == source.read_bytes()
    items = load_queue(w.repo, p.id)['items']
    assert len(items) == 1 and items[0]['count'] == 3
    assert items[0]['text'] == rows
    assert w.update_context_from_translator(ws)
    assert len(load_queue(w.repo, p.id)['items']) == 1


def test_all_unstructured_vocabulary_is_copied_to_queue_without_review_dialog(translator, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    w, p, ws, source, errors = translator
    novel = 'บทที่ 750\nเนื้อเรื่อง\n[จบตอน]'
    raw = ('李来福 เดินกลับเข้าบ้าน\n'
           'unknown layout: 中文\tไทย  -  details\n'
           'unstructured note 📖\n'
           ' \n'
           '李来福 เดินกลับเข้าบ้าน')
    original = novel + '\nคำศัพท์ใหม่\n' + raw
    editor = ws.editor._current_editor()
    editor.setPlainText(original)
    def no_review_prompt(self):
        assert self.windowTitle() != 'ตรวจรายการคำศัพท์ก่อน Export'
        return QMessageBox.Yes
    monkeypatch.setattr(QMessageBox, 'exec', no_review_prompt)
    assert w.update_context_from_translator(ws)
    assert source.read_text(encoding='utf-8').rstrip('\n') == novel
    assert editor.toPlainText().rstrip('\n') == novel
    assert Path(p.context_path).read_bytes() == source.read_bytes()
    exports = list((Path(p.main_folder) / 'Context Exports').glob('*.txt'))
    assert len(exports) == 1
    assert exports[0].read_bytes() == source.read_bytes()
    queue = load_queue(w.repo, p.id)['items']
    assert len(queue) == 1 and queue[0]['text'] == raw and queue[0]['count'] == 4
    assert QApplication.clipboard().text() == raw
    assert w.update_context_from_translator(ws)
    assert len(load_queue(w.repo, p.id)['items']) == 1


def test_unbounded_heading_preserves_context_and_source(translator):
    w, p, ws, source, errors = translator
    original = 'บทที่ 750\nเนื้อเรื่อง\nคำศัพท์ใหม่\nanything'
    ws.editor._current_editor().setPlainText(original)
    old_context = Path(p.context_path).read_bytes()
    assert not w.update_context_from_translator(ws)
    assert source.read_text(encoding='utf-8').rstrip('\n') == original
    assert Path(p.context_path).read_bytes() == old_context
    assert not load_queue(w.repo, p.id)['items']
