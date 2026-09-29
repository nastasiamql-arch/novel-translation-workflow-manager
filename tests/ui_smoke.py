"""Run an offscreen Qt event loop and exercise the tabbed novel workspace."""
import os
import sys
import tempfile
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("NOVELWORKFLOW_DISABLE_WEBENGINE", "1")

from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QToolBar

from novel_workflow.models import LaunchTarget, StepFile, Workflow
from novel_workflow.services import ProfileService
from novel_workflow.storage import ProjectRepository
from novel_workflow.workspace_window import MainWindow


def main() -> int:
    app = QApplication(["NovelWorkflowUISmoke"])
    app.setQuitOnLastWindowClosed(False)

    with tempfile.TemporaryDirectory(prefix="novelworkflow-ui-") as temp_dir:
        root = Path(temp_dir)
        repo = ProjectRepository(root / "data")

        novel_folder = root / "novel-a"
        novel_folder.mkdir()
        chapter = novel_folder / "126.txt"
        context = novel_folder / "Context.md"
        chapter.write_text("ตอนที่ 126\nเนื้อหาทดสอบ", encoding="utf-8")
        context.write_text("บทที่ 126\nContext", encoding="utf-8")

        profile = ProfileService(repo).create("เรื่อง A", Workflow.defaults())
        profile.main_folder = str(novel_folder)
        profile.workflow.steps[0].files.append(
            StepFile(
                label="Chapter 126",
                reference_type="external_file",
                path=str(chapter),
                file_type="chapter",
                order=0,
            )
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
                assert window.profile_cards.count() == 2
                assert window.profile.id == profile.id
                assert window.main_pages.currentWidget() is window.workspace_stack
                workspace = window.workspaces[profile.id]
                assert workspace.root_path == novel_folder.resolve()
                assert workspace.steps.count() == 3
                assert [workspace.steps.item(i).text() for i in range(3)] == [
                    "1. หาศัพท์", "2. แปล", "3. ตรวจคำแปล",
                ]

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
                assert workspace.editor.tabs.count() == 1

                editor = workspace.editor.tabs.currentWidget()
                assert editor.objectName() == "codeEditor"
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

                assert editor.find("126")
                QTest.keyClick(editor, Qt.Key_H, Qt.ControlModifier)
                app.processEvents()
                assert workspace.editor.find_panel.isVisible()
                assert workspace.editor.find_input.text() == "126"
                assert workspace.editor.find_count.text() == "1/1"
                editor.appendPlainText("\nแก้ไขอีกครั้ง")
                workspace.editor.find_input.setText("แก้ไข")
                assert workspace.editor.find_count.text() == "1/2"
                workspace.editor._find_next()
                assert workspace.editor.find_count.text() == "2/2"
                workspace.editor._find_next(backward=True)
                assert workspace.editor.find_count.text() == "1/2"
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

                window.copy_step()
                app.processEvents()
                urls = app.clipboard().mimeData().urls()
                assert [Path(url.toLocalFile()) for url in urls] == [chapter.resolve()]
                assert workspace.steps.currentRow() == 1

                window.show_library()
                window._open_profile_card(window.profile_cards.item(1))
                app.processEvents()
                assert window.profile.id == second.id
                assert window.workspaces[second.id] is not workspace

                window.show_library()
                window._open_profile_card(window.profile_cards.item(0))
                app.processEvents()
                assert window.profile.id == profile.id
                assert window.workspaces[profile.id] is workspace

                window.resize(1100, 700)
                app.processEvents()
                assert window.width() == 1100

                smoke_passed = True
                app.exit(0)
                print("UI smoke passed: Novel Library, workflow sidebar, Auto Save, Find, COPY STEP")
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
