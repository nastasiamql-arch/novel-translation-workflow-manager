"""Run separately for each QT_SCALE_FACTOR so Qt actually uses that DPI."""
import os
import sys
import tempfile
from pathlib import Path
from datetime import date
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtGui import QFontDatabase
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QAbstractButton,QLineEdit,QSpinBox,QLabel,QWidget
from novel_workflow.storage import ProjectRepository
from novel_workflow.models import NovelProfile, StepFile
from novel_workflow.workspace_window import MainWindow
from novel_workflow.main import _configure_font


def assert_layout(widget):
    def check(layout):
        rectangles=[]
        for index in range(layout.count()):
            item=layout.itemAt(index)
            child=item.widget()
            if child and not child.isVisible(): continue
            if item.spacerItem(): continue
            rect=item.geometry()
            assert rect.top()>=0 and rect.left()>=0, (widget.objectName(),rect)
            assert rect.right()<widget.width() and rect.bottom()<widget.height(), (widget.objectName(),rect,widget.size())
            for previous in rectangles: assert not rect.intersects(previous),(widget.objectName(),rect,previous)
            rectangles.append(rect)
            if child:
                if isinstance(child,(QLabel,QAbstractButton)) and child.text():
                    assert child.height() >= child.fontMetrics().height(), (child.text(),child.size(),child.fontMetrics().height())
                assert_layout(child)
            elif item.layout(): check(item.layout())
    if widget.layout(): check(widget.layout())


def main():
    app=QApplication([]); app.setQuitOnLastWindowClosed(False)
    # Windows offscreen uses FreeType; register installed fonts without bundling them.
    fonts=Path(os.environ.get("WINDIR", "C:/Windows"))/"Fonts"
    for filename in ("segoeui.ttf","LeelawUI.ttf","tahoma.ttf","msyh.ttc","YuGothR.ttc","seguisym.ttf"):
        if (fonts/filename).is_file(): QFontDatabase.addApplicationFont(str(fonts/filename))
    _configure_font(app)
    with tempfile.TemporaryDirectory() as directory:
        root=Path(directory); repo=ProjectRepository(root/'data')
        settings=repo.load_settings(); settings.last_update_check_date=date.today().isoformat(); repo.save_settings(settings)
        context=root/'Context.md'; context.write_text('บทที่ 123\n中文 日本語 English',encoding='utf-8')
        p=NovelProfile(name='ชื่อเรื่องยาว ภาษาไทย 中文 日本語 English '*8,context_path=str(context))
        p.workflow.steps[0].files = [StepFile(label="ไฟล์แนบภาษาไทย 中文 日本語 " + str(i), path=f"file{i}.txt") for i in range(6)]
        repo.save_profile(p)
        win=MainWindow(repo); win.show()
        ws=win.workspaces[p.id]
        for name in ['ชื่อไฟล์ยาวภาษาไทย'*6+'.txt','中文文件名'*10+'.txt','日本語.txt','English.txt']:
            path=root/name; path.write_text('ไทย 中文 日本語 English',encoding='utf-8'); ws.editor.open_file(path)
        for theme in ('Light','Dark'):
            win.settings.appearance=theme; win.apply_theme()
            for width,height in ((900,600),(1440,860)):
                win.resize(width,height); app.processEvents(); QTest.qWait(30)
                assert win.width()==width and win.height()==height,(win.size(),width,height)
                ws.editor.tabs.setCurrentWidget(ws.editor.export_tab); app.processEvents()
                assert_layout(ws.editor.export_tab)
                assert not win.brand_toolbar.isVisible()
                assert ws.mapTo(win.centralWidget(), ws.rect().topLeft()).y() == 0
                export = ws.editor.export_tab
                assert export.editor.geometry().left() == 0
                assert export.editor.geometry().right() == export.width()-1
                assert ws.editor.export_tab.editor.viewport().height() >= 80,(theme,width,ws.editor.export_tab.editor.viewport().size(),ws.editor.export_tab.size(),ws.novel_header.size())
                ws.editor.export_tab.advanced_button.setChecked(True); app.processEvents()
                assert_layout(ws.editor.export_tab)
                ws.editor.export_tab.advanced_button.setChecked(False); app.processEvents()
                assert_layout(ws.editor_header)
                assert_layout(ws.novel_header)
                assert_layout(win.navigation)
                assert win.navigation.width() == 60
                assert all(button.toolButtonStyle() == Qt.ToolButtonIconOnly
                           for button in win.navigation.buttons.values())
                bar=ws.editor.tabs.tabBar()
                rects=[bar.tabRect(i) for i in range(bar.count())]
                assert len({r.top() for r in rects})==1
                for a,b in zip(rects,rects[1:]): assert not a.intersects(b)
                assert ws.editor.tabs.indexOf(ws.editor.export_tab)==bar.count()-1
                assert bar.tabButton(bar.count()-1,bar.ButtonPosition.RightSide) is None
                assert bar.tabButton(bar.count()-1,bar.ButtonPosition.LeftSide) is None
                for button in ws.editor_header.findChildren(QAbstractButton):
                    if button.isVisible(): assert button.height()>=button.fontMetrics().height()
                assert 'แปลถึงบท 123' in ws.novel_header.progress.text()
                assert ws.workspace_splitter.count() == 2
                if os.environ.get("PALANTIR_UI_CAPTURE"):
                    Path("build").mkdir(exist_ok=True)
                    win.grab().save(f"build/ui-{theme}-{width}.png")
        for key in ("library", "progress", "groups", "settings", "workspace"):
            win.navigate(key); win.resize(900,600); app.processEvents()
            assert not win.brand_toolbar.isVisible()
            assert win.width()==900 and win.height()==600,(key,win.size())
            if key == "progress":
                statistics = win.utility_stack.currentWidget()
                statistics.goal_disclosure.setChecked(True)
                app.processEvents(); assert_layout(statistics); assert_layout(statistics.body)
                statistics.goal_disclosure.setChecked(False)
            if key in ("progress","groups","settings"):
                assert_layout(win.utility_page)
                assert_layout(win.utility_stack.currentWidget())
            if key == "settings":
                for appearance in ("Light", "Dark"):
                    win.settings.appearance=appearance; win.apply_theme()
                    for dimensions in ((900,600),(1440,860)):
                        win.resize(*dimensions); app.processEvents(); QTest.qWait(30)
                        assert win.files.visualItemRect(win.files.item(5)).bottom() < win.files.viewport().height()
                        for child in win.utility_stack.currentWidget().findChildren(QWidget):
                            if child.isVisible() and child.layout(): assert_layout(child)

            if os.environ.get("PALANTIR_UI_CAPTURE"):
                Path("build").mkdir(exist_ok=True)
                win.grab().save(f"build/ui-{key}.png")
        win.close(); app.processEvents()
    print('DPI geometry passed',os.environ.get('QT_SCALE_FACTOR','1.0'))
    return 0

if __name__=='__main__': raise SystemExit(main())
