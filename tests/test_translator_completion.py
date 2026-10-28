import hashlib
import json
import os
from dataclasses import asdict
from datetime import datetime, timezone, timedelta, date
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
from PySide6.QtWidgets import QApplication, QMessageBox, QLabel
from novel_workflow.models import NovelProfile, StepFile
from novel_workflow.storage import ProjectRepository
from novel_workflow.translation_progress import daily_chapter_count, goal_progress, sync_profile_context
from test_polish_history_ui import window


def record(p, chapters, event_id='event', when=None):
    from novel_workflow.translation_progress import record_translator_export
    return record_translator_export(p, chapters, source_path='Translator.txt',
        digest=hashlib.sha256(b'translation').hexdigest(), exported_path='Export.txt',
        event_id=event_id, completed_at=when or datetime.now().astimezone())


@pytest.mark.parametrize('chapters,count', [([1],1),(list(range(6,11)),5),([6,10],2),([],0)])
def test_count_actual_confirmed_chapters(chapters,count):
    p=NovelProfile(); record(p,chapters)
    assert daily_chapter_count(p)==count


def test_disjoint_overlap_repeats_restart_and_event_retry(tmp_path):
    p=NovelProfile(); repo=ProjectRepository(tmp_path)
    record(p,list(range(6,11)),'first'); assert daily_chapter_count(p)==5
    record(p,list(range(11,16)),'second'); assert daily_chapter_count(p)==10
    record(p,list(range(6,11)),'typo'); assert daily_chapter_count(p)==10
    repo.save_profile(p); p=repo.list_profiles()[0]
    record(p,list(range(11,16)),'second')
    assert daily_chapter_count(p)==10
    assert len(p.translator_export_events)==3
    record(p,[14,15,20],'extra'); assert daily_chapter_count(p)==11


def test_context_and_legacy_statistics_never_count_completed(tmp_path):
    context=tmp_path/'Context.md'; context.write_text('Chapter 150',encoding='utf-8')
    p=NovelProfile(context_path=str(context),translation_daily_activity={'2026-10-13':[1,2]},translation_goal_target=5,translation_goal_baseline=1)
    original=p.translation_daily_activity.copy()
    sync_profile_context(p)
    assert p.chapter_state.current_chapter==150
    assert p.translation_daily_activity==original
    assert daily_chapter_count(p,'2026-10-13')==0
    assert goal_progress(p)==(0,5,0)


def test_daily_midnight_and_global_dedup():
    p=NovelProfile()
    tz=timezone(timedelta(hours=7))
    record(p,[6,7],'one',datetime(2026,10,13,23,59,59,tzinfo=tz))
    record(p,[7,8],'two',datetime(2026,10,14,0,0,1,tzinfo=tz))
    record(p,[6,7],'three',datetime(2026,10,14,0,1,tzinfo=tz))
    assert daily_chapter_count(p,'2026-10-13')==2
    assert daily_chapter_count(p,'2026-10-14')==1


def test_goal_overflow_manual_reset_preserves_events():
    from novel_workflow.translation_progress import reset_goal_progress, restart_completed_goal_cycles
    p=NovelProfile(translation_goal_target=5)
    record(p,list(range(1,8)))
    assert goal_progress(p)==(7,5,100)
    assert not restart_completed_goal_cycles(p)
    assert goal_progress(p)==(7,5,100)
    before=asdict(p)['translator_export_events']
    assert reset_goal_progress(p)
    assert goal_progress(p)==(0,5,0)
    assert p.translator_export_events==before
    assert daily_chapter_count(p)==7


@pytest.fixture
def translator(window,tmp_path,monkeypatch):
    w,p,ws,errors=window
    source=w.repo.profile_dir(p.id)/'ExampleTranslator.txt'
    source.write_bytes('บทที่ 6-10\nข้อความแปล'.encode())
    p.working_files=[StepFile(path=source.name)]
    p.workflow.steps[1].files=[StepFile(path=source.name),StepFile(reference_type='external_file',path=p.context_path)]
    w.repo.save_profile(p)
    ws.editor.open_file(source)
    monkeypatch.setattr(QMessageBox,'exec',lambda *a: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox,'information',lambda *a: QMessageBox.Ok)
    return w,p,ws,source,errors


def test_real_translator_export_counts_only_success_and_preserves_snapshot(translator):
    w,p,ws,source,errors=translator
    before=Path(p.context_path).read_bytes()
    assert w.update_context_from_translator(ws)
    saved=w.repo.list_profiles()[0]
    assert daily_chapter_count(saved)==5
    assert saved.verified_export_history==[]
    event=saved.translator_export_events[0]
    assert event['chapters']==list(range(6,11)) and event['status']=='committed'
    assert event['sha256']==hashlib.sha256(source.read_bytes()).hexdigest()
    assert Path(p.context_path).read_bytes()==source.read_bytes()
    snapshot=w.polish_history.list(saved)[0]
    context_entry=next(e for e in snapshot.manifest['files'] if e['is_context'])
    assert (snapshot.path/context_entry['snapshot_path']).read_bytes()==before
    assert w.update_context_from_translator(ws)
    assert daily_chapter_count(w.repo.list_profiles()[0])==5
    assert not errors


def test_real_exports_6_to_10_then_11_to_15_and_corrections_count_ten(translator):
    w,p,ws,source,errors=translator
    p.translation_goal_target=5; w.repo.save_profile(p)
    original_step=w.si
    QApplication.clipboard().setText('unrelated clipboard')
    assert w.update_context_from_translator(ws)
    assert daily_chapter_count(w.repo.list_profiles()[0])==5
    editor=ws.editor._current_editor(); editor.setPlainText('บทที่ 11–15\nรอบใหม่')
    assert w.update_context_from_translator(ws)
    saved=w.repo.list_profiles()[0]
    assert daily_chapter_count(saved)==10 and goal_progress(saved)==(10,5,100)
    from PySide6.QtGui import QTextCursor
    editor.moveCursor(QTextCursor.End); editor.insertPlainText('แก้คำผิด')
    assert w.update_context_from_translator(ws)
    saved=w.repo.list_profiles()[0]
    assert daily_chapter_count(saved)==10 and goal_progress(saved)==(10,5,100)
    assert w.si==original_step and QApplication.clipboard().text()=='unrelated clipboard'
    assert 'วันนี้ +10 บท' in w.progress_status.fullText()
    assert 'วันนี้ +' not in ws.novel_header.progress.text()
    assert not errors


def test_real_sparse_headings_export_only_confirmed_chapters(translator):
    w,p,ws,source,errors=translator
    editor=ws.editor._current_editor()
    editor.setPlainText('บทที่ 6\nเนื้อหา\nบทที่ 10\nเนื้อหา')
    assert w.update_context_from_translator(ws)
    saved=w.repo.list_profiles()[0]
    assert saved.translator_export_events[0]['chapters']==[6,10]
    assert daily_chapter_count(saved)==2
    assert 'Export ล่าสุด: บท 6, 10' in ws.novel_header.progress.text()


def test_no_heading_export_never_guesses_from_manual_snapshot_range(translator,monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    w,p,ws,source,errors=translator
    ws.editor._current_editor().setPlainText('เนื้อหาที่ไม่มีหัวบท')
    monkeypatch.setattr(QInputDialog,'getText',lambda *args,**kw: ('6-10',True))
    assert w.update_context_from_translator(ws)
    saved=w.repo.list_profiles()[0]
    assert daily_chapter_count(saved)==0 and saved.translator_export_events[0]['chapters']==[]
    assert any('ไม่ได้เพิ่มยอด' in error for error in errors)


def test_dashboard_library_header_and_goal_agree(translator):
    from novel_workflow.progress_dialog import StatisticsPage
    w,p,ws,source,errors=translator
    p.translation_goal_target=5; w.repo.save_profile(p)
    assert w.update_context_from_translator(ws)
    saved=w.repo.list_profiles()[0]
    page=StatisticsPage(w,[saved],w.repo,w.repo.list_profiles)
    labels=[label.text() for label in page.findChildren(QLabel)]
    assert 'วันนี้แปลเพิ่ม 5 บท' not in labels
    assert any(label == '5 บท' for label in labels)
    assert all('verified' not in label.casefold() for label in labels)
    assert 'แปลสำเร็จ 5/5 บท ✓' in labels
    card=next(w.profile_cards.item(i) for i in range(w.profile_cards.count()) if w.profile_cards.item(i).data(256)==p.id)
    assert card.text() == saved.name
    assert 'วันนี้ +5 บท' in w.progress_status.fullText()
    assert 'วันนี้ +' not in ws.novel_header.progress.text()


def test_date_rollover_refreshes_header_without_new_exports(window,monkeypatch):
    import novel_workflow.translation_progress as progress
    w,p,ws,errors=window
    record(p,[1,2],'one',datetime(2026,10,13,23,59))
    w.repo.save_profile(p)
    monkeypatch.setattr(progress,'local_day',lambda *a:'2026-10-13')
    w.refresh_translation_progress()
    assert 'วันนี้ +2 บท' in w.progress_status.fullText()
    assert 'วันนี้ +' not in ws.novel_header.progress.text()
    monkeypatch.setattr(progress,'local_day',lambda *a:'2026-10-14')
    w.progress_timer.timeout.emit()
    assert 'วันนี้ +0 บท' in w.progress_status.fullText()
    assert 'วันนี้ +' not in ws.novel_header.progress.text()


@pytest.mark.parametrize('appearance',['Light','Dark'])
@pytest.mark.parametrize('width',[320,1000])
def test_completed_header_compact_geometry_and_tooltip(window,appearance,width):
    from novel_workflow.shell_components import NovelHeader
    from novel_workflow.theme import application_stylesheet
    w,p,ws,errors=window
    p.name='中文 Thai English · นิยายชื่อยาว'*10
    record(p,[2147483647])
    header=NovelHeader(w.repo); header.setStyleSheet(application_stylesheet(appearance))
    header.resize(width,80); header.refresh(p); header.show(); QApplication.processEvents()
    try:
        assert header.progress.wordWrap()
        assert header.progress.geometry().right()<header.close_button.geometry().left()
        assert header.progress.height()>=header.progress.fontMetrics().height()
        assert 'Translator Export' in header.progress.toolTip()
        assert 'วันนี้ส่ง' not in header.progress.text()
    finally: header.close(); header.deleteLater()


def test_statistics_failure_rolls_back_context_txt_status_and_count(translator,monkeypatch):
    w,p,ws,source,errors=translator
    context_before=Path(p.context_path).read_bytes()
    original=w.repo.save_profile
    def fail_statistics(profile,**kwargs):
        if getattr(profile,'translator_export_events',[]): raise OSError('statistics failure')
        return original(profile,**kwargs)
    monkeypatch.setattr(w.repo,'save_profile',fail_statistics)
    assert not w.update_context_from_translator(ws)
    assert Path(p.context_path).read_bytes()==context_before
    assert not list((Path(p.main_folder)/'Context Exports').glob('*.txt'))
    assert daily_chapter_count(w.repo.list_profiles()[0])==0
    assert w._translator_export_status(p.id,source)!='exported'


@pytest.mark.parametrize('moment',['before_write','after_write'])
def test_live_transaction_conflicts_preserve_external_context(translator,monkeypatch,moment):
    import novel_workflow.workspace_window as module
    w,p,ws,source,errors=translator
    commit=module.commit_staged
    context=Path(p.context_path)
    def external_edit(*args,**kwargs):
        if moment=='before_write': context.write_bytes(b'USER EXTERNAL WORK')
        else:
            verify=kwargs['commit_metadata']
            def changed():
                context.write_bytes(b'USER EXTERNAL WORK')
                verify()
            kwargs['commit_metadata']=changed
        return commit(*args,**kwargs)
    monkeypatch.setattr(module,'commit_staged',external_edit)
    assert not w.update_context_from_translator(ws)
    assert context.read_bytes()==b'USER EXTERNAL WORK'
    assert daily_chapter_count(w.repo.list_profiles()[0])==0


def test_external_edit_between_txt_and_context_commit_is_not_overwritten(translator,monkeypatch):
    import novel_workflow.recovery as recovery
    w,p,ws,source,errors=translator
    original=recovery.os.link
    context=Path(p.context_path)
    def linked(*args,**kwargs):
        original(*args,**kwargs)
        context.write_bytes(b'USER WORK DURING EXPORT')
    monkeypatch.setattr(recovery.os,'link',linked)
    assert not w.update_context_from_translator(ws)
    assert context.read_bytes()==b'USER WORK DURING EXPORT'
    assert daily_chapter_count(w.repo.list_profiles()[0])==0


def test_export_crossing_midnight_uses_post_context_completion_day(translator,monkeypatch):
    import novel_workflow.recovery as recovery
    import novel_workflow.workspace_window as module
    w,p,ws,source,errors=translator
    after_context={'value':False}
    original=recovery.replace_with_retry
    def replace(*args):
        original(*args)
        if Path(args[1])==Path(p.context_path): after_context['value']=True
    class Clock:
        @staticmethod
        def now():
            return datetime(2026,10,14,0,0,1) if after_context['value'] else datetime(2026,10,13,23,59,59)
    monkeypatch.setattr(recovery,'replace_with_retry',replace)
    monkeypatch.setattr(module,'datetime',Clock)
    assert w.update_context_from_translator(ws)
    saved=w.repo.list_profiles()[0]
    assert saved.translator_export_events[0]['local_date']=='2026-10-14'
    assert daily_chapter_count(saved,'2026-10-14')==5


@pytest.mark.parametrize('failure',['cancel','snapshot'])
def test_failed_or_cancelled_export_never_counts(translator,monkeypatch,failure):
    w,p,ws,source,errors=translator
    if failure=='cancel': monkeypatch.setattr(QMessageBox,'exec',lambda *a: QMessageBox.No)
    else: monkeypatch.setattr(w.polish_history,'create',lambda *a,**kw: (_ for _ in ()).throw(OSError('snapshot failure')))
    assert not w.update_context_from_translator(ws)
    assert daily_chapter_count(w.repo.list_profiles()[0])==0


def test_header_never_uses_default_context_chapter_or_verified_line(window):
    w,p,ws,errors=window
    p.chapter_state.current_chapter=323
    ws.novel_header.refresh(p,323)
    assert 'ยังไม่มี Export ที่ยืนยัน' in ws.novel_header.progress.text()
    assert 'วันนี้ส่ง' not in ws.novel_header.progress.text()
    record(p,[322,323])
    ws.novel_header.refresh(p,323)
    assert 'Export ล่าสุด: บท 322–323' in ws.novel_header.progress.text()
    assert daily_chapter_count(p) == 2
    assert 'วันนี้ +' not in ws.novel_header.progress.text()


@pytest.mark.parametrize('phase',['after_txt','after_context','after_statistics','after_commit'])
def test_real_process_crash_recovers_consistent_files_and_events(tmp_path,phase):
    import subprocess,sys
    context=tmp_path/'Context.md'; context.write_bytes(b'old context')
    repo=ProjectRepository(tmp_path/'data')
    p=NovelProfile(context_path=str(context),main_folder=str(tmp_path)); repo.save_profile(p)
    result=subprocess.run([sys.executable,str(Path(__file__).with_name('translator_crash_process.py')),str(repo.root),phase],timeout=30)
    assert result.returncode==7
    reopened=ProjectRepository(repo.root); restored=reopened.list_profiles()[0]
    expected=5 if phase=='after_commit' else 0
    assert daily_chapter_count(restored)==expected
    assert context.read_bytes()==(b'new translation' if expected else b'old context')
    exported=list((tmp_path/'Context Exports').glob('*.txt'))
    assert len(exported)==(1 if expected else 0)
    assert not (repo.profile_dir(p.id)/'translator_export_transaction.json').exists()
    assert daily_chapter_count(reopened.list_profiles()[0])==expected


@pytest.mark.parametrize('edited',['context','profile','txt','context_path','main_folder'])
def test_crash_recovery_preserves_external_work_and_blocks_incomplete_counts(tmp_path,edited):
    import subprocess,sys
    context=tmp_path/'Context.md'; context.write_bytes(b'old context')
    repo=ProjectRepository(tmp_path/'data')
    p=NovelProfile(context_path=str(context),main_folder=str(tmp_path)); repo.save_profile(p)
    result=subprocess.run([sys.executable,str(Path(__file__).with_name('translator_crash_process.py')),str(repo.root),'after_statistics'],timeout=30)
    assert result.returncode==7
    if edited=='context': path=context
    elif edited=='txt': path=next((tmp_path/'Context Exports').glob('*.txt'))
    else: path=repo.profile_dir(p.id)/'profile.json'
    if edited in {'profile','context_path','main_folder'}:
        raw=json.loads(path.read_text(encoding='utf-8'))
        if edited=='profile': raw['name']='USER NEW NAME'
        else: raw[edited]=str(tmp_path/'different')
        path.write_text(json.dumps(raw),encoding='utf-8')
    else: path.write_bytes(b'USER NEW WORK AFTER CRASH')
    before=path.read_bytes()
    reopened=ProjectRepository(repo.root); restored=reopened.list_profiles()[0]
    assert path.read_bytes()==before
    assert daily_chapter_count(restored)==0
    assert restored.id in reopened.export_recovery_errors
    assert (repo.profile_dir(p.id)/'translator_export_transaction.json').exists()
    with pytest.raises(OSError): reopened.save_profile(restored)


def test_safe_v312_migration_keeps_legacy_context_data_without_fake_exports(tmp_path):
    repo=ProjectRepository(tmp_path)
    p=NovelProfile(translation_daily_activity={'2026-10-12':[1,2,3]},translation_goal_target=5,translation_goal_baseline=323)
    repo.save_profile(p)
    path=repo.profile_dir(p.id)/'profile.json'
    raw=json.loads(path.read_text(encoding='utf-8'))
    for key in ['translator_export_events','translator_goal_baseline','translation_progress_version','legacy_translation_progress']:
        raw.pop(key)
    raw['schema_version']=8; path.write_text(json.dumps(raw),encoding='utf-8')
    restored=repo.list_profiles()[0]
    assert restored.translation_daily_activity=={'2026-10-12':[1,2,3]}
    assert restored.legacy_translation_progress['daily_activity']==restored.translation_daily_activity
    assert restored.translator_export_events==[]
    assert daily_chapter_count(restored,'2026-10-12')==0
    assert goal_progress(restored)==(0,5,0)
    assert repo.list_profiles()[0].translator_export_events==[]


def test_actual_parser_does_not_fill_gaps_or_count_bilingual_headings_twice():
    from novel_workflow.translation_progress import translator_chapters
    assert translator_chapters('[A]Chapter 6\n[B]บทที่ 6\n[A]Chapter 10'.encode())==[6,10]
    assert translator_chapters('บทที่ 6–10\nเนื้อหา'.encode())==list(range(6,11))
    assert translator_chapters('ไม่มีเลขบท'.encode())==[]


def test_profiles_daily_weekly_and_goal_share_confirmed_history():
    from novel_workflow.translation_progress import profile_week_count
    first,second=NovelProfile(),NovelProfile()
    record(first,[6,7],'one',datetime(2026,10,12,10))
    record(first,[7,8],'two',datetime(2026,10,13,10))
    assert daily_chapter_count(first,'2026-10-13')==1
    assert profile_week_count(first,date(2026,10,13))==3
    assert profile_week_count(second,date(2026,10,13))==0


def test_txt_submit_and_editor_autosave_never_count_translator_completion(translator,tmp_path):
    w,p,ws,source,errors=translator
    editor=ws.editor._current_editor(); editor.insertPlainText('correction')
    ws.editor._autosave_editor(editor)
    assert daily_chapter_count(w.repo.list_profiles()[0])==0
    panel=ws.editor.export_tab
    panel.directory.setText(str(tmp_path)); panel.editor.setPlainText('Chapter 16\nTXT only')
    assert panel.export()
    from test_polish_history_ui import wait_until
    wait_until(lambda: not w.history_busy())
    saved=w.repo.list_profiles()[0]
    assert saved.verified_goal_count==1 and len(saved.verified_export_history)==1
    assert daily_chapter_count(saved)==0
