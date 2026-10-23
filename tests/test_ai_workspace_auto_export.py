"""Integration-style auto export preflight with a fake bound editor/service.

The real export engine has separate transaction/recovery integration tests.
"""
from pathlib import Path
from types import SimpleNamespace

from novel_workflow.ai_workspace.core import build_jobs, record_response
from novel_workflow.ai_workspace.page import AIWorkspacePage


class Editor:
    def __init__(self, target):
        self.target = target
        self.text = ""

    def setPlainText(self, text):
        self.text = text


class EditorService:
    def __init__(self, target):
        self.target = target
        self.editor = Editor(target)

    def save_all(self, *, include_normalization):
        return True

    def open_file(self, target):
        return target == self.target

    def _current_editor(self):
        return self.editor

    def _path(self, editor):
        return self.target

    def _dirty(self, editor):
        return False

    def save_editor(self, editor, *, quiet, normalize):
        self.target.write_text(editor.text, encoding="utf-8")
        return True


def prepared_page(tmp_path, *, consent=True):
    profile = SimpleNamespace(id="a" * 32)
    target = tmp_path / "Novel Translator.txt"
    target.write_text("", encoding="utf-8")
    chapter = SimpleNamespace(number=475, path=Path("475.txt"))
    job = build_jobs(profile.id, "แปล", [chapter], 1)[0]
    record_response(job, "บทที่ 475\nข้อความฉบับแปล\n[จบตอน]\nคำศัพท์ใหม่\n[-]")
    job.auto_export = consent
    editor = EditorService(target)
    workspace = SimpleNamespace(editor=editor)
    events = []
    owner = SimpleNamespace(
        profile=profile,
        workspaces={profile.id: workspace},
        _profile_file_paths=lambda p: [target],
        _translator_profile_for_path=lambda pid, path: profile if path == target else None,
        update_context_from_translator=lambda workspace, **kwargs: events.append(kwargs) or True,
    )
    status = SimpleNamespace(setText=lambda message: events.append(message))
    page = SimpleNamespace(owner=owner, jobs=[job], status=status,
                           _selected_profile=lambda: profile,
                           _save=lambda: events.append("saved"))
    return page, target, job, events


def test_opt_in_auto_export_uses_existing_export_service(tmp_path):
    page, target, job, events = prepared_page(tmp_path)
    AIWorkspacePage.import_export(page, automatic=True)
    assert job.imported and job.status == "IMPORTED"
    assert "บทที่ 475" in target.read_text(encoding="utf-8")
    assert {"preauthorized": True} in events


def test_auto_export_rejects_missing_batch_consent_without_writing(tmp_path):
    page, target, job, events = prepared_page(tmp_path, consent=False)
    AIWorkspacePage.import_export(page, automatic=True)
    assert target.read_text(encoding="utf-8") == ""
    assert not job.imported
    assert not any(isinstance(x, dict) for x in events)
