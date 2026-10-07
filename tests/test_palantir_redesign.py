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
    button.setFocus(Qt.TabFocusReason)
    QApplication.processEvents()
    image = button.grab().toImage()
    assert image.pixelColor(4, image.height() - 1).name().upper() == theme_colors(appearance)['focus']


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

@pytest.mark.parametrize('legacy_collapsed', [False, True])
def test_navigation_is_always_icon_only(legacy_collapsed):
    from novel_workflow.shell_components import NavigationSidebar
    from PySide6.QtWidgets import QToolButton
    app = QApplication.instance() or QApplication([])
    sidebar = NavigationSidebar(legacy_collapsed)
    sidebar.resize(240, 600)
    sidebar.show()
    app.processEvents()
    assert sidebar.width() == 60
    assert sidebar.collapsed
    assert len(sidebar.findChildren(QToolButton)) == 5
    for key, button in sidebar.buttons.items():
        assert button.toolButtonStyle() == Qt.ToolButtonIconOnly
        assert button.toolTip() and button.accessibleName()
    sidebar.select('groups')
    assert sidebar.buttons['groups'].isChecked()
    sidebar.close()


def test_shell_ignores_legacy_expanded_navigation_width(window):
    assert window.navigation.width() == 60
    assert all(button.toolButtonStyle() == Qt.ToolButtonIconOnly
               for button in window.navigation.buttons.values())


def test_unchanged_context_is_not_read_repeatedly(tmp_path, monkeypatch):
    from novel_workflow.translation_progress import sync_profile_context
    path = tmp_path / 'Context.md'
    path.write_text('Chapter 12', encoding='utf-8')
    profile = NovelProfile(context_path=str(path))
    original = Path.read_text
    reads = []
    def tracked(self, *args, **kwargs):
        if self == path: reads.append(self)
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', tracked)
    sync_profile_context(profile)
    sync_profile_context(profile)
    assert len(reads) == 1
    path.write_text('Chapter 123', encoding='utf-8')
    sync_profile_context(profile)
    assert profile.chapter_state.current_chapter == 123
    assert len(reads) == 2


def test_profile_mouse_press_does_not_load_details():
    from novel_workflow.workspace_window import ReorderableProfileList
    app = QApplication.instance() or QApplication([])
    listing = ReorderableProfileList()
    listing.addItems(['one', 'two'])
    listing.resize(300, 200); listing.show(); app.processEvents()
    activated = []
    listing.selectionCommitted.connect(activated.append)
    point = listing.visualItemRect(listing.item(1)).center()
    QTest.mousePress(listing.viewport(), Qt.LeftButton, pos=point)
    assert activated == []
    QTest.mouseRelease(listing.viewport(), Qt.LeftButton, pos=point)
    assert activated == [1]
    listing.close()


def test_desktop_drag_starts_on_movement_with_preview(monkeypatch):
    from PySide6.QtCore import QPoint, QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    import novel_workflow.workspace_window as module
    app = QApplication.instance() or QApplication([])
    listing = module.ReorderableProfileList()
    listing.addItems(['one', 'two'])
    listing.resize(300, 200); listing.show(); app.processEvents()
    started = []
    class Drag:
        def __init__(self, source): pass
        def setMimeData(self, data): assert data.formats()
        def setPixmap(self, pixmap): assert not pixmap.isNull()
        def setHotSpot(self, point): pass
        def exec(self, *args): started.append(True); return Qt.IgnoreAction
    import novel_workflow.profile_list as drag_module
    monkeypatch.setattr(drag_module, 'QDrag', Drag)
    point = listing.visualItemRect(listing.item(0)).center()
    QTest.mousePress(listing.viewport(), Qt.LeftButton, pos=point)
    moved = point + QPoint(QApplication.startDragDistance() + 2, 0)
    event = QMouseEvent(QEvent.MouseMove, QPointF(moved), QPointF(moved), Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(listing.viewport(), event)
    assert started == [True]
    listing.close()


def test_profile_reorder_updates_selection_mapping_and_survives_restart(window):
    for name in ('two', 'three'):
        window.repo.save_profile(NovelProfile(name=name))
    window.refresh_profiles()
    ids = list(reversed([p.id for p in window.ps_list]))
    window._persist_profile_order(ids)
    assert [p.id for p in window.ps_list] == ids
    assert [p.id for p in window.repo.list_profiles()] == ids


def test_all_focus_tokens_are_neutral_and_profile_delegate_removes_frame():
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QStyle, QStyleOptionViewItem
    from novel_workflow.theme import theme_colors
    from novel_workflow.workspace_window import ReorderableProfileList
    app = QApplication.instance() or QApplication([])
    for appearance in ('Dark', 'Light'):
        color = QColor(theme_colors(appearance)['focus'])
        assert color.red() == color.green() == color.blue()
    listing = ReorderableProfileList(); listing.addItem('novel')
    option = QStyleOptionViewItem()
    option.state = QStyle.State_HasFocus | QStyle.State_Selected
    listing.itemDelegate().initStyleOption(option, listing.model().index(0, 0))
    assert not option.state & QStyle.State_HasFocus
    assert option.font.bold()


def test_library_covers_support_drag_reordering(window):
    assert window.profile_cards.dragEnabled()
    assert window.profile_cards.acceptDrops()
    assert hasattr(window.profile_cards, 'orderChanged')


def test_settings_shows_six_complete_attachment_rows(window):
    from novel_workflow.models import StepFile
    step = window.profile.workflow.steps[0]
    step.files = [StepFile(label=f'ไฟล์แนบภาษาไทย 中文 {i}', path=f'file{i}.txt') for i in range(6)]
    window.repo.save_profile(window.profile)
    window.settings_dialog()
    QApplication.processEvents()
    listing = window.files
    listing.setStyleSheet("QListWidget { font-size: 24pt; }")
    QApplication.processEvents()
    assert listing.count() == 6
    assert listing.visualItemRect(listing.item(5)).bottom() < listing.viewport().height()


def test_drop_reorders_at_target_and_emits_only_final_order():
    from PySide6.QtCore import QPointF, QMimeData
    from PySide6.QtGui import QDropEvent
    from novel_workflow.workspace_window import ReorderableProfileList
    app = QApplication.instance() or QApplication([])
    listing = ReorderableProfileList(); listing.resize(300,300)
    for name in ('a','b','c'):
        listing.addItem(name); listing.item(listing.count()-1).setData(Qt.UserRole,name)
    listing.show(); app.processEvents()
    listing.setCurrentRow(0)
    listing._drag_profile_id = 'a'
    data = listing.mimeData([listing.item(0)])
    point = listing.visualItemRect(listing.item(2)).bottomLeft()
    event = QDropEvent(QPointF(point), Qt.MoveAction, data, Qt.LeftButton, Qt.NoModifier)
    orders = []; listing.orderChanged.connect(orders.append)
    listing.dropEvent(event)
    assert [listing.item(i).data(Qt.UserRole) for i in range(3)] == ['b','c','a']
    assert orders == [['b','c','a']]
    assert event.isAccepted()
    listing.close()


def test_library_drop_changes_persistent_order_and_preserves_active_profile(window):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QDropEvent
    for name in ('two','three'):
        window.repo.save_profile(NovelProfile(name=name))
    window.refresh_profiles()
    window.show_library(); QApplication.processEvents()
    active = window.profile.id
    cards = window.profile_cards
    first = cards.item(0).data(Qt.UserRole)
    cards.setCurrentRow(0); cards._drag_profile_id = first
    point = cards.visualItemRect(cards.item(2)).topRight()
    event = QDropEvent(QPointF(point), Qt.MoveAction,
                       cards.mimeData([cards.item(0)]), Qt.LeftButton, Qt.NoModifier)
    cards.dropEvent(event)
    assert event.isAccepted()
    assert cards.item(2).data(Qt.UserRole) == first
    assert [p.id for p in window.repo.list_profiles()] == [cards.item(i).data(Qt.UserRole) for i in range(3)]
    assert window.profile.id == active
    window.repo.save_profile(window.profile)
    assert window.repo.list_profiles()[2].id == first


def test_attachment_multiselect_shortcuts_and_batch_remove(window):
    from novel_workflow.models import StepFile
    step=window.profile.workflow.steps[0]
    step.files=[StepFile(label=f'file {i}',path=f'{i}.txt',order=i) for i in range(5)]
    window.repo.save_profile(window.profile);window.settings_dialog();QApplication.processEvents()
    listing=window.files
    QTest.mouseClick(listing.viewport(),Qt.LeftButton,pos=listing.visualItemRect(listing.item(0)).center())
    QTest.mouseClick(listing.viewport(),Qt.LeftButton,Qt.ControlModifier,pos=listing.visualItemRect(listing.item(2)).center())
    assert len(listing.selectedItems()) == 2
    window.remove_file()
    assert [f.label for f in window.step().files] == ['file 1','file 3','file 4']
    listing.setFocus();QTest.keyClick(listing,Qt.Key_A,Qt.ControlModifier)
    assert len(listing.selectedItems()) == 3


def test_batch_move_preserves_selected_relative_order(window):
    from novel_workflow.models import StepFile
    step=window.profile.workflow.steps[0]
    step.files=[StepFile(label=str(i),path=f'{i}.txt',order=i) for i in range(5)]
    window.repo.save_profile(window.profile);window.settings_dialog();QApplication.processEvents()
    for i in (1,2): window.files.item(i).setSelected(True)
    window.move_file(-1)
    assert [f.label for f in window.step().files] == ['1','2','0','3','4']
    assert len(window.files.selectedItems()) == 2
    assert window.file().label == '1'


def test_cover_gap_resolves_to_nearest_slot(window):
    from PySide6.QtCore import QPoint
    for name in ('two','three'): window.repo.save_profile(NovelProfile(name=name))
    window.refresh_profiles();window.show_library();QApplication.processEvents()
    cards=window.profile_cards
    first=cards.visualItemRect(cards.item(0)); second=cards.visualItemRect(cards.item(1))
    gap=QPoint(first.right()+1,first.center().y())
    assert cards._drop_row(gap) in (0,1)


def test_working_files_batch_open_and_remove(window,monkeypatch):
    from novel_workflow.models import StepFile
    window.profile.working_files=[StepFile(label=str(i),path=f'{i}.txt',order=i) for i in range(3)]
    window.repo.save_profile(window.profile);window.settings_dialog();QApplication.processEvents()
    listing=window.working_files;listing.item(0).setSelected(True);listing.item(2).setSelected(True)
    opened=[];monkeypatch.setattr(window,'open_working_file',opened.append)
    window.open_selected_working_file()
    assert set(opened)=={listing.item(0).data(Qt.UserRole),listing.item(2).data(Qt.UserRole)}
    window.remove_working_file()
    assert [file.label for file in window.profile.working_files] == ['1']


def test_shift_selects_attachment_range(window):
    from novel_workflow.models import StepFile
    window.profile.workflow.steps[0].files=[StepFile(label=str(i),path=str(i),order=i) for i in range(5)]
    window.repo.save_profile(window.profile);window.settings_dialog();QApplication.processEvents()
    listing=window.files
    QTest.mouseClick(listing.viewport(),Qt.LeftButton,pos=listing.visualItemRect(listing.item(1)).center())
    QTest.mouseClick(listing.viewport(),Qt.LeftButton,Qt.ShiftModifier,pos=listing.visualItemRect(listing.item(4)).center())
    assert len(listing.selectedItems()) == 4


def test_drag_edge_scroll_and_cancel_clears_marker():
    from PySide6.QtCore import QPoint
    from novel_workflow.profile_list import ReorderableProfileList
    app=QApplication.instance() or QApplication([])
    listing=ReorderableProfileList();listing.resize(300,180);listing.addItems([str(i) for i in range(30)])
    listing.show();app.processEvents()
    listing._show_drag_target(QPoint(50,listing.viewport().height()-1))
    assert listing._marker is not None
    listing._scroll_drag_edge()
    assert listing.verticalScrollBar().value()>0
    listing._clear_drag_target()
    assert listing._marker is None and not listing._edge_scroll.isActive()
    assert [listing.item(i).text() for i in range(30)] == [str(i) for i in range(30)]
    listing.close()


def test_progress_refresh_defers_io_during_drag(window,monkeypatch):
    def forbidden():raise AssertionError('Disk scan while dragging')
    original=window.repo.list_profiles
    window.profile_cards._dragging=True
    monkeypatch.setattr(window.repo,'list_profiles',forbidden)
    assert window.refresh_translation_progress() is window.ps_list
    window.profile_cards._dragging=False
    window.context_refresh_timer.stop()
    monkeypatch.setattr(window.repo,'list_profiles',original)


def test_file_manager_batch_attach_and_delete_cancel(window,monkeypatch):
    from PySide6.QtWidgets import QListWidget,QPushButton
    root=window.repo.profile_dir(window.profile.id)
    for name in ('one.txt','two.txt'):(root/name).write_text(name,encoding='utf-8')
    window.file_manager();QApplication.processEvents()
    page=window.utility_stack.currentWidget();listing=page.findChild(QListWidget,'fileManagerList')
    for i in range(listing.count()):
        if listing.item(i).text() in ('one.txt','two.txt'):listing.item(i).setSelected(True)
    next(b for b in page.findChildren(QPushButton) if b.text()=='เพิ่มในขั้นตอน').click()
    assert {'one.txt','two.txt'} <= {file.path for file in window.step().files}
    monkeypatch.setattr(QMessageBox,'question',lambda *args:QMessageBox.No)
    next(b for b in page.findChildren(QPushButton) if b.text()=='ลบไฟล์').click()
    assert (root/'one.txt').exists() and (root/'two.txt').exists()


def test_file_lists_and_launch_targets_allow_multiple_selection(window):
    from PySide6.QtWidgets import QAbstractItemView
    from novel_workflow.models import LaunchTarget
    workspace=window.workspaces[window.profile.id]
    assert workspace.files.selectionMode()==QAbstractItemView.ExtendedSelection
    assert workspace.file_tree.selectionMode()==QAbstractItemView.ExtendedSelection
    window.profile.launch_targets=[LaunchTarget(label=str(i),kind='file',target=f'{i}.txt',order=i) for i in range(3)]
    window.repo.save_profile(window.profile);window.settings_dialog();QApplication.processEvents()
    for listing in (window.files,window.working_files,window.settings_launch_targets):
        assert listing.selectionMode()==QAbstractItemView.ExtendedSelection
    window.settings_launch_targets.selectAll();window.remove_settings_launch_target()
    assert window.profile.launch_targets==[]


def test_workspace_fills_content_edges_without_brand_toolbar(window):
    from PySide6.QtWidgets import QToolBar
    window.navigate('workspace'); QApplication.processEvents()
    toolbar=window.findChild(QToolBar,'mainToolbar')
    assert not toolbar.isVisible()
    workspace=window.workspaces[window.profile.id]
    assert workspace.mapTo(window.centralWidget(),workspace.rect().topLeft()).y() == 0
    export=workspace.editor.export_tab
    workspace.editor.tabs.setCurrentWidget(export); QApplication.processEvents()
    assert export.editor.geometry().left() == 0
    assert export.editor.geometry().right() == export.width()-1
    assert export.submit_button.mapTo(export,export.submit_button.rect().topRight()).x() < export.width()-1
    window.navigate('library'); QApplication.processEvents()
    assert toolbar.isVisible()
    window.navigate('workspace'); QApplication.processEvents()
    assert not toolbar.isVisible()
    assert window.menuBar().isVisible()
