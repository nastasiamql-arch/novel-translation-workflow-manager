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

        profile = ProfileService(repo).create(
            "เรื่อง A",
            Workflow.defaults(),
        )
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
        profile.launch_targets.extend([
            LaunchTarget(
                label="Chapter",
                kind="file",
                target=str(chapter),
                order=0,
            ),
            LaunchTarget(
                label="Example",
                kind="website",
                target="https://example.com",
                order=1,
            ),
        ])
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
                assert window.story_tabs.count() == 2
                assert window.story_tabs.tabText(0) == "เรื่อง A"
                assert window.story_tabs.tabText(1) == "เรื่อง B"

                assert window.profile.id == profile.id
                workspace = window.workspaces[profile.id]
                assert workspace.root_path == novel_folder.resolve()
                assert workspace.steps.count() == 3
                assert [workspace.steps.item(i).text() for i in range(3)] == [
                    "1. หาศัพท์",
                    "2. แปล",
                    "3. ตรวจคำแปล",
                ]

                copy_buttons = [
                    button
                    for button in window.findChildren(QPushButton)
                    if "COPY STEP" in button.text()
                ]
                assert len(copy_buttons) == 1
                assert copy_buttons[0] is window.copy_button

                workspace.editor.open_file(chapter)
                workspace.browser.open_url(
                    "https://example.com", title="Example", new_tab=True
                )
                app.processEvents()

                assert workspace.editor.tabs.count() == 1
                assert workspace.editor.tabs.tabText(0) == "126.txt"
                assert workspace.browser.tabs.count() == 2
                assert workspace.browser.urls()[-1] == "https://example.com"

                editor = workspace.editor.tabs.currentWidget()
                editor.appendPlainText("\nแก้ไขจาก editor ภายใน")
                app.processEvents()
                assert workspace.editor.dirty_count() == 1
                assert workspace.editor.save_current()
                assert "แก้ไขจาก editor ภายใน" in chapter.read_text(encoding="utf-8")

                QTest.mouseClick(window.copy_button, Qt.LeftButton)
                app.processEvents()
                urls = app.clipboard().mimeData().urls()
                assert [Path(url.toLocalFile()) for url in urls] == [chapter.resolve()]
                assert workspace.steps.currentRow() == 1

                window.story_tabs.setCurrentIndex(1)
                app.processEvents()
                assert window.profile.id == second.id
                second_workspace = window.workspaces[second.id]
                assert second_workspace is not workspace
                assert second_workspace.browser.tabs.count() == 1

                window.story_tabs.setCurrentIndex(0)
                app.processEvents()
                assert window.profile.id == profile.id
                assert window.workspaces[profile.id] is workspace
                assert workspace.browser.tabs.count() == 2
                assert workspace.editor.tabs.count() == 1

                window.resize(1100, 700)
                app.processEvents()
                assert window.width() == 1100

                smoke_passed = True
                app.exit(0)
                print(
                    "UI smoke passed: novel tabs, three-step workflow, "
                    "embedded file editor, multi-tab browser, COPY STEP"
                )
            except Exception as exc:
                traceback.print_exc()
                print(f"UI smoke failed: {type(exc).__name__}: {exc}")
                # Do not call close() here: an assertion may have failed while an
                # editor is dirty, and closeEvent intentionally asks the user
                # whether to save. CI has nobody available to answer that dialog.
                app.exit(1)

        QTimer.singleShot(100, exercise_workspace)
        QTimer.singleShot(
            20000,
            lambda: (
                print("UI smoke timed out after 20 seconds"),
                app.exit(2),
            ),
        )
        event_result = app.exec()
        print(f"Qt event loop exit status: {event_result}")
        result = 0 if smoke_passed else (event_result or 1)

    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(result)


if __name__ == "__main__":
    main()
