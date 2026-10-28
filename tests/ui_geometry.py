"""Run separately for each QT_SCALE_FACTOR so Qt actually uses that DPI."""
import os
import sys
import tempfile
import time
from pathlib import Path
from datetime import date
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtGui import QFontDatabase
from PySide6.QtCore import Qt, QPoint, QPointF
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QAbstractButton,QLineEdit,QSpinBox,QLabel,QWidget,QToolButton,QListWidget,QListWidgetItem,QFrame,QPushButton
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
        # Check the same card rectangles at each CI QT_SCALE_FACTOR, not just
        # main-window layout widgets.
        cards = win.profile_cards
        delegate = cards.itemDelegate()
        regions = delegate.card_rects(
            cards.visualItemRect(cards.item(0)),
            title_text=cards.item(0).text())
        assert not regions["cover"].intersects(regions["title"])
        assert not regions["title"].intersects(regions["status"])
        assert not regions["status"].intersects(regions["progress"])
        assert cards.gridSize().height() >= regions['status'].bottom() - regions['cover'].top()

        for name in ['ชื่อไฟล์ยาวภาษาไทย'*3+'.txt','中文文件名'*6+'.txt','日本語.txt','English.txt']:
            path=root/name; path.write_text('ไทย 中文 日本語 English',encoding='utf-8'); ws.editor.open_file(path)
        for theme in ('Light','Dark'):
            win.settings.appearance=theme; win.apply_theme()
            for width,height in ((900,600),(1280,720),(1366,768),(1920,1080)):
                win.resize(width,height); app.processEvents(); QTest.qWait(30)
                cards = win.profile_cards
                if cards.count():
                    card_rect = cards.visualItemRect(cards.item(0))
                    regions = cards.itemDelegate().card_rects(
                        card_rect, title_text=cards.item(0).text())
                    assert card_rect.contains(regions["cover"])
                    assert card_rect.contains(regions["title"])
                    assert card_rect.contains(regions["status"])
                    assert card_rect.contains(regions["progress"])
                    tabs = win.library_status_tabs
                    for index in range(tabs.count()):
                        required = tabs.tabSizeHint(index).width()
                        font = tabs.font()
                        assert required >= __import__("PySide6.QtGui", fromlist=[
                            "QFontMetrics"]).QFontMetrics(font).horizontalAdvance(
                                tabs.tabText(index)) + 30
                    assert not regions["title"].intersects(regions["status"])

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
                # Catch unmanaged, visible children missing from the Qt layout:
                # they are not visited by assert_layout and can paint over Thai text.
                header_layout = ws.editor_header.layout()
                for button in ws.editor_header.findChildren(
                    QToolButton, options=Qt.FindDirectChildrenOnly
                ):
                    if button.isVisible():
                        assert header_layout.indexOf(button) >= 0, (
                            button.objectName(), button.text(), button.geometry()
                        )
                assert_layout(ws.novel_header)
                assert_layout(win.navigation)
                assert win.navigation.width() == (60 if win.navigation.collapsed else 196)
                assert all(button.toolButtonStyle() == (Qt.ToolButtonIconOnly if win.navigation.collapsed else Qt.ToolButtonTextBesideIcon)
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
                assert 'ยังไม่มี Export ที่ยืนยัน' in ws.novel_header.progress.text()
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
                if key != "settings":
                    assert_layout(win.utility_page)
                    assert_layout(win.utility_stack.currentWidget())
            if key == "settings":
                page = win.utility_stack.currentWidget()
                sidebar = page.findChild(QFrame, "preferencesSidebar")
                categories = page.findChild(QListWidget, "preferencesCategory")
                QTest.qWait(30)
                assert_layout(page)
                profiles = win.profiles
                assert sidebar is not None and sidebar.parentWidget() is win.utility_stack.currentWidget()
                assert categories is not None and categories.count() == 7
                assert categories.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
                # Populate a temporary, in-memory overflow so this matrix exercises
                # the real QListWidget scrollbar without changing repository data.
                for index in range(18):
                    QListWidgetItem(f"ทดสอบนิยาย {index + 1}", profiles)
                assert profiles.dragEnabled() and profiles.acceptDrops()
                profile_panel = profiles.parentWidget()
                profile_buttons = profile_panel.findChildren(QPushButton)
                assert len(profile_buttons) == 4
                for appearance in ("Light", "Dark"):
                    win.settings.appearance=appearance; win.apply_theme()
                    for dimensions in ((900,600),(1280,720),(1366,768),(1920,1080)):
                        win.resize(*dimensions); app.processEvents(); QTest.qWait(30)
                        page = win.utility_stack.currentWidget()
                        QTest.qWait(30)
                        assert_layout(page)
                        sidebar_rect = sidebar.geometry()
                        category_rect = categories.geometry()
                        assert sidebar_rect.top() >= 0 and sidebar_rect.bottom() < page.height()
                        assert categories.verticalScrollBar().maximum() == 0
                        last_category = categories.visualItemRect(categories.item(6))
                        assert last_category.bottom() < categories.viewport().height(), (
                            appearance, dimensions, last_category, categories.viewport().size()
                        )
                        assert profiles.minimumHeight() == 0
                        assert profiles.verticalScrollBar().maximum() > 0, (
                            appearance, dimensions, profiles.size(), profiles.count()
                        )
                        buttons_before = [button.mapTo(sidebar, button.rect().topLeft())
                                          for button in profile_buttons]
                        profiles.verticalScrollBar().setValue(profiles.verticalScrollBar().maximum())
                        app.processEvents()
                        assert categories.geometry() == category_rect
                        assert [button.mapTo(sidebar, button.rect().topLeft())
                                for button in profile_buttons] == buttons_before
                        assert profiles.verticalScrollBar().value() == profiles.verticalScrollBar().maximum()
                        profile_scroll = profiles.verticalScrollBar()
                        profile_scroll.setValue(0)
                        position = QPointF(profiles.viewport().rect().center())
                        wheel = QWheelEvent(position, QPointF(profiles.viewport().mapToGlobal(
                            position.toPoint())), QPoint(), QPoint(0, -120),
                            Qt.NoButton, Qt.NoModifier, Qt.ScrollUpdate, False)
                        QApplication.sendEvent(profiles.viewport(), wheel)
                        assert profile_scroll.value() > 0
                        assert categories.geometry() == category_rect
                        assert [button.mapTo(sidebar, button.rect().topLeft())
                                for button in profile_buttons] == buttons_before
                        profile_bottom = profiles.mapTo(sidebar, profiles.rect().bottomLeft()).y()
                        first_button_y = min(buttons_before, key=lambda point: point.y()).y()
                        assert profile_bottom < first_button_y, (
                            appearance, dimensions, profile_bottom, first_button_y
                        )
                        profiles.verticalScrollBar().setValue(0)
                        assert [categories.item(i).text() for i in range(categories.count())] == [
                            "ข้อมูลนิยาย", "ไฟล์และโฟลเดอร์", "ขั้นตอนการแปล", "แท็บทำงาน",
                            "ส่งออก TXT", "ทั่วไป", "อัปเดตโปรแกรม"
                        ]
                        for category in ("General", "Novel", "Workflow", "Workflow Files", "Working Tabs", "TXT Export", "Program Updates"):
                            page.select_category(category)
                            app.processEvents(); QTest.qWait(30)
                            if category == "Workflow Files":
                                last_attachment = win.files.visualItemRect(win.files.item(5))
                                assert last_attachment.bottom() < win.files.viewport().height(), (
                                    last_attachment, win.files.viewport().size(), win.files.size(),
                                    win.files.parentWidget().size(), dimensions,
                                )
                            for child in page.findChildren(QWidget):
                                if child.isVisible() and child.layout(): assert_layout(child)

            if os.environ.get("PALANTIR_UI_CAPTURE"):
                Path("build").mkdir(exist_ok=True)
                win.grab().save(f"build/ui-{key}.png")
        win.navigate('workspace')
        p = win.profile
        p.main_folder = str(root)
        p.polish_history_step_id = p.workflow.steps[1].id
        payload = repo.profile_dir(p.id) / 'history.txt'; payload.write_bytes(b'lossless\t\n\n')
        p.workflow.steps[1].files = [StepFile(path='history.txt', enabled=False)]
        win.polish_history.create(p, p.workflow.steps[1], '100000-100123')
        win.open_polish_history()
        deadline = time.monotonic() + 15
        while win.history_busy() and time.monotonic() < deadline:
            app.processEvents(); time.sleep(.01)
        assert not win.history_busy()
        history = win.utility_stack.currentWidget()
        for appearance in ('Light', 'Dark'):
            win.settings.appearance = appearance; win.apply_theme()
            for dimensions in ((900,600), (1280,720), (1440,860), (1920,1080)):
                win.resize(*dimensions); app.processEvents(); QTest.qWait(30)
                assert_layout(win.utility_page)
                assert_layout(history)
                for child in history.cards.findChildren(QWidget):
                    if child.isVisible() and child.layout(): assert_layout(child)
                if os.environ.get('PALANTIR_UI_CAPTURE'):
                    win.grab().save(f'build/history-{appearance}-{dimensions[0]}.png')
            win.showMaximized(); app.processEvents(); QTest.qWait(50)
            assert_layout(win.utility_page)
            assert_layout(history)
            for child in history.cards.findChildren(QWidget):
                if child.isVisible() and child.layout(): assert_layout(child)
            win.showNormal(); app.processEvents()
        win.utility_back.click()
        assert win.workspace_stack.currentWidget() is ws
        win.close(); app.processEvents()
    print('DPI geometry passed',os.environ.get('QT_SCALE_FACTOR','1.0'))
    return 0

if __name__=='__main__': raise SystemExit(main())
