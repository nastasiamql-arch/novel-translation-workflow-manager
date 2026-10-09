import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from novel_workflow.models import NovelProfile, StepFile, WorkflowStep
from novel_workflow.services import AssemblyService
from novel_workflow.storage import ProjectRepository
from novel_workflow.export_service import ExportService
from novel_workflow.workspace_editor import EditorTabs
from test_txt_export import app, panel

VOCAB = "秀儿\tซิ่วเอ๋อร์\tหญิง\tรูปเรียกสนิทของ '李秀'"
PARTIAL = "李秀\tซิ่ว\t\t"
RAW = "\nบทที่ 1\n\n \t\n" + VOCAB + "\n\u00a0\n" + PARTIAL + "\n\n[จบตอน]\n"
CLEAN = "บทที่ 1\n" + VOCAB + "\n" + PARTIAL + "\n[จบตอน]"


def test_export_and_context_preserve_blank_lines_and_vocabulary(tmp_path):
    app()
    context = tmp_path / "Context.md"
    context.write_text("old", encoding="utf-8")
    export = panel(tmp_path, context_path_callback=lambda: context)
    export.editor.setPlainText(RAW)
    export.copy_text()
    assert QApplication.clipboard().text() == RAW
    assert export.export(update_context=True)
    assert (tmp_path / "segverified1.txt").read_text(encoding="utf-8") == RAW
    assert context.read_text(encoding="utf-8") == RAW


def test_paste_preserves_empty_lines_and_can_undo(tmp_path):
    app()
    export = panel(tmp_path)
    export.editor.setPlainText("existing\n")
    cursor = export.editor.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    export.editor.setTextCursor(cursor)
    QApplication.clipboard().setText(RAW)
    export.editor.paste()
    assert export.editor.toPlainText() == "existing\n" + RAW
    export.editor.undo()
    assert export.editor.toPlainText() == "existing\n"
    QTest.keyClick(export.editor, Qt.Key_Return)
    assert export.editor.toPlainText() == "existing\n\n"


def test_workspace_paste_compacts_blank_clipboard_lines_without_rewriting_open_file(tmp_path):
    app()
    path = tmp_path / "translated" / "chapter_1.txt"
    path.parent.mkdir()
    path.write_text("existing\n", encoding="utf-8")
    tabs = EditorTabs()
    editor = tabs.open_file(path)
    assert editor is not None
    assert editor.toPlainText() == "existing\n"
    editor.moveCursor(editor.textCursor().MoveOperation.End)
    QApplication.clipboard().setText(RAW)
    editor.paste()
    assert editor.toPlainText() == "existing\n" + CLEAN
    assert path.read_text(encoding="utf-8") == "existing\n"
    assert tabs.save_editor(editor)
    assert path.read_text(encoding="utf-8") == "existing\n" + CLEAN
    editor.undo()
    assert editor.toPlainText() == "existing\n"


def test_copy_to_rich_text_app_preserves_empty_lines(tmp_path):
    app()
    from PySide6.QtGui import QTextDocument
    export = panel(tmp_path)
    export.editor.setPlainText("A\n\nB")
    export.editor.selectAll()
    export.editor.copy()
    data = QApplication.clipboard().mimeData()
    if data.hasHtml():
        document = QTextDocument()
        document.setHtml(data.html())
        assert document.toPlainText() == "A\n\nB"
    assert data.text() == "A\n\nB"


@pytest.mark.parametrize("suffix", [".txt", ".tsv"])
def test_text_file_open_save_and_copy_preserve_tabs(tmp_path, suffix):
    app()
    path = tmp_path / ("chapter" + suffix)
    path.write_text(RAW, encoding="utf-8")
    tabs = EditorTabs()
    editor = tabs.open_file(path)
    assert editor.toPlainText() == RAW
    assert path.read_text(encoding="utf-8") == RAW  # Opening alone never rewrites disk.
    editor.setPlainText(RAW)
    editor.selectAll()
    editor.copy()
    assert QApplication.clipboard().text() == RAW
    assert tabs.save_editor(editor)
    assert path.read_text(encoding="utf-8") == RAW
    assert editor.toPlainText() == RAW
    assert tabs.dirty_count() == 0


@pytest.mark.parametrize("name", ["Prompt.md", "config.json", "table.csv"])
def test_structured_files_keep_formatting(tmp_path, name):
    app()
    raw = "heading\n\n  content\t\t\n"
    path = tmp_path / name
    path.write_text(raw, encoding="utf-8")
    tabs = EditorTabs()
    editor = tabs.open_file(path)
    assert editor.toPlainText() == raw
    assert tabs.save_editor(editor)
    assert path.read_text(encoding="utf-8") == raw
    editor.selectAll()
    QApplication.clipboard().setText(raw)
    editor.paste()
    assert editor.toPlainText() == raw


def test_chapter_markdown_is_preserved(tmp_path):
    app()
    path = tmp_path / "translated" / "chapter_1.md"
    path.parent.mkdir()
    path.write_text(RAW, encoding="utf-8")
    tabs = EditorTabs()
    editor = tabs.open_file(path)
    assert editor.toPlainText() == RAW


def test_assembly_removes_blank_lines_between_files_without_changing_sources(tmp_path):
    repo = ProjectRepository(tmp_path)
    profile = NovelProfile()
    repo.save_profile(profile)
    root = repo.profile_dir(profile.id)
    path = root / "source" / "chapter_1.txt"
    path.write_text(RAW, encoding="utf-8")
    step = WorkflowStep(files=[StepFile(path="source/chapter_1.txt"), StepFile(path="source/chapter_1.txt", order=1)])
    assert AssemblyService(repo).assemble(profile, step, "[{FILE_NAME}]", False) == CLEAN + "\n" + CLEAN
    assert path.read_text(encoding="utf-8") == RAW


def test_assembly_skips_whitespace_only_files_and_keeps_headings(tmp_path):
    repo = ProjectRepository(tmp_path)
    profile = NovelProfile()
    repo.save_profile(profile)
    root = repo.profile_dir(profile.id)
    (root / "source" / "empty.txt").write_text(" \n\t\n", encoding="utf-8")
    (root / "source" / "vocab.txt").write_text("\n" + VOCAB + "\n\n" + PARTIAL, encoding="utf-8")
    step = WorkflowStep(files=[StepFile(path="source/empty.txt", label="empty"),
                              StepFile(path="source/vocab.txt", label="vocab", order=1)])
    assert AssemblyService(repo).assemble(profile, step, "[{FILE_NAME}]", True) == "[vocab]\n" + VOCAB + "\n" + PARTIAL


def test_export_draft_preserves_blank_lines(tmp_path):
    repo = ProjectRepository(tmp_path)
    profile = NovelProfile()
    repo.save_profile(profile)
    service = ExportService(repo, profile.id)
    service.save_draft(RAW)
    assert service.profile().txt_export_draft == RAW


def test_restored_export_draft_preserves_empty_lines(tmp_path):
    app()
    repo = ProjectRepository(tmp_path)
    profile = NovelProfile(txt_export_draft=RAW)
    repo.save_profile(profile)
    from novel_workflow.workspace_editor import TxtExportTab
    export = TxtExportTab(profile.txt_export_settings, export_service=ExportService(repo, profile.id))
    assert export.editor.toPlainText() == RAW


def test_autosave_preserves_disk_and_typing(tmp_path):
    app()
    path = tmp_path / "chapter.txt"
    path.write_text("A", encoding="utf-8")
    tabs = EditorTabs()
    editor = tabs.open_file(path)
    editor.setPlainText("A\n\nB\n")
    cursor = editor.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    editor.setTextCursor(cursor)
    assert tabs.save_editor(editor, autosave=True)
    assert path.read_text(encoding="utf-8") == "A\n\nB\n"
    assert editor.toPlainText() == "A\n\nB\n"
    assert editor.textCursor().position() == 5


@pytest.mark.parametrize("raw, expected", [
    ("  A  \r\n\t\r\nB\t\t", "  A  \nB\t\t"),
    ("\n \n\t\n\u00a0\n", ""),
    ("A\vB\n\nC", "A\vB\nC"),
])
def test_normalization_preserves_nonempty_line_characters(raw, expected):
    from novel_workflow.text_normalization import remove_empty_lines
    assert remove_empty_lines(raw) == expected
