import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
from PySide6.QtWidgets import QApplication, QMessageBox
from novel_workflow.models import NovelProfile
from novel_workflow.translation_progress import latest_context_chapter
from novel_workflow.workspace_editor import EditorTabs

@pytest.mark.parametrize('text,expected', [('บทที่ 159\nบทที่ 12',159), ('第123-125章\n第90章',125), ('Chapter 123-125\nChapter 10',125), ('บทที่ 125-123',None), ('body 999',None), ('## Chapter 123',123)])
def test_context_max_valid_heading(text, expected):
    assert latest_context_chapter(text) == expected

def test_verified_cycles_preserve_history():
    from novel_workflow.export_service import record_export, reset_verified_goal, verified_goal_text
    p = NovelProfile()
    p.verified_goal_target = 5
    for i in range(12): record_export(p, 'WSTverified1.txt', 'WSTverified', 1)
    assert verified_goal_text(p) == '12/5 ✓ · +7 เกินเป้า'
    reset_verified_goal(p)
    assert p.verified_goal_count == 0
    assert len(p.verified_export_history) == 12
    assert p.verified_goal_cycles[-1]['count'] == 12

def test_export_tab_stays_last(tmp_path):
    app = QApplication.instance() or QApplication([])
    tabs = EditorTabs()
    for name in ['ชื่อไฟล์ยาวภาษาไทย.txt', '中文长文件名.txt']:
        path = tmp_path/name; path.write_text('text', encoding='utf-8'); tabs.open_file(path)
    assert tabs.tabs.indexOf(tabs.export_tab) == tabs.tabs.count()-1
    tabs.tabs.tabBar().moveTab(tabs.tabs.count()-1, 0)
    assert tabs.tabs.indexOf(tabs.export_tab) == tabs.tabs.count()-1
from datetime import date
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLineEdit, QTextEdit
from novel_workflow.storage import ProjectRepository
from novel_workflow.workspace_window import MainWindow
from novel_workflow.workspace_editor import CodeEditor
from novel_workflow.export_service import ExportService, record_export, daily_export_count, verified_goal_text

@pytest.fixture
def window(tmp_path, monkeypatch):
    def unexpected_warning(_parent, title, message, *_args):
        raise AssertionError(f'{title}: {message}')
    monkeypatch.setattr(QMessageBox, 'warning', unexpected_warning)
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    repo = ProjectRepository(tmp_path/'data')
    settings = repo.load_settings(); settings.last_update_check_date=date.today().isoformat(); repo.save_settings(settings)
    context=tmp_path/'Context.md'; context.write_text('บทที่ 123',encoding='utf-8')
    profile=NovelProfile(name='นิยายชื่อยาว 中文 日本語 English '*5, context_path=str(context))
    profile.txt_export_settings.directory=str(tmp_path)
    repo.save_profile(profile)
    win=MainWindow(repo); win.show(); win.activateWindow(); QTest.qWait(30)
    yield win
    win.close(); app.processEvents()

@pytest.mark.parametrize('count,text', [(1,'1/5'),(5,'5/5 ✓'),(12,'12/5 ✓ · +7 เกินเป้า')])
def test_verified_unlimited_goal(count,text):
    p=NovelProfile(verified_goal_target=5)
    for i in range(count): record_export(p,f'WSTverified{i}.txt','WSTverified',i,timestamp='2026-10-07T12:00:00+07:00')
    assert verified_goal_text(p)==text
    assert daily_export_count(p,'2026-10-07')==count
    assert daily_export_count(p,'2026-10-06')==0

@pytest.mark.parametrize('failure', ['txt','context','context-lock','metadata'])
def test_failed_submit_restores_files_and_does_not_count(window,tmp_path,monkeypatch,failure):
    from novel_workflow import recovery
    ws=window.workspaces[window.profile.id]; panel=ws.editor.export_tab
    target=tmp_path/'segverified1.txt'; target.write_text('old TXT',encoding='utf-8')
    context=Path(window.profile.context_path)
    panel.editor.setPlainText('บทที่ 125\nnew')
    original=recovery.os.replace
    def replace(source,dest):
        if Path(dest)==(target if failure=='txt' else context) and str(source).endswith('.part'):
            if failure == 'context-lock':
                error = PermissionError('persistent Windows lock')
                error.winerror = 5
                raise error
            raise OSError('simulated locked file')
        return original(source,dest)
    if failure=='metadata':
        monkeypatch.setattr(panel.export_service,'commit',lambda *_: (_ for _ in ()).throw(OSError('disk full')))
    else: monkeypatch.setattr(recovery.os,'replace',replace)
    monkeypatch.setattr(QMessageBox,'warning',lambda *_:QMessageBox.Ok)
    assert not panel.export(update_context=True)
    assert target.read_text(encoding='utf-8')=='old TXT'
    assert context.read_text(encoding='utf-8')=='บทที่ 123'
    profile=window.repo.list_profiles()[0]
    assert profile.verified_goal_count==0 and profile.verified_export_history==[]
    assert panel.current.value()==1


def test_submit_retries_transient_windows_context_lock(window, monkeypatch):
    from novel_workflow import recovery
    context = Path(window.profile.context_path).resolve()
    original = recovery.os.replace
    attempts = []
    def replace(source, destination):
        if Path(destination) == context and str(source).endswith('.part'):
            attempts.append(source)
            if len(attempts) < 3:
                error = PermissionError('transient scanner lock')
                error.winerror = 5
                raise error
        return original(source, destination)
    monkeypatch.setattr(recovery.os, 'replace', replace)
    panel = window.workspaces[window.profile.id].editor.export_tab
    panel.editor.setPlainText('บทที่ 124')
    assert panel.export(update_context=True)
    assert len(attempts) == 3
    profile = window.repo.list_profiles()[0]
    assert profile.verified_goal_count == 1
    assert len(profile.verified_export_history) == 1
    assert context.read_text(encoding='utf-8') == 'บทที่ 124'


def test_goal_wrap_manual_reset_and_immediate_header(window,tmp_path):
    ws=window.workspaces[window.profile.id]; panel=ws.editor.export_tab
    panel.goal_target.setValue(5)
    panel.editor.setPlainText('บทที่ 124\nnew')
    for _ in range(12): assert panel.export(update_context=True)
    p=window.repo.list_profiles()[0]
    assert p.verified_goal_count==12
    assert panel.current.value()==3
    assert '12/5 ✓' in ws.novel_header.progress.text()
    assert 'แปลถึงบท 124' in ws.novel_header.progress.text()
    panel.goal_reset.click()
    p=window.repo.list_profiles()[0]
    assert p.verified_goal_count==0 and len(p.verified_export_history)==12
    assert p.verified_goal_cycles[-1]['count']==12
    assert '0/5' in ws.novel_header.progress.text()
    assert panel.current.value()==3
    assert list((tmp_path/'.palantir-recovery').glob('*.bak'))


def test_status_undo_restores_profile(window):
    pid=window.profile.id
    window.set_profile_status(pid,'paused')
    assert window.repo.list_profiles()[0].status=='paused'
    window.submit_toast.undo_button.click()
    assert window.repo.list_profiles()[0].status=='translating'

@pytest.mark.parametrize('kind',[CodeEditor,QTextEdit,QLineEdit])
def test_native_edit_shortcuts(kind):
    app=QApplication.instance() or QApplication([])
    widget=kind(); widget.show(); widget.activateWindow(); widget.setFocus(); QTest.qWait(20)
    text=lambda: widget.text() if isinstance(widget,QLineEdit) else widget.toPlainText()
    QTest.keyClicks(widget,'hello')
    QTest.keyClick(widget,Qt.Key_A,Qt.ControlModifier)
    QTest.keyClick(widget,Qt.Key_C,Qt.ControlModifier)
    assert app.clipboard().text()=='hello'
    QTest.keyClick(widget,Qt.Key_X,Qt.ControlModifier); assert text()==''
    QTest.keyClick(widget,Qt.Key_V,Qt.ControlModifier); assert text()=='hello'
    QTest.keyClick(widget,Qt.Key_Z,Qt.ControlModifier); assert text()==''
    QTest.keyClick(widget,Qt.Key_Y,Qt.ControlModifier); assert text()=='hello'
    QTest.keyClick(widget,Qt.Key_Z,Qt.ControlModifier); assert text()==''
    QTest.keyClick(widget,Qt.Key_Z,Qt.ControlModifier|Qt.ShiftModifier); assert text()=='hello'
    widget.close()


def test_tab_shortcuts_and_undo_buttons_follow_active_editor(window,tmp_path):
    ws=window.workspaces[window.profile.id]; tabs=ws.editor
    path=tmp_path/'long ไทย 中文 日本語.txt'; path.write_text('',encoding='utf-8')
    editor=tabs.open_file(path); editor.setFocus()
    assert not ws.undo_button.isEnabled() and not ws.redo_button.isEnabled()
    QTest.keyClicks(editor,'hello')
    assert ws.undo_button.isEnabled()
    ws.undo_button.click(); assert editor.toPlainText()=='' and ws.redo_button.isEnabled()
    ws.redo_button.click(); assert editor.toPlainText()=='hello'
    editor.setFocus(); QTest.keyClick(editor,Qt.Key_Tab,Qt.ControlModifier)
    assert tabs.tabs.currentWidget() is tabs.export_tab
    assert not ws.undo_button.isEnabled()
    export=tabs.export_tab.editor
    QTest.keyClicks(export,'export')
    assert ws.undo_button.isEnabled()
    QTest.keyClick(export,Qt.Key_Tab,Qt.ControlModifier|Qt.ShiftModifier)
    assert tabs.tabs.currentWidget() is editor
    QTest.keyClick(editor,Qt.Key_S,Qt.ControlModifier)
    assert path.read_text(encoding='utf-8')=='hello'
    assert editor.document().isUndoAvailable()
    QTest.keyClick(editor,Qt.Key_H,Qt.ControlModifier)
    assert tabs.find_panel.isVisible()


def test_context_replace_refreshes_active_undo_buttons(window):
    ws = window.workspaces[window.profile.id]
    path = Path(window.profile.context_path)
    editor = ws.editor.open_file(path)
    editor.setFocus()
    QTest.keyClicks(editor, 'changed')
    assert ws.undo_button.isEnabled()
    ws.editor.apply_external_update(path, 'บทที่ 130')
    assert not editor.document().isUndoAvailable()
    assert not ws.undo_button.isEnabled()
    assert not ws.redo_button.isEnabled()


def test_workspace_uses_library_navigation_without_cover_rail(window):
    ws = window.workspaces[window.profile.id]
    assert ws.workspace_splitter.count() == 2
    assert ws.workspace_splitter.widget(0) is ws.sidebar
    assert not hasattr(ws, 'novel_cover_rail')
    ws.toggle_sidebar()
    assert ws.workspace_splitter.sizes()[0] == 0
    ws.toggle_sidebar()
    assert ws.workspace_splitter.sizes()[0] > 0
    window.navigate('library')
    window._open_profile_card(window.profile_cards.item(0))
    assert window.main_pages.currentWidget() is window.workspace_stack


def test_mouse_focus_is_quiet_and_tab_focus_is_visible(window):
    button = window.navigation.buttons['library']
    QTest.mouseClick(button, Qt.LeftButton)
    assert not button.property('keyboardFocus')
    QTest.keyClick(button, Qt.Key_Tab)
    focused = QApplication.focusWidget()
    assert focused is not None and focused.property('keyboardFocus')
    QTest.mouseClick(window.navigation.buttons['workspace'], Qt.LeftButton)
    assert not window.navigation.buttons['workspace'].property('keyboardFocus')


@pytest.mark.parametrize('appearance', ['Light', 'Dark'])
def test_export_primary_action_renders_theme_contrast(window, appearance):
    from novel_workflow.theme import theme_colors
    window.settings.appearance = appearance
    window.apply_theme()
    ws = window.workspaces[window.profile.id]
    ws.editor.tabs.setCurrentWidget(ws.editor.export_tab)
    QApplication.processEvents()
    button = ws.editor.export_tab.submit_button
    image = button.grab().toImage()
    assert image.pixelColor(8, image.height() // 2).name().upper() == theme_colors(appearance)['primary']


def test_legacy_ranges_and_unknown_fields_preserved(tmp_path):
    import json
    from dataclasses import asdict
    repo=ProjectRepository(tmp_path/'data'); p=NovelProfile()
    data=asdict(p); data['schema_version']=6
    data['txt_export_settings']={'start':20,'end':80,'current':38,'custom_extension':'keep'}
    data['unknown']={'keep':True}
    data['workflow']['custom']='keep'
    folder=repo.profile_dir(p.id); folder.mkdir(parents=True)
    path=folder/'profile.json'; path.write_text(json.dumps(data),encoding='utf-8')
    loaded=repo.list_profiles()[0]; assert loaded.txt_export_settings.advanced_range
    assert (loaded.txt_export_settings.start,loaded.txt_export_settings.end,loaded.txt_export_settings.current)==(20,80,38)
    saved=json.loads(path.read_text(encoding='utf-8'))
    assert saved['unknown']=={'keep':True}
    assert saved['workflow']['custom']=='keep'
    assert saved['txt_export_settings']['custom_extension']=='keep'


def test_recovery_is_bounded_and_restorable(tmp_path):
    from novel_workflow.recovery import backup_file, restore_backup, BACKUP_LIMIT
    p=tmp_path/'Context.md'
    for i in range(15):
        p.write_text(f'บทที่ {i+1}',encoding='utf-8'); backup=backup_file(p)
    assert len(list((tmp_path/'.palantir-recovery').glob('*.bak')))==BACKUP_LIMIT
    p.write_text('wrong',encoding='utf-8'); restore_backup(p,backup)
    assert p.read_text(encoding='utf-8')=='บทที่ 15'

def test_copy_step_shortcut_is_distinct_from_copy(window,tmp_path):
    from novel_workflow.models import StepFile
    path=tmp_path/'chapter.txt'; path.write_text('copy me',encoding='utf-8')
    window.profile.workflow.steps[0].files.append(StepFile(label='chapter',reference_type='external_file',path=str(path)))
    window.repo.save_profile(window.profile); window.refresh_steps(); window.refresh_files()
    ws=window.workspaces[window.profile.id]; editor=ws.editor.open_file(path)
    editor.setFocus(); QTest.keyClick(editor,Qt.Key_A,Qt.ControlModifier)
    QTest.keyClick(editor,Qt.Key_C,Qt.ControlModifier)
    assert QApplication.clipboard().text()=='copy me'
    assert window.si==0
    QTest.keyClick(editor,Qt.Key_C,Qt.ControlModifier|Qt.ShiftModifier)
    assert [Path(url.toLocalFile()) for url in QApplication.clipboard().mimeData().urls()]==[path.resolve()]
    assert window.si==1


def test_preferences_and_draft_survive_restart(tmp_path):
    app=QApplication.instance() or QApplication([])
    repo=ProjectRepository(tmp_path/'data'); settings=repo.load_settings()
    settings.appearance='Light'; settings.editor_font_size=16
    settings.navigation_collapsed=True; settings.last_update_check_date=date.today().isoformat()
    repo.save_settings(settings); p=NovelProfile(); repo.save_profile(p)
    win=MainWindow(repo); ws=win.workspaces[p.id]
    ws.editor.export_tab.editor.setPlainText('draft ไทย 中文')
    win.close(); app.processEvents()
    saved=repo.load_settings()
    assert saved.appearance=='Light' and saved.editor_font_size==16
    assert saved.navigation_collapsed
    win=MainWindow(repo)
    assert win.workspaces[p.id].editor.export_tab.editor.toPlainText()=='draft ไทย 中文'
    win.close(); app.processEvents()

def test_recovery_can_restore_oldest_retained_copy(tmp_path):
    from novel_workflow.recovery import backup_file, restore_backup, BACKUP_LIMIT
    p=tmp_path/'Context.md'
    for i in range(BACKUP_LIMIT):
        p.write_text(f'Chapter {i+1}',encoding='utf-8'); backup_file(p)
    oldest=sorted((tmp_path/'.palantir-recovery').glob('*.bak'))[0]
    p.write_text('wrong',encoding='utf-8')
    restore_backup(p,oldest)
    assert p.read_text(encoding='utf-8')=='Chapter 1'
