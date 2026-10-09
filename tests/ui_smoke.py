"""Run an offscreen Qt event loop and exercise the tabbed novel workspace."""
import os
import sys
import tempfile
import traceback
from datetime import date
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("NOVELWORKFLOW_DISABLE_WEBENGINE", "1")

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor, QPalette, QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractItemView, QApplication, QPushButton, QToolBar, QLabel

from novel_workflow.models import LaunchTarget, StepFile, Workflow, WorkflowStep
from novel_workflow.services import ProfileService
from novel_workflow.storage import ProjectRepository
from novel_workflow.theme import _DARK, _LIGHT
from novel_workflow.workspace_window import ElidingStatusLabel, MainWindow


def _contrast_ratio(foreground, background):
    def luminance(color):
        channels = [getattr(color, channel)() / 255 for channel in ("red", "green", "blue")]
        linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
                  for value in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    first, second = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (first + 0.05) / (second + 0.05)


def main() -> int:
    app = QApplication(["NovelWorkflowUISmoke"])
    app.setQuitOnLastWindowClosed(False)

    with tempfile.TemporaryDirectory(prefix="novelworkflow-ui-") as temp_dir:
        root = Path(temp_dir)
        repo = ProjectRepository(root / "data")
        settings = repo.load_settings()
        settings.last_update_check_date = date.today().isoformat()
        repo.save_settings(settings)

        novel_folder = root / "novel-a"
        novel_folder.mkdir()
        chapter = novel_folder / "126.txt"
        context = novel_folder / "Context.md"
        review = novel_folder / "review.txt"
        chapter.write_text("ตอนที่ 156\nเนื้อหาทดสอบ", encoding="utf-8")
        context.write_text("บทที่ 156\nContext", encoding="utf-8")
        review.write_text("ตรวจคำแปล", encoding="utf-8")

        profile = ProfileService(repo).create("เรื่อง A", Workflow.defaults())
        profile.main_folder = str(novel_folder)
        profile.context_path = str(context)
        profile.translation_goal_baseline = 156
        profile.translation_goal_target = 10
        profile.workflow.steps[0].files.append(
            StepFile(
                label="Chapter 156",
                reference_type="external_file",
                path=str(chapter),
                file_type="chapter",
                order=0,
            )
        )
        profile.workflow.steps[1].files.append(
            StepFile(
                label="Review",
                reference_type="external_file",
                path=str(review),
                file_type="chapter",
                order=0,
            )
        )
        legacy_vocabulary_file = StepFile(
            label="Find Terms",
            reference_type="external_file",
            path=str(context),
            file_type="glossary",
            order=0,
        )
        profile.workflow.steps.insert(
            0, WorkflowStep(name="หาศัพท์", files=[legacy_vocabulary_file])
        )
        profile.launch_targets.append(
            LaunchTarget(label="Chapter", kind="file", target=str(chapter), order=0)
        )
        repo.save_profile(profile)
        second = ProfileService(repo).create("เรื่อง B", Workflow.defaults())

        window = MainWindow(repo)
        window.show()
        smoke_passed = False

        def exercise_workspace():
            nonlocal smoke_passed
            try:
                toolbar = window.findChild(QToolBar, "mainToolbar")
                assert toolbar is not None
                assert window.navigation.buttons["workspace"].isChecked()
                assert window.profile_cards.count() == 2
                assert window.profile.id == profile.id
                assert window.main_pages.currentWidget() is window.workspace_stack
                workspace = window.workspaces[profile.id]
                for appearance, tokens in (("Dark", _DARK), ("Light", _LIGHT)):
                    window.settings.appearance = appearance
                    window.apply_theme()
                    app.processEvents()
                    disabled_text = app.palette().color(
                        QPalette.Disabled, QPalette.ButtonText
                    )
                    assert _contrast_ratio(
                        disabled_text, QColor(tokens["sidebar"])
                    ) >= 4.5, (
                        appearance, disabled_text.name(), tokens["sidebar"]
                    )
                    assert "QFrame#editorHeader QToolButton:disabled" in app.styleSheet()
                    assert "QTabWidget#editorTabs QTabBar::tab:disabled" in (
                        workspace.editor.tabs.styleSheet()
                    )
                window.settings.appearance = "Dark"
                window.apply_theme()
                app.processEvents()
                assert window.library_status_tabs.count() == 4
                assert [
                    workspace.pause_profile_button.text(),
                    workspace.caught_up_profile_button.text(),
                ] == ["พักแปล", "ชนต้นฉบับแล้ว"]

                def saved_profile():
                    return next(item for item in repo.list_profiles() if item.id == profile.id)

                workspace.pause_profile_button.click()
                app.processEvents()
                assert saved_profile().status == "paused"
                assert saved_profile().context_path == str(context)
                assert saved_profile().chapter_state.current_chapter == 156
                assert window.library_status_tabs.tabText(1).endswith("(1)")
                window.library_status_tabs.setCurrentIndex(1)
                paused_card = next(
                    window.profile_cards.item(i)
                    for i in range(window.profile_cards.count())
                    if window.profile_cards.item(i).data(Qt.UserRole) == profile.id
                )
                assert not paused_card.isHidden()
                window.profile_cards.itemClicked.emit(paused_card)
                app.processEvents()
                assert window.profile is not None and window.profile.id == profile.id
                assert window.main_pages.currentWidget() is window.workspace_stack

                window.workspaces[profile.id].resume_profile_button.click()
                app.processEvents()
                assert saved_profile().status == "translating"
                window.workspaces[profile.id].caught_up_profile_button.click()
                app.processEvents()
                assert saved_profile().status == "caught_up"
                assert window.library_status_tabs.tabText(2).endswith("(1)")
                window.library_status_tabs.setCurrentIndex(2)
                caught_up_card = next(
                    window.profile_cards.item(i)
                    for i in range(window.profile_cards.count())
                    if window.profile_cards.item(i).data(Qt.UserRole) == profile.id
                )
                assert not caught_up_card.isHidden()
                window.workspaces[profile.id].resume_profile_button.click()
                app.processEvents()
                assert saved_profile().status == "translating"
                workspace.checking_web_profile_button.click()
                app.processEvents()
                assert saved_profile().status == "checking_web"
                assert window.library_status_tabs.tabText(3).startswith("กำลังเช็กกับเว็บ (1)")
                window.library_status_tabs.setCurrentIndex(3)
                checking_card = next(
                    window.profile_cards.item(i)
                    for i in range(window.profile_cards.count())
                    if window.profile_cards.item(i).data(Qt.UserRole) == profile.id
                )
                assert not checking_card.isHidden()
                assert "กำลังเช็กกับเว็บ" in checking_card.text()
                workspace.resume_profile_button.click()
                app.processEvents()
                assert saved_profile().status == "translating"
                window.library_status_tabs.setCurrentIndex(0)
                app.processEvents()
                workspace = window.workspaces[profile.id]
                assert window.settings.appearance == "Dark"
                assert workspace.root_path == novel_folder.resolve()
                assert workspace.steps.count() == 2
                assert [workspace.steps.item(i).text() for i in range(2)] == ["", ""]
                assert all(workspace.steps.itemWidget(workspace.steps.item(i)) for i in range(2))
                assert workspace.steps.objectName() == "workflowSteps"
                assert [workspace.steps.itemWidget(workspace.steps.item(i)).text() for i in range(2)] == [
                    "แปล", "ตรวจคำแปล",
                ]
                assert [
                    workspace.steps.itemWidget(workspace.steps.item(i)).accessibleName()
                    for i in range(2)
                ] == ["แปล", "ตรวจคำแปล"]
                for index in range(workspace.steps.count()):
                    item = workspace.steps.item(index)
                    button = workspace.steps.itemWidget(item)
                    assert workspace.steps.visualItemRect(item).contains(
                        button.geometry()
                    ), (index, button.geometry(), workspace.steps.visualItemRect(item))
                assert [workspace.steps.itemWidget(workspace.steps.item(i)).property("workflowActive") for i in range(2)] == [True, False]
                assert workspace.vocabulary_button.text() == "หาศัพท์"
                assert not hasattr(workspace, "vocabulary_polish_button")
                assert not hasattr(workspace, "vocabulary_panel")
                assert workspace.workspace_splitter.count() == 2
                assert window.profile.workflow.steps[0].name == "แปล"
                assert window.profile.vocabulary_step.files[0].id == legacy_vocabulary_file.id
                saved_profile = repo.list_profiles()[0]
                assert [step.name for step in saved_profile.workflow.steps] == ["แปล", "ตรวจคำแปล"]
                workspace.vocabulary_button.click()
                app.processEvents()
                assert workspace.vocabulary_mode
                assert window.step().name == "หาศัพท์"
                assert workspace.vocabulary_button.text() == "หาศัพท์"
                assert workspace.vocabulary_button.property("workflowActive")
                assert workspace.files.item(0).text() == "Find Terms"
                assert [Path(url.toLocalFile()).resolve() for url in QApplication.clipboard().mimeData().urls()] == [context.resolve()]
                workspace.vocabulary_button.click()
                app.processEvents()
                assert workspace.vocabulary_mode
                assert [Path(url.toLocalFile()).resolve() for url in QApplication.clipboard().mimeData().urls()] == [context.resolve()]
                translation_button = workspace.steps.itemWidget(workspace.steps.item(0))
                translation_geometry = translation_button.geometry()
                QTest.mouseMove(translation_button, translation_button.rect().center())
                app.processEvents()
                assert translation_button.geometry() == translation_geometry
                translation_button.click()
                app.processEvents()
                assert translation_button.geometry() == translation_geometry
                assert not workspace.vocabulary_mode
                assert translation_button.text() == "แปล"
                assert translation_button.property("workflowActive")
                review_button = workspace.steps.itemWidget(workspace.steps.item(1))
                assert review_button.text() == "ตรวจคำแปล"
                assert workspace.steps.currentRow() == 0
                assert [Path(url.toLocalFile()).resolve() for url in QApplication.clipboard().mimeData().urls()] == [chapter.resolve()]
                review_button.click()
                app.processEvents()
                assert workspace.steps.currentRow() == 1
                assert review_button.text() == "ตรวจคำแปล"
                assert review_button.property("workflowActive")
                assert [Path(url.toLocalFile()).resolve() for url in QApplication.clipboard().mimeData().urls()] == [review.resolve()]
                translation_button.click()
                app.processEvents()

                assert workspace.content_stack.currentWidget() is workspace.workflow_page
                assert not hasattr(workspace, "browser")
                assert workspace.content_stack.currentWidget() is workspace.workflow_page
                workspace.file_search.setText("Chapter")
                assert not workspace.files.item(0).isHidden()
                workspace.file_search.setText("not found")
                assert workspace.files.item(0).isHidden()
                workspace.file_search.clear()
                workspace.toggle_sidebar()
                assert not window.settings.sidebar_visible
                workspace.toggle_sidebar()
                assert window.settings.sidebar_visible

                assert not any(action.text() == "คัดลอกขั้นตอน" for action in toolbar.actions())
                assert workspace.copy_step_button.text() == "COPY STEP"
                assert workspace.copy_step_button.isEnabled()

                workspace.editor.open_file(chapter)
                app.processEvents()
                assert workspace.editor.tabs.count() == 2
                assert workspace.editor.tabs.tabText(workspace.editor.tabs.count()-1) == "TXT Export"
                assert workspace.editor.export_tab is workspace.editor.tabs.widget(workspace.editor.tabs.count()-1)
                export_tab = workspace.editor.export_tab
                editor = workspace.editor.tabs.currentWidget()
                assert not hasattr(export_tab, "autosave_timer")
                export_tab.editor.setPlainText("ส่งออกไทย 卡")
                export_tab.filename.setText("smoke.txt")
                export_tab.directory.setText(str(root))
                export_tab.submit_button.click()
                assert (root / "smoke1.txt").read_text(encoding="utf-8") == "ส่งออกไทย 卡"
                assert export_tab.current.value() == 2
                assert len(export_tab.editor.font().families()) == 1
                workspace.editor.close_tab(workspace.editor.tabs.indexOf(export_tab))
                assert workspace.editor.tabs.count() == 2
                workspace.editor.tabs.setCurrentWidget(export_tab)
                app.processEvents()
                assert "TXT Export" in workspace.editor.current_status_text()
                workspace.editor.tabs.setCurrentWidget(editor)
                app.processEvents()

                assert editor.objectName() == "codeEditor"
                assert editor.colors["background"] == _DARK["surface"]
                assert editor.font().pointSizeF() >= 10.5
                window.adjust_editor_font_size(1)
                assert round(editor.font().pointSizeF(), 2) == 12.0, editor.font().pointSizeF()
                window.set_editor_font_size(11.0)
                assert workspace.file_tree.objectName() == "fileTree"
                editor.appendPlainText("\nแก้ไขจาก Auto Save")
                app.processEvents()
                assert workspace.editor.dirty_count() == 1
                QTest.qWait(1200)
                app.processEvents()
                assert workspace.editor.dirty_count() == 0
                assert "แก้ไขจาก Auto Save" in chapter.read_text(encoding="utf-8")
                assert "บันทึกอัตโนมัติแล้ว" in workspace.editor.status.text()
                assert "อักขระ" in window.editor_status.text()
                selection_cursor = editor.textCursor()
                selection_cursor.setPosition(0)
                selection_cursor.setPosition(6, QTextCursor.KeepAnchor)
                editor.setTextCursor(selection_cursor)
                app.processEvents()
                assert "เลือก 6 อักขระ" in workspace.editor.current_status_text()
                selection_cursor.setPosition(6)
                editor.setTextCursor(selection_cursor)
                app.processEvents()
                assert window.editor_status.minimumWidth() == 0
                assert "UTF-8" in window.editor_status.toolTip()
                compact_status = ElidingStatusLabel()
                compact_status.setFixedWidth(70)
                compact_status.setFullText("บันทึกแล้ว · 922 คำ · 29,580 อักขระ · Ln 264, Col 8 · UTF-8 MD")
                assert compact_status.text().endswith("…")
                assert compact_status.toolTip().endswith("UTF-8 MD")

                assert editor.find("156")
                QTest.keyClick(editor, Qt.Key_H, Qt.ControlModifier)
                app.processEvents()
                assert workspace.editor.find_panel.isVisible()
                assert workspace.editor.find_input.text() == "156"
                assert workspace.editor.find_count.text() == "1/1"
                editor.appendPlainText("\nแก้ไขอีกครั้ง")
                workspace.editor.find_input.setText("แก้ไข")
                assert workspace.editor.find_count.text() == "1/2"
                workspace.editor._find_next()
                assert workspace.editor.find_count.text() == "2/2"
                workspace.editor._find_next(backward=True)
                assert workspace.editor.find_count.text() == "1/2"

                cursor = editor.textCursor()
                cursor.movePosition(QTextCursor.Start)
                editor.setTextCursor(cursor)
                clicked_position = editor.textCursor().position()
                workspace.editor._update_find_matches()
                assert editor.textCursor().position() == clicked_position
                assert workspace.editor.find_count.text() == "0/2"
                workspace.editor._find_next()
                assert workspace.editor.find_count.text() == "1/2"
                workspace.editor.replace_input.setText("EDITED")
                workspace.editor.replace_current_button.click()
                assert "EDITED" in editor.toPlainText()
                workspace.editor.replace_input.setText("REPLACED")
                workspace.editor.replace_all_button.click()
                assert "แก้ไข" not in editor.toPlainText()
                assert workspace.editor.find_count.text() == "0/0"

                context_editor = workspace.editor.open_file(context)
                assert context_editor is not None
                context_editor.setPlainText("บทที่ 157-159\nContext updated")
                assert workspace.editor.save_current()
                app.processEvents()
                assert "วันนี้ +3 บท" in window.progress_status.text()
                assert "เป้าหมาย 3/10 บท · 30%" == window.goal_status.text()
                assert window.goal_status_bar.value() == 30
                context.write_text("บทที่ 160-161\nExternal Context update", encoding="utf-8")
                QTest.qWait(450)
                app.processEvents()
                assert "วันนี้ +5 บท" in window.progress_status.text()
                assert "เป้าหมาย 5/10 บท · 50%" == window.goal_status.text()
                workspace.editor.tabs.setCurrentWidget(editor)
                app.processEvents()
                QTest.keyClick(workspace.editor.find_input, Qt.Key_Escape)
                workspace.editor.close_find()
                assert not workspace.editor.find_panel.isVisible()

                original_block_format = editor.document().begin().blockFormat()
                pasted = editor.textCursor()
                pasted.insertText("\nข้อความที่วางจากภาษาญี่ปุ่น\n次の段落")
                last_format = editor.document().lastBlock().blockFormat()
                assert original_block_format.bottomMargin() == last_format.bottomMargin()
                assert original_block_format.lineHeight() == last_format.lineHeight()
                workspace.editor.save_current()

                translation_button.click()
                workspace.copy_step_button.click()
                app.processEvents()
                urls = app.clipboard().mimeData().urls()
                assert [Path(url.toLocalFile()) for url in urls] == [chapter.resolve()]
                assert workspace.steps.currentRow() == 1
                assert workspace.steps.itemWidget(workspace.steps.item(1)).text() == "ตรวจคำแปล"

                window.show_library()
                window._open_profile_card(window.profile_cards.item(1))
                app.processEvents()
                assert window.profile.id == second.id
                assert window.workspaces[second.id] is not workspace
                status_for_second = window.editor_status.text()
                window._workspace_editor_status_changed(
                    workspace.editor, "stale  ·  0 คำ  ·  0 อักขระ"
                )
                assert window.editor_status.text() == status_for_second

                window.show_library()
                window._open_profile_card(window.profile_cards.item(0))
                app.processEvents()
                assert window.profile.id == profile.id
                assert set(window.workspaces) == {profile.id}
                workspace = window.workspaces[profile.id]
                export_tab = workspace.editor.export_tab
                assert workspace.novel_header.cover.isVisible()
                assert not workspace.novel_header.cover.pixmap().isNull()

                window.groups_dialog()
                assert window.main_pages.currentWidget() is window.utility_page
                assert window.utility_title.text() == "กลุ่มนิยาย"
                groups_page = window._utility_pages["groups"]
                groups_page.new_name.setText("ทดสอบกลุ่ม")
                groups_page.create_group()
                assert groups_page.selector.currentText() == "ทดสอบกลุ่ม"
                groups_page.members.item(0).setCheckState(Qt.Checked)
                groups_page.store_group()
                window.return_from_utility_page()
                assert window.main_pages.currentWidget() is window.workspace_stack

                window.translation_dashboard()
                assert window.main_pages.currentWidget() is window.utility_page
                assert window._utility_pages["progress"].isVisible()
                dashboard = window._utility_pages["progress"]
                assert dashboard.bulk_goal_button.isEnabled()
                assert dashboard.clear_all_goals_button.text() == "ยกเลิกเป้าหมายทั้งหมด"
                assert dashboard.clear_all_goals_button.isEnabled()
                assert dashboard.bulk_goal_hint.text() == "ตั้งได้ 1 เรื่องที่มีไฟล์ Context"
                dashboard.bulk_goal_target.setValue(12)
                dashboard.bulk_goal_button.click()
                saved_goals = {item.id: item.translation_goal_target for item in repo.list_profiles()}
                assert saved_goals[profile.id] == 12
                assert saved_goals[second.id] is None
                window.return_from_utility_page()

                workspace.vocabulary_button.click()
                assert workspace.vocabulary_mode
                window.settings_dialog()
                assert window.main_pages.currentWidget() is window.utility_page
                assert window._settings_open
                assert window.profiles.dragDropMode() == QAbstractItemView.InternalMove
                assert window.profiles.dragEnabled()
                original_order = [window.profiles.item(i).data(Qt.UserRole) for i in range(window.profiles.count())]
                assert set(original_order) == {profile.id, second.id}
                reordered = list(reversed(original_order))
                window._persist_profile_order(reordered)
                assert [item.id for item in repo.list_profiles()] == reordered
                window._persist_profile_order(original_order)
                assert [item.id for item in repo.list_profiles()] == original_order
                vocabulary_row = len(window.profile.workflow.steps)
                assert window.steps.item(vocabulary_row).text() == "หาศัพท์"
                window.steps.setCurrentRow(vocabulary_row)
                assert window.step().name == "หาศัพท์"
                assert window.files.item(0).text() == "Find Terms"
                window.steps.setCurrentRow(vocabulary_row)
                window.steps.itemDoubleClicked.emit(window.steps.item(vocabulary_row))
                assert not hasattr(window, "_settings_tabs")
                window.steps.setCurrentRow(0)
                assert window.step().name == "แปล"
                window.show_vocabulary_files()
                assert window.step().name == "หาศัพท์"
                target_profile_row = next(
                    index for index in range(window.profiles.count())
                    if window.profiles.item(index).data(Qt.UserRole) == profile.id
                )
                window.profiles.setCurrentRow(target_profile_row)
                assert window.profile.id == profile.id
                workspace = window.workspaces[profile.id]
                working_file = novel_folder / "working.txt"
                working_file.write_text("เปิดเป็นแท็บ", encoding="utf-8")
                window.profile.working_files.append(StepFile(
                    label="working.txt", reference_type="external_file",
                    path=str(working_file),
                ))
                window.save()
                window.refresh_working_files()
                working_row = window.working_files.item(0)
                row_widget = window.working_files.itemWidget(working_row)
                open_button = row_widget.findChild(QPushButton)
                assert row_widget.findChild(QLabel).text() == "working.txt"
                assert open_button.text() == "เปิด"
                open_button.click()
                window.return_from_utility_page()
                assert not window._settings_open
                assert window.main_pages.currentWidget() is window.workspace_stack
                opened_paths = [
                    workspace.editor._path(workspace.editor.tabs.widget(i))
                    for i in range(workspace.editor.tabs.count())
                ]
                assert working_file.resolve() in opened_paths, (
                    f"working file was not opened: expected={working_file.resolve()!s}; "
                    f"active_profile={window.profile.id if window.profile else None}; "
                    f"workspace_profile={workspace.profile_id}; tabs={opened_paths!r}; "
                    f"working_files={[(item.id, item.path) for item in window.profile.working_files]!r}"
                )
                assert workspace.vocabulary_mode
                previous_step_index = workspace.step_index
                for stage_button in workspace.stage_buttons:
                    QTest.mouseMove(stage_button)
                    app.processEvents()
                    assert workspace.step_index == previous_step_index
                    assert workspace.vocabulary_mode
                workspace.vocabulary_button.click()

                window.file_manager()
                assert window.main_pages.currentWidget() is window.utility_page
                assert window.utility_title.text() == "จัดการไฟล์โครงการ"
                window.return_from_utility_page()

                workspace = window.workspaces[profile.id]
                window.preview()
                assert window.main_pages.currentWidget() is window.utility_page
                assert window.utility_title.text().startswith("ตัวอย่าง ·")
                window.return_from_utility_page()

                window.launcher_dialog()
                assert window.main_pages.currentWidget() is window.utility_page
                assert window.utility_title.text() == "ตั้งค่าและจัดการ"
                window.return_from_utility_page()

                selected_profile = window.profile
                saved_folder, saved_targets = selected_profile.main_folder, selected_profile.launch_targets
                selected_profile.main_folder, selected_profile.launch_targets = "", []
                window.launch_profile()
                assert window.main_pages.currentWidget() is window.utility_page
                assert window.utility_title.text() == "ตั้งค่าและจัดการ"
                window.return_from_utility_page()
                selected_profile.main_folder, selected_profile.launch_targets = saved_folder, saved_targets

                window.resize(1100, 700)
                app.processEvents()
                assert window.width() == 1100
                status_bar = window.statusBar()
                assert window.editor_status.geometry().right() <= status_bar.width()
                assert status_bar.height() >= 27
                assert "แปลถึงบท 161" in window.context_status.fullText()
                assert window.editor_status.height() >= 20
                assert workspace.novel_header.isVisible()
                assert "แปลถึงบท" in workspace.novel_header.progress.text()
                assert "วันนี้ส่ง" in workspace.novel_header.progress.text()

                context_editor = workspace.editor.open_file(context)
                context_editor.setPlainText("ข้อความเก่าที่รอ Auto Save")
                export_tab.editor.setPlainText("บทที่ 161\nContext จาก TXT Export")
                export_tab.submit_button.click()
                assert (root / "smoke2.txt").read_text(encoding="utf-8") == "บทที่ 161\nContext จาก TXT Export"
                assert context.read_text(encoding="utf-8") == "บทที่ 161\nContext จาก TXT Export"
                assert context_editor.toPlainText() == "บทที่ 161\nContext จาก TXT Export"
                assert workspace.editor.dirty_count() == 0
                assert not context_editor.autosave_timer.isActive()
                assert window.submit_toast.isVisible()
                assert "smoke2.txt" in window.submit_toast.message.text()
                assert export_tab.current.value() == 3

                smoke_passed = True
                app.exit(0)
                print("UI smoke passed: status, Context watcher, in-app utility pages, Find/Replace, Auto Save, COPY STEP")
            except Exception as exc:
                traceback.print_exc()
                print(f"UI smoke failed: {type(exc).__name__}: {exc}")
                app.exit(1)

        QTimer.singleShot(100, exercise_workspace)
        QTimer.singleShot(20000, lambda: (print("UI smoke timed out after 20 seconds"), app.exit(2)))
        event_result = app.exec()
        print(f"Qt event loop exit status: {event_result}")
        result = 0 if smoke_passed else (event_result or 1)

    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(result)


if __name__ == "__main__":
    main()
