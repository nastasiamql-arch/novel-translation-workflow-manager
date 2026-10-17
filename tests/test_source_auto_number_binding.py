"""Regression coverage for source-file automatic numbering discovery and manual start."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
from PySide6.QtWidgets import QApplication
from novel_workflow.models import NovelProfile, StepFile
from novel_workflow.storage import ProjectRepository
from novel_workflow.chapter_number_reference import resolve_translator_reference
from novel_workflow.chapter_numbering_dialog import ChapterNumberDialog
from novel_workflow.workspace_window import MainWindow
from test_release_36 import setup_profile


def test_unbound_translator_sibling_is_accepted_only_within_owned_profile_dir(tmp_path):
    repo = ProjectRepository(tmp_path)
    profile = NovelProfile(name="SEG")
    repo.save_profile(profile)
    folder = repo.profile_dir(profile.id)
    source = folder / "SEG.txt"
    source.write_text("第646章 开始", encoding="utf-8")
    trans = folder / "SEGTranslator.txt"
    trans.write_text("บทที่ 630\nงานแปล", encoding="utf-8")
    found = resolve_translator_reference(repo, profile.id, source)
    assert found.path == trans and found.start == 631
    external = tmp_path / "unbound" / "SEG.txt"
    external.parent.mkdir()
    external.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    (external.parent / "SEGTranslator.txt").write_text("บทที่ 99", encoding="utf-8")
    assert resolve_translator_reference(repo, profile.id, external).start is None


def test_start_number_is_remembered_only_as_manual_fallback(tmp_path):
    repo, profile, _ = setup_profile(tmp_path)
    source = repo.profile_dir(profile.id) / "source" / "SEG.txt"
    source.parent.mkdir(exist_ok=True)
    source.write_text("第646章 开始", encoding="utf-8")
    app = QApplication.instance() or QApplication([])
    window = MainWindow(repo)
    window.select_profile(next(i for i, p in enumerate(window.ps_list) if p.id == profile.id))
    workspace = window.workspaces[profile.id]
    editor = workspace.editor.open_file(source)
    first = ChapterNumberDialog(workspace, editor, source)
    first.start_number.setValue(631)
    stored = next(p for p in repo.list_profiles() if p.id == profile.id)
    assert stored.chapter_manual_start == 631
    second = ChapterNumberDialog(workspace, editor, source)
    assert second.start_number.value() == 631
    assert second.translator_reference.start is None
    first.close(); second.close()
    window._close_export_reminder_accepted = True
    window.close()


def test_external_source_matches_explicit_bound_translator(tmp_path):
    repo, profile, _ = setup_profile(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    source = outside / "SEG.txt"
    source.write_text("第646章 开始", encoding="utf-8")
    trans = outside / "SEGTranslator.txt"
    trans.write_text("บทที่ 630\nงานแปล", encoding="utf-8")
    profile.working_files = [StepFile(path=str(trans), reference_type="external_file")]
    profile.auto_review_enabled = True
    profile.auto_chapter_number_mode = "fix"
    repo.save_profile(profile)
    app = QApplication.instance() or QApplication([])
    window = MainWindow(repo)
    window.select_profile(next(i for i, p in enumerate(window.ps_list) if p.id == profile.id))
    workspace = window.workspaces[profile.id]
    editor = workspace.editor.open_file(source)
    workspace.editor.tabs.setCurrentWidget(editor)
    assert window._auto_original_source_eligible(window.profile, workspace, source)
    editor.setPlainText("第646章 开始\n故事")
    assert workspace.editor.save_editor(editor, quiet=True)
    assert workspace.auto_chapter_review_timer.isActive()
    workspace.auto_chapter_review_timer.stop()
    window._run_auto_chapter_review(profile.id)
    assert source.read_text(encoding="utf-8").startswith("第631章")
    assert trans.read_text(encoding="utf-8").startswith("บทที่ 630")
    window._close_export_reminder_accepted = True
    window.close()
