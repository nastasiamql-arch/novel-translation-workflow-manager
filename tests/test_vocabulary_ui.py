import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from novel_workflow.models import NovelProfile
from novel_workflow.storage import ProjectRepository


def test_panel_remembers_separate_profile_files(tmp_path):
    from novel_workflow.vocabulary_panel import VocabularyPanel
    app = QApplication.instance() or QApplication([])
    repo = ProjectRepository(tmp_path)
    first, second = NovelProfile(name="A"), NovelProfile(name="B")
    repo.save_profile(first); repo.save_profile(second)
    panels = [VocabularyPanel(repo, p, lambda path: None) for p in (first, second)]
    panels[0].set_file("source_path", str(tmp_path / "a.txt"))
    panels[1].set_file("source_path", str(tmp_path / "b.txt"))
    panels[0].set_file("polish_prompt_path", str(tmp_path / "polish.docx"))
    loaded = {p.id:p for p in repo.list_profiles()}
    assert loaded[first.id].vocabulary_settings.source_path.endswith("a.txt")
    assert loaded[second.id].vocabulary_settings.source_path.endswith("b.txt")
    assert loaded[first.id].vocabulary_settings.polish_prompt_path.endswith("polish.docx")
    assert "เกลา" in panels[0].run_button.text()
    assert panels[0].width() >= 0
    for panel in panels: panel.deleteLater()
    app.processEvents()


def test_editor_lock_prevents_stale_autosave(tmp_path):
    from novel_workflow.workspace_editor import EditorTabs
    app = QApplication.instance() or QApplication([])
    path = tmp_path / "vocab.tsv"
    path.write_text("source\ttarget\na\tb\n", encoding="utf-8")
    tabs = EditorTabs()
    assert tabs.supports(path)
    editor = tabs.open_file(path)
    tabs.lock_path(path)
    assert editor.isReadOnly()
    editor.setPlainText("stale")
    assert tabs.save_editor(editor, quiet=True) is False
    path.write_text("source\ttarget\na\tnew\n", encoding="utf-8")
    tabs.unlock_path(path)
    assert "new" in editor.toPlainText() and not tabs._dirty(editor)
    assert not editor.isReadOnly()
    tabs.deleteLater()
    app.processEvents()


def test_background_worker_updates_and_releases_lock(tmp_path, monkeypatch):
    import time
    from test_vocabulary import setup_run, api_result
    from novel_workflow import vocabulary_panel
    app = QApplication.instance() or QApplication([])
    repo = ProjectRepository(tmp_path / "app")
    profile = NovelProfile()
    settings, vocab = setup_run(tmp_path)
    profile.vocabulary_settings = settings
    repo.save_profile(profile)
    released = []
    class Provider:
        def validate_request(self, *args): pass
        def complete(self, *args): return api_result(new=[{"source":"new","target":"value","notes":""}])
    monkeypatch.setattr(vocabulary_panel, "create_provider", lambda *args: Provider())
    panel = vocabulary_panel.VocabularyPanel(repo, profile, lambda path: None, release=released.append)
    monkeypatch.setattr(panel.credentials, "get", lambda *args: "key")
    panel.start()
    assert not panel.run_button.isEnabled()
    deadline = time.monotonic() + 5
    while panel.worker is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    assert panel.worker is None
    assert panel.run_button.isEnabled() and released == [str(vocab)]
    assert "เพิ่ม 1" in panel.status.text() and "new\tvalue" in vocab.read_text("utf-8")
    panel.deleteLater()
    app.processEvents()


def test_workspace_panel_stays_readable_at_default_window_size(tmp_path):
    from datetime import date
    from novel_workflow.workspace_window import MainWindow
    app = QApplication.instance() or QApplication([])
    repo = ProjectRepository(tmp_path)
    settings = repo.load_settings()
    settings.last_update_check_date = date.today().isoformat()
    repo.save_settings(settings)
    profile = NovelProfile()
    repo.save_profile(profile)
    window = MainWindow(repo)
    window.show()
    app.processEvents()
    workspace = window.workspaces[profile.id]
    assert workspace.vocabulary_panel.width() >= 250
    assert workspace.editor.width() >= 300
    workspace.vocabulary_panel.toggle()
    app.processEvents()
    assert workspace.vocabulary_panel.width() <= 70
    workspace.vocabulary_panel.toggle()
    app.processEvents()
    assert workspace.vocabulary_panel.width() >= 250
    window.close()
    app.processEvents()


def test_failed_vocab_reload_cannot_restore_stale_buffer(tmp_path):
    from novel_workflow.workspace_editor import EditorTabs
    app = QApplication.instance() or QApplication([])
    path = tmp_path / "vocab.tsv"
    path.write_text("source\ttarget\na\tb\n", encoding="utf-8")
    tabs = EditorTabs()
    editor = tabs.open_file(path)
    tabs.lock_path(path)
    path.unlink()
    tabs.unlock_path(path)
    assert editor.isReadOnly()
    assert not tabs.save_editor(editor, quiet=True)
    assert not path.exists()
    tabs.deleteLater()
    app.processEvents()


def test_model_list_worker_fetches_models_off_ui_thread():
    from novel_workflow.vocabulary_panel import ModelListWorker
    app = QApplication.instance() or QApplication([])
    class Provider:
        def __init__(self): self.thread = None; self.base_url = "https://api.example/v1"
        def list_models(self, key):
            from PySide6.QtCore import QThread
            self.thread = QThread.currentThread()
            assert key == "temporary-key"
            return ["model-a", "model-b"]
    provider = Provider()
    worker = ModelListWorker(provider, "temporary-key")
    result = []
    worker.succeeded.connect(lambda endpoint, names: result.extend((endpoint, names)))
    worker.start()
    assert worker.wait(3000)
    app.processEvents()
    assert result == ["https://api.example/v1", ["model-a", "model-b"]]
    assert provider.thread != app.thread()
    assert worker.key == ""
    worker.deleteLater()
    app.processEvents()


def test_pipeline_failure_reports_phase_and_safe_provider_status(tmp_path):
    from test_vocabulary import setup_run
    from novel_workflow.vocabulary_panel import VocabularyWorker
    settings, _ = setup_run(tmp_path)
    class Provider:
        def complete(self, *args):
            raise ValueError("Provider HTTP 403; check key and API access")
    worker = VocabularyWorker(settings, Provider(), "private-api-key")
    worker.run()
    assert worker.current_phase == "extract"
    assert "หาศัพท์ไม่สำเร็จ" in worker.error
    assert "HTTP 403" in worker.error and "ไม่มีสิทธิ์" in worker.error
    assert "private-api-key" not in worker.error
    assert worker.key == ""
