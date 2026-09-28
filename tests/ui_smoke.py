"""Run a real offscreen Qt event loop and exercise key workspace interactions."""
import os
import tempfile
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from novel_workflow.models import NovelGroup, StepFile, Workflow
from novel_workflow.services import ProfileService
from novel_workflow.storage import ProjectRepository
from novel_workflow.ui import MainWindow


def main() -> int:
    app = QApplication(["NovelWorkflowUISmoke"])
    app.setQuitOnLastWindowClosed(False)
    with tempfile.TemporaryDirectory(prefix="novelworkflow-ui-") as temp_dir:
        repo = ProjectRepository(temp_dir)
        profile = ProfileService(repo).create("ชื่อเรื่องยาวสำหรับตรวจการแสดงผล", Workflow.defaults())
        source = repo.profile_dir(profile.id) / "prompts" / "find_terms.txt"
        source.write_text("Find terms", encoding="utf-8")
        profile.workflow.steps[0].files.append(
            StepFile(label="Find Terms Prompt", path="prompts/find_terms.txt", file_type="prompt", order=0)
        )
        repo.save_profile(profile)
        repo.save_groups([NovelGroup(name="กลุ่มหลัก", profile_ids=[profile.id])])

        window = MainWindow(repo)
        window.show()

        smoke_passed = False

        def exercise_workspace():
            nonlocal smoke_passed
            try:
                assert set(window.nav_buttons) == {"home", "novels", "groups", "files", "progress", "settings"}
                assert window.novel.text() == profile.name
                assert window.steps.currentRow() == 0

                window.open_novel_workspace(profile.id)
                novel_tab_key = f"novel:{profile.id}"
                novel_tab_count = window.main_tabs.count()
                window.open_novel_workspace(profile.id)
                assert window.main_tabs.count() == novel_tab_count
                novel_tab_index = window.main_tabs.indexOf(window.pages[novel_tab_key])
                window.close_workspace_tab(novel_tab_index)
                assert novel_tab_key not in window.pages
                window.open_destination("workflow")

                window.open_destination("groups")
                app.processEvents()
                assert window.main_tabs.currentWidget() is window.groups_page
                tab_count = window.main_tabs.count()
                window.open_destination("groups")
                assert window.main_tabs.count() == tab_count

                window.translation_dashboard()
                app.processEvents()
                assert window.main_tabs.currentWidget() is window.dashboard_page
                assert not window.dashboard_page.isWindow()
                assert window.dashboard_page.tabs.currentIndex() == 1
                assert window.dashboard_page.goal_tabs.currentIndex() == 0
                assert any(
                    button.text() == "บันทึกเป้ากลุ่ม"
                    for button in window.dashboard_page.findChildren(QPushButton)
                )
                window.main_tabs.setCurrentWidget(window.workspace_page)
                app.processEvents()

                second = window.steps.visualItemRect(window.steps.item(1))
                QTest.mouseClick(window.steps.viewport(), Qt.LeftButton, pos=second.center())
                app.processEvents()
                assert window.steps.currentRow() == 1

                first = window.steps.visualItemRect(window.steps.item(0))
                QTest.mouseClick(window.steps.viewport(), Qt.LeftButton, pos=first.center())
                app.processEvents()
                row = window.files.item(0)
                assert row is not None and row.checkState() == Qt.Checked
                row.setCheckState(Qt.Unchecked)
                app.processEvents()
                assert not window.profile.workflow.steps[0].files[0].enabled
                row.setCheckState(Qt.Checked)
                app.processEvents()

                copy_button = next(button for button in window.findChildren(QPushButton) if button.text() == "COPY STEP")
                QTest.mouseClick(copy_button, Qt.LeftButton)
                app.processEvents()
                urls = app.clipboard().mimeData().urls()
                assert [Path(url.toLocalFile()) for url in urls] == [source.resolve()]
                assert window.steps.currentRow() == 1

                window.open_destination("files")
                app.processEvents()
                assert window.main_tabs.currentWidget() is window.pages[f"files:{profile.id}"]
                state = window._files_states[f"files:{profile.id}"]
                assert state["list"].count() >= 1
                file_row = next(i for i in range(state["list"].count()) if state["list"].item(i).text() == "prompts/find_terms.txt")
                state["list"].setCurrentRow(file_row)
                state["editor"].setPlainText("Find terms updated")
                assert window._files_dirty(state)
                window.save()
                assert source.read_text(encoding="utf-8") == "Find terms updated"
                window.open_destination("settings")
                assert window.main_tabs.currentWidget() is window.pages["settings"]
                window.set_profile_by_id(profile.id)
                window.open_destination("workflow")
                window.steps.setCurrentRow(0)
                window.preview()
                assert window.main_tabs.currentWidget() is window.pages[f"preview:{profile.id}:{profile.workflow.steps[0].id}"]
                preview_editor = window.pages[f"preview:{profile.id}:{profile.workflow.steps[0].id}"].findChild(type(state["editor"]))
                assert preview_editor is not None and preview_editor.isReadOnly()
                window.launcher_dialog()
                assert window.main_tabs.currentWidget() is window.pages[f"launcher:{profile.id}"]

                window.settings.appearance = "Light"
                window.apply_theme()
                app.processEvents()
                assert "#F4F5F7" in app.styleSheet()
                window.settings.appearance = "Dark"
                window.apply_theme()

                window.resize(900, 600)
                app.processEvents()
                assert window.width() == 900
                window.close()
                app.exit(0)
                smoke_passed = True
                print("UI smoke passed: select step, enable file, copy to clipboard, cycle, theme, resize")
            except Exception as exc:
                print(f"UI smoke failed: {type(exc).__name__}: {exc}")
                window.close()
                app.exit(1)

        QTimer.singleShot(100, exercise_workspace)
        event_result = app.exec()
        print(f"Qt event loop exit status: {event_result}")
        result = 0 if smoke_passed else (event_result or 1)
    # The Qt offscreen plugin on hosted Windows runners leaves Python with exit code 1
    # during interpreter teardown even after QApplication.exec() returns 0.
    # The temporary project has already been cleaned up by the context manager above.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(result)


if __name__ == "__main__":
    main()
