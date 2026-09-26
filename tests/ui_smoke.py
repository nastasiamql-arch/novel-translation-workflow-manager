"""Run a real offscreen Qt event loop and exercise key workspace interactions."""
import os
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton
import shiboken6

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
        shiboken6.delete(window)
        shiboken6.delete(app)
        return result


if __name__ == "__main__":
    raise SystemExit(main())
