import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from novel_workflow.models import StepFile, Workflow
from novel_workflow.services import ProfileService
from novel_workflow.storage import ProjectRepository
from novel_workflow.theme import application_stylesheet
from novel_workflow.ui import MainWindow


def _application():
    return QApplication.instance() or QApplication(["NovelWorkflowTests"])


def test_workspace_click_copy_and_step_cycle(tmp_path):
    app = _application()
    repo = ProjectRepository(tmp_path)
    profile = ProfileService(repo).create("ชื่อเรื่องยาวสำหรับตรวจการแสดงผล", Workflow.defaults())
    source = repo.profile_dir(profile.id) / "prompts" / "find_terms.txt"
    source.write_text("Find terms", encoding="utf-8")
    profile.workflow.steps[0].files.append(
        StepFile(label="Find Terms Prompt", path="prompts/find_terms.txt", file_type="prompt", order=0)
    )
    repo.save_profile(profile)

    window = MainWindow(repo)
    window.show()
    QTest.qWait(80)
    assert window.novel.text() == profile.name
    assert window.minimumWidth() <= 900
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
    assert [url.toLocalFile() for url in urls] == [str(source.resolve())]
    assert window.steps.currentRow() == 1

    window.resize(900, 600)
    app.processEvents()
    assert window.width() == 900
    window.close()


def test_theme_appearance_modes_are_real_stylesheets(tmp_path):
    app = _application()
    dark = application_stylesheet("Dark")
    light = application_stylesheet("Light")
    assert "#0F1115" in dark and "#6C7CFF" in dark
    assert "#F4F5F7" in light and "#5265E8" in light
    assert "qlineargradient" not in dark.lower()
    assert "glow" not in dark.lower()

    window = MainWindow(ProjectRepository(tmp_path))
    window.settings.appearance = "Light"
    window.apply_theme()
    app.processEvents()
    assert "#F4F5F7" in app.styleSheet()
    window.settings.appearance = "Dark"
    window.apply_theme()
    window.close()
