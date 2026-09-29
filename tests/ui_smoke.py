"""Run a real offscreen Qt event loop and exercise key workspace interactions."""
import os
import tempfile
import sys
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QToolBar

from novel_workflow.models import StepFile, Workflow
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

        window = MainWindow(repo)
        window.show()

        smoke_passed = False

        def exercise_workspace():
            nonlocal smoke_passed
            try:
                assert window.novel.text() == profile.name
                assert window.steps.currentRow() == 0
                toolbar = window.findChild(QToolBar, "mainToolbar")
                logo = window.findChild(QLabel, "toolbarLogo")
                assert toolbar is not None, "main toolbar is missing"
                assert logo is not None and logo.pixmap() is not None and not logo.pixmap().isNull(), "toolbar logo is missing"
                assert window.findChild(QLabel, "brandTitle") is None, "toolbar still contains the program name"
                assert {action.text() for action in toolbar.actions()} >= {
                    "เปิดนิยาย", "กลุ่มนิยาย", "นำเข้าข้อมูลเดิม", "ความคืบหน้า", "ตั้งค่า"
                }, "toolbar actions changed unexpectedly"

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

                window.settings.appearance = "Light"
                window.apply_theme()
                app.processEvents()
                assert "#F4F5F7" in app.styleSheet()
                window.settings.appearance = "Dark"
                window.apply_theme()

                browse = Path(temp_dir) / "selected-folder"
                browse.mkdir()
                ProfileService.remember_browse_directory(repo, window.profile, browse / "context.md")
                actual_browse = window.profile_browse_directory()
                assert actual_browse == browse.resolve(), (
                    f"profile browse directory mismatch: stored={window.profile.last_browse_directory!r}, "
                    f"expected={str(browse.resolve())!r}, actual={str(actual_browse)!r}"
                )

                second = ProfileService(repo).create("Second novel")
                window.refresh_profiles(profile.id)
                window.move_profile(1)
                expected_order = [second.id, profile.id]
                assert [item.id for item in repo.list_profiles()] == expected_order, "profile move did not reorder the list"
                assert [item.id for item in ProjectRepository(temp_dir).list_profiles()] == expected_order, "profile move did not persist"

                window.resize(900, 600)
                app.processEvents()
                assert window.width() == 900
                window.close()
                app.exit(0)
                smoke_passed = True
                print("UI smoke passed: toolbar branding, profile order persistence, browse memory, workspace interactions, theme, resize")
            except Exception as exc:
                traceback.print_exc()
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
