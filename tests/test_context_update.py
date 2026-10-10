import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from novel_workflow.models import NovelProfile, StepFile
from novel_workflow.storage import ProjectRepository
from novel_workflow.workspace_window import MainWindow


def app():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("tag", ["SELFLOVE", "WST", "ABC"])
def test_bound_translator_updates_only_its_profile_context(tmp_path, monkeypatch, tag):
    app()
    repo = ProjectRepository(tmp_path / "data")
    first = NovelProfile(name="A")
    first_dir = repo.profile_dir(first.id)
    translator = first_dir / "source" / f"{tag}Translator.txt"
    context = tmp_path / f"{tag}Context.md"
    translator.parent.mkdir(parents=True)
    translator.write_text("บทที่ 77\nTemplate\nตัวละครเฉพาะเรื่อง 卡", encoding="utf-8")
    context.write_text("old A", encoding="utf-8")
    first.context_path = str(context)
    first.working_files = [StepFile(label=translator.name, path=f"source/{translator.name}")]
    repo.save_profile(first)

    second = NovelProfile(name="B")
    other_context = tmp_path / "OTHERContext.md"
    other_translator = repo.profile_dir(second.id) / "source" / "WSTTranslator.txt"
    other_translator.parent.mkdir(parents=True)
    other_translator.write_text("WST specific", encoding="utf-8")
    other_context.write_text("old B", encoding="utf-8")
    second.context_path = str(other_context)
    second.working_files = [StepFile(path=f"source/{other_translator.name}")]
    repo.save_profile(second)

    window = MainWindow(repo)
    window.refresh_profiles(first.id)
    workspace = window._workspace(window.profile)
    editor = workspace.editor.open_file(translator)
    editor.setPlainText("บทที่ 77\nTemplate\nชื่อตัวละครเดิมและคำแนะนำการแปล")
    monkeypatch.setattr(QMessageBox, "exec", lambda _self: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: QMessageBox.Ok)

    assert workspace.update_context_button.isHidden() is False
    original = editor.toPlainText()
    assert window.update_context_from_translator(workspace)

    assert context.read_text(encoding="utf-8") == original
    assert translator.read_text(encoding="utf-8") == original
    assert other_context.read_text(encoding="utf-8") == "old B"
    assert window.profile.verified_goal_count == 0
    assert not window.profile.verified_export_history
    assert window.profile.chapter_state.current_chapter == 77
    assert list((context.parent / ".palantir-recovery").glob("*.bak"))
    window.close()


def test_translator_button_is_hidden_for_unbound_and_other_tabs(tmp_path):
    app()
    repo = ProjectRepository(tmp_path / "data")
    profile = NovelProfile()
    folder = repo.profile_dir(profile.id)
    translator = folder / "source" / "SELFLOVETranslator.txt"
    unbound = folder / "source" / "WSTTranslator.txt"
    context = tmp_path / "SELFLOVEContext.md"
    translator.parent.mkdir(parents=True)
    translator.write_text("Translator", encoding="utf-8")
    unbound.write_text("Other", encoding="utf-8")
    context.write_text("Context", encoding="utf-8")
    profile.context_path = str(context)
    profile.working_files = [StepFile(path=f"source/{translator.name}")]
    repo.save_profile(profile)
    window = MainWindow(repo)
    window.refresh_profiles(profile.id)
    workspace = window._workspace(window.profile)

    workspace.editor.open_file(translator)
    assert workspace.update_context_button.isHidden() is False
    workspace.editor.open_file(unbound)
    assert workspace.update_context_button.isHidden()
    workspace.editor.tabs.setCurrentWidget(workspace.editor.export_tab)
    assert workspace.update_context_button.isHidden()
    assert all(action.text() != "อัปเดต Context" for action in workspace.more_menu.actions())
    window.close()


def test_shared_translator_reference_disables_context_update(tmp_path):
    app()
    repo = ProjectRepository(tmp_path / "data")
    first = NovelProfile()
    shared = repo.profile_dir(first.id) / "source" / "ABCTranslator.txt"
    shared.parent.mkdir(parents=True)
    shared.write_text("shared", encoding="utf-8")
    context = tmp_path / "AContext.md"
    context.write_text("old", encoding="utf-8")
    first.context_path = str(context)
    first.working_files = [StepFile(path=f"source/{shared.name}")]
    second = NovelProfile()
    second.context_path = str(tmp_path / "BContext.md")
    second.working_files = [StepFile(reference_type="external_file", path=str(shared))]
    repo.save_profile(first)
    repo.save_profile(second)
    window = MainWindow(repo)
    window.refresh_profiles(first.id)
    workspace = window._workspace(window.profile)
    workspace.editor.open_file(shared)

    assert workspace.update_context_button.isHidden()
    window.close()


def test_context_update_refuses_unsaved_context_edits(tmp_path, monkeypatch):
    app()
    repo = ProjectRepository(tmp_path / "data")
    profile = NovelProfile()
    folder = repo.profile_dir(profile.id)
    translator = folder / "source" / "ABCTranslator.txt"
    context = tmp_path / "ABCContext.md"
    translator.parent.mkdir(parents=True)
    translator.write_text("บทที่ 2\nsource", encoding="utf-8")
    context.write_text("บทที่ 1\nold", encoding="utf-8")
    profile.context_path = str(context)
    profile.working_files = [StepFile(path=f"source/{translator.name}")]
    repo.save_profile(profile)
    window = MainWindow(repo)
    window.refresh_profiles(profile.id)
    workspace = window._workspace(window.profile)
    workspace.editor.open_file(translator)
    context_editor = workspace.editor.open_file(context)
    context_editor.setPlainText("unsaved context")
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: QMessageBox.Ok)

    assert not window.update_context_from_translator(workspace)

    assert context.read_text(encoding="utf-8") == "บทที่ 1\nold"
    window.close()


def test_translator_external_conflict_stops_before_context_replace(tmp_path, monkeypatch):
    app()
    repo = ProjectRepository(tmp_path / "data")
    profile = NovelProfile()
    folder = repo.profile_dir(profile.id)
    translator = folder / "source" / "ABCTranslator.txt"
    context = tmp_path / "ABCContext.md"
    translator.parent.mkdir(parents=True)
    translator.write_text("source", encoding="utf-8")
    context.write_text("old context", encoding="utf-8")
    profile.context_path = str(context)
    profile.working_files = [StepFile(path=f"source/{translator.name}")]
    repo.save_profile(profile)
    window = MainWindow(repo)
    window.refresh_profiles(profile.id)
    workspace = window._workspace(window.profile)
    editor = workspace.editor.open_file(translator)
    translator.write_text("external edit", encoding="utf-8")
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: QMessageBox.Ok)

    assert not window.update_context_from_translator(workspace)

    assert context.read_text(encoding="utf-8") == "old context"
    window.close()


def test_translator_external_change_during_confirmation_stops_update(tmp_path, monkeypatch):
    app()
    repo = ProjectRepository(tmp_path / "data")
    profile = NovelProfile()
    folder = repo.profile_dir(profile.id)
    translator = folder / "source" / "ABCTranslator.txt"
    context = tmp_path / "ABCContext.md"
    translator.parent.mkdir(parents=True)
    translator.write_text("old translator", encoding="utf-8")
    context.write_text("old context", encoding="utf-8")
    profile.context_path = str(context)
    profile.working_files = [StepFile(path=f"source/{translator.name}")]
    repo.save_profile(profile)
    window = MainWindow(repo)
    window.refresh_profiles(profile.id)
    workspace = window._workspace(window.profile)
    workspace.editor.open_file(translator)

    def external_change(_self):
        translator.write_text("external translator", encoding="utf-8")
        return QMessageBox.Yes

    monkeypatch.setattr(QMessageBox, "exec", external_change)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: QMessageBox.Ok)

    assert not window.update_context_from_translator(workspace)

    assert context.read_text(encoding="utf-8") == "old context"
    window.close()


def test_atomic_context_write_failure_keeps_original_and_recovery(tmp_path, monkeypatch):
    app()
    import novel_workflow.recovery as recovery
    repo = ProjectRepository(tmp_path / "data")
    profile = NovelProfile()
    folder = repo.profile_dir(profile.id)
    translator = folder / "source" / "ABCTranslator.txt"
    context = tmp_path / "ABCContext.md"
    translator.parent.mkdir(parents=True)
    translator.write_text("new context", encoding="utf-8")
    context.write_text("old context", encoding="utf-8")
    profile.context_path = str(context)
    profile.working_files = [StepFile(path=f"source/{translator.name}")]
    repo.save_profile(profile)
    window = MainWindow(repo)
    window.refresh_profiles(profile.id)
    workspace = window._workspace(window.profile)
    workspace.editor.open_file(translator)
    monkeypatch.setattr(QMessageBox, "exec", lambda _self: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: QMessageBox.Ok)
    monkeypatch.setattr(recovery, "replace_with_retry", lambda *_args: (_ for _ in ()).throw(OSError("simulated write failure")))

    assert not window.update_context_from_translator(workspace)

    assert context.read_text(encoding="utf-8") == "old context"
    assert list((context.parent / ".palantir-recovery").glob("*.bak"))
    window.close()
