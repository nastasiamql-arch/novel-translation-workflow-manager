import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from novel_workflow.models import NovelProfile
from novel_workflow.storage import ProjectRepository
from novel_workflow.updater import UpdateInfo
from novel_workflow import workspace_window
from novel_workflow.workspace_window import MainWindow


class Signal:
    def __init__(self):
        self.callback = None

    def connect(self, callback):
        self.callback = callback

    def emit(self, *args):
        self.callback(*args)


class FakeDialog:
    def __init__(self, *_args):
        self.canceled = Signal()

    def setWindowTitle(self, *_args): pass
    def setWindowModality(self, *_args): pass
    def setMinimumDuration(self, *_args): pass
    def setValue(self, *_args): pass
    def close(self): pass
    def deleteLater(self): pass


class FakeWorker:
    def __init__(self, _update, destination, _parent):
        self.destination = destination
        self.progress = Signal()
        self.finished_download = Signal()

    def requestInterruption(self): pass

    def start(self):
        self.finished_download.emit(self.destination, "")


def test_verified_update_saves_editor_and_settings_before_launch(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    repo = ProjectRepository(tmp_path / "data")
    settings = repo.load_settings()
    settings.last_update_check_date = date.today().isoformat()
    settings.txt_export_filename = "release-notes"
    settings.txt_export_current = 38
    repo.save_settings(settings)
    profile = NovelProfile()
    repo.save_profile(profile)
    source = tmp_path / "draft.txt"
    source.write_text("old", encoding="utf-8")
    window = MainWindow(repo)
    workspace = window.workspaces[profile.id]
    editor = workspace.editor.open_file(source)
    editor.setPlainText("save before update")
    assert workspace.editor.dirty_count() == 1

    launched = []

    def launch(args, **_kwargs):
        assert source.read_text(encoding="utf-8") == "save before update"
        saved_settings = repo.load_settings()
        assert saved_settings.txt_export_filename == "release-notes"
        assert saved_settings.txt_export_current == 38
        launched.append(args[0])

    monkeypatch.setattr(workspace_window, "QProgressDialog", FakeDialog)
    monkeypatch.setattr(workspace_window, "_UpdateDownloadWorker", FakeWorker)
    monkeypatch.setattr(workspace_window.subprocess, "Popen", launch)
    monkeypatch.setattr(workspace_window.QApplication, "quit", lambda: None)
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not ask again")),
    )
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: QMessageBox.Ok)
    update = UpdateInfo(
        version="1.14.0",
        release_url="https://github.com/nastasiamql-arch/novel-translation-workflow-manager/releases/tag/v1.14.0",
        download_url="https://github.com/nastasiamql-arch/novel-translation-workflow-manager/releases/download/v1.14.0/NovelWorkflow-Setup-1.14.0.exe",
        asset_api_url="https://api.github.com/repos/nastasiamql-arch/novel-translation-workflow-manager/releases/assets/123",
        sha256="a" * 64,
        size=123,
        notes="Feature release",
    )

    window._download_update(update, tmp_path / "verified-installer.exe")

    assert launched == [str(tmp_path / "verified-installer.exe")]
    assert workspace.editor.dirty_count() == 0
    window.close()
    app.processEvents()
