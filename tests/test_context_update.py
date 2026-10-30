import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import hashlib
import json
import os
import pytest
from pathlib import Path
from PySide6.QtCore import QMimeData
from PySide6.QtWidgets import QApplication, QMessageBox

from novel_workflow.models import NovelProfile, StepFile
from novel_workflow.storage import ProjectRepository
from novel_workflow.workspace_window import MainWindow


def app():
    return QApplication.instance() or QApplication([])


def configure_translator_export_history(profile, folder, translator, context):
    """Tests opt into the explicit step-two attachment required before Context replacement."""
    profile.main_folder = str(folder)
    step = profile.workflow.steps[1]
    step.files = [
        StepFile(label=translator.name, path=f"source/{translator.name}", order=0),
        StepFile(label=context.name, reference_type="external_file", path=str(context), order=1),
    ]
    profile.polish_history_step_id = step.id


@pytest.mark.parametrize("choice", ["Keep Editing", "Replace Anyway"])
def test_destructive_paste_preserves_old_text_or_saves_recovery(tmp_path, monkeypatch, choice):
    app()
    repo = ProjectRepository(tmp_path / "data")
    profile = NovelProfile(name="Paste protection")
    folder = repo.profile_dir(profile.id)
    translator = folder / "source" / "TESTTranslator.txt"
    context = tmp_path / "TESTContext.md"
    translator.parent.mkdir(parents=True)
    translator.write_text("old translation", encoding="utf-8")
    context.write_text("old context", encoding="utf-8")
    profile.context_path = str(context)
    profile.working_files = [StepFile(path=f"source/{translator.name}")]
    repo.save_profile(profile)
    window = MainWindow(repo); window.refresh_profiles(profile.id)
    workspace = window.workspaces[profile.id]
    editor = workspace.editor.open_file(translator)
    window._mark_export_pending(profile.id, translator)
    editor.selectAll()
    old_selection = editor.textCursor().selectedText()
    QApplication.clipboard().setText("clipboard stays")
    mime = QMimeData(); mime.setText("replacement")

    def choose_dialog_button(dialog):
        button = next(button for button in dialog.buttons() if button.text() == choice)
        button.click()
        return 0

    monkeypatch.setattr(QMessageBox, "exec", choose_dialog_button)
    editor.insertFromMimeData(mime)
    assert QApplication.clipboard().text() == "clipboard stays"
    if choice == "Keep Editing":
        assert editor.toPlainText() == "old translation"
        assert editor.textCursor().selectedText() == old_selection
    else:
        recovery = json.loads(workspace.editor._recovery_path(translator).read_text(encoding="utf-8"))
        assert recovery["text"] == "old translation"
        assert editor.toPlainText() == "replacement\n"
    window._close_export_reminder_accepted = True
    window.close()


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
    configure_translator_export_history(first, first_dir, translator, context)
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
    assert workspace.export_status_label.text() == "⚠ ยังไม่ได้ Export"
    editor.setPlainText("บทที่ 77\nTemplate\nชื่อตัวละครเดิมและคำแนะนำการแปล")
    assert workspace.export_status_label.text() == "⚠ ยังไม่ได้ Export"
    monkeypatch.setattr(QMessageBox, "exec", lambda _self: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: QMessageBox.Ok)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[2]))

    assert workspace.update_context_button.isHidden() is False
    original = editor.toPlainText()
    assert window.update_context_from_translator(workspace)
    assert workspace.export_status_label.text() == "✓ ส่งออกแล้ว"

    assert context.read_text(encoding="utf-8") == original
    assert translator.read_text(encoding="utf-8") == original
    assert other_context.read_text(encoding="utf-8") == "old B"
    assert window.profile.verified_goal_count == 0
    assert not window.profile.verified_export_history
    assert window.profile.chapter_state.current_chapter == 77
    exports = list((first_dir / "Context Exports").glob("*.txt"))
    assert [item.name for item in exports] == [f"{tag}Translator 77.txt"]
    assert exports[0].read_bytes() == context.read_bytes() == translator.read_bytes()
    state_path = repo.profile_dir(first.id) / "export_status.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    record = state[os.path.normcase(str(translator.resolve()))]
    assert record["profile_id"] == first.id
    assert record["translator_path"] == os.path.normcase(str(translator.resolve()))
    assert record["digest"] == hashlib.sha256(translator.read_bytes()).hexdigest()
    assert record["exported_txt_path"] == str(exports[0].resolve())
    assert record["exported_at"]
    assert not (repo.profile_dir(second.id) / "export_status.json").exists()
    history = first_dir / "Polish History" / "ตรวจคำแปล บท 77"
    manifest = json.loads((history / "manifest.json").read_text(encoding="utf-8"))
    context_record = next(item for item in manifest["files"] if item["is_context"])
    assert manifest["step_id"] == first.workflow.steps[1].id
    assert manifest["chapter_range"] == "77"
    assert manifest["file_count"] == 2
    assert context_record["sha256"] == hashlib.sha256(b"old A").hexdigest()
    assert (history / context_record["snapshot_path"]).read_bytes() == b"old A"
    assert not warnings

    editor.moveCursor(editor.textCursor().MoveOperation.End)
    editor.insertPlainText("x")
    assert workspace.export_status_label.text() == "⚠ ต้อง Export ใหม่"
    editor.undo()
    workspace._confirm_export_digest()
    assert workspace.export_status_label.text() == "✓ ส่งออกแล้ว"
    assert not list(context.parent.glob(".palantir-recovery/*.bak"))
    window.close()


def test_translator_export_requires_context_attached_to_selected_review_step(tmp_path, monkeypatch):
    app()
    repo = ProjectRepository(tmp_path / "data")
    profile = NovelProfile()
    folder = repo.profile_dir(profile.id)
    translator = folder / "source" / "ABCTranslator.txt"
    context = tmp_path / "Context.md"
    translator.parent.mkdir(parents=True)
    translator.write_text("บทที่ 6-10\nnew", encoding="utf-8")
    context.write_text("บทที่ 1-5\nold", encoding="utf-8")
    profile.context_path = str(context)
    profile.working_files = [StepFile(path=f"source/{translator.name}")]
    profile.main_folder = str(folder)
    step = profile.workflow.steps[1]
    step.files = [StepFile(path=f"source/{translator.name}")]
    profile.polish_history_step_id = step.id
    repo.save_profile(profile)
    window = MainWindow(repo)
    window.refresh_profiles(profile.id)
    workspace = window._workspace(window.profile)
    workspace.editor.open_file(translator)
    confirmations = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: confirmations.append(args[2]))
    monkeypatch.setattr(QMessageBox, "exec", lambda *_args: pytest.fail("must stop before confirmation"))

    assert not window.update_context_from_translator(workspace)
    assert "ยังไม่ได้เลือกไฟล์ Context ในขั้นตอนตรวจคำแปล" in confirmations[0]
    assert context.read_text(encoding="utf-8") == "บทที่ 1-5\nold"
    assert not list((folder / "Context Exports").glob("*.txt"))
    assert not list((folder / "Polish History").glob("ตรวจคำแปล บท *"))
    window.close()


def test_cancelled_translator_export_does_not_create_history(tmp_path, monkeypatch):
    app()
    repo = ProjectRepository(tmp_path / "data")
    profile = NovelProfile()
    folder = repo.profile_dir(profile.id)
    translator = folder / "source" / "ABCTranslator.txt"
    context = tmp_path / "Context.md"
    translator.parent.mkdir(parents=True)
    translator.write_text("บทที่ 6-10\nnew", encoding="utf-8")
    old_context = b"\xef\xbb\xbf\xe0\xb8\x9a\xe0\xb8\x97\xe0\xb8\x97\xe0\xb8\xb5\xe0\xb9\x88 1-5\r\nold\t \r\n"
    context.write_bytes(old_context)
    profile.context_path = str(context)
    profile.working_files = [StepFile(path=f"source/{translator.name}")]
    configure_translator_export_history(profile, folder, translator, context)
    repo.save_profile(profile)
    window = MainWindow(repo)
    window.refresh_profiles(profile.id)
    workspace = window._workspace(window.profile)
    workspace.editor.open_file(translator)
    monkeypatch.setattr(QMessageBox, "exec", lambda *_args: QMessageBox.No)

    assert not window.update_context_from_translator(workspace)
    assert context.read_bytes() == old_context
    assert not list((folder / "Context Exports").glob("*.txt"))
    assert not list((folder / "Polish History").glob("ตรวจคำแปล บท *"))
    window.close()


def test_snapshot_failure_stops_translator_export_before_context_write(tmp_path, monkeypatch):
    app()
    import novel_workflow.polish_history as polish_history
    repo = ProjectRepository(tmp_path / "data")
    profile = NovelProfile()
    folder = repo.profile_dir(profile.id)
    translator = folder / "source" / "ABCTranslator.txt"
    context = tmp_path / "Context.md"
    translator.parent.mkdir(parents=True)
    translator.write_text("บทที่ 6-10\nnew", encoding="utf-8")
    old_context = "\ufeffบทที่ 1-5\r\nold\t \r\n".encode("utf-8")
    context.write_bytes(old_context)
    profile.context_path = str(context)
    profile.working_files = [StepFile(path=f"source/{translator.name}")]
    configure_translator_export_history(profile, folder, translator, context)
    repo.save_profile(profile)
    window = MainWindow(repo)
    window.refresh_profiles(profile.id)
    workspace = window._workspace(window.profile)
    workspace.editor.open_file(translator)
    warnings = []
    monkeypatch.setattr(QMessageBox, "exec", lambda *_args: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[2]))
    monkeypatch.setattr(
        polish_history.PolishHistory, "_copy_file",
        lambda *_args: (_ for _ in ()).throw(OSError("disk full")),
    )

    assert not window.update_context_from_translator(workspace)
    assert context.read_bytes() == old_context
    assert not list((folder / "Context Exports").glob("*.txt"))
    assert any("disk full" in message for message in warnings)
    assert not list((folder / "Polish History").glob("ตรวจคำแปล บท *"))
    window.close()


def test_translator_changed_during_snapshot_stops_context_replacement(tmp_path, monkeypatch):
    app()
    import novel_workflow.polish_history as polish_history
    repo = ProjectRepository(tmp_path / "data")
    profile = NovelProfile()
    folder = repo.profile_dir(profile.id)
    translator = folder / "source" / "ABCTranslator.txt"
    context = tmp_path / "Context.md"
    translator.parent.mkdir(parents=True)
    translator.write_text("บทที่ 6-10\ntranslator", encoding="utf-8")
    context.write_bytes("\ufeffบทที่ 1-5\r\nold\t\r\n".encode("utf-8"))
    original_context = context.read_bytes()
    profile.context_path = str(context)
    profile.working_files = [StepFile(path=f"source/{translator.name}")]
    configure_translator_export_history(profile, folder, translator, context)
    repo.save_profile(profile)
    window = MainWindow(repo)
    window.refresh_profiles(profile.id)
    workspace = window._workspace(window.profile)
    workspace.editor.open_file(translator)
    warnings = []
    monkeypatch.setattr(QMessageBox, "exec", lambda *_args: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[2]))
    copy_file = polish_history.PolishHistory._copy_file

    def mutate_after_copy(source, destination):
        copy_file(source, destination)
        if source.resolve() == translator.resolve():
            translator.write_text("บทที่ 6-10\nexternal edit", encoding="utf-8")

    monkeypatch.setattr(polish_history.PolishHistory, "_copy_file", staticmethod(mutate_after_copy))

    assert not window.update_context_from_translator(workspace)
    assert context.read_bytes() == original_context
    assert "external edit" in translator.read_text(encoding="utf-8")
    assert not list((folder / "Context Exports").glob("*.txt"))
    assert not list((folder / "Polish History").glob("ตรวจคำแปล บท *"))
    assert any("changed" in message or "เปลี่ยน" in message for message in warnings)
    window.close()


def test_export_now_saves_the_current_unsaved_translator_before_export(tmp_path, monkeypatch):
    app()
    repo = ProjectRepository(tmp_path / "data")
    profile = NovelProfile(name="Export current draft")
    folder = repo.profile_dir(profile.id)
    translator = folder / "source" / "TESTTranslator.txt"
    context = tmp_path / "TESTContext.md"
    translator.parent.mkdir(parents=True)
    translator.write_text("old translation", encoding="utf-8")
    context.write_text("old context", encoding="utf-8")
    profile.context_path = str(context)
    profile.working_files = [StepFile(path=f"source/{translator.name}")]
    configure_translator_export_history(profile, folder, translator, context)
    repo.save_profile(profile)

    window = MainWindow(repo)
    window.refresh_profiles(profile.id)
    workspace = window.workspaces[profile.id]
    editor = workspace.editor.open_file(translator)
    editor.setPlainText("[A]Chapter 1\ncurrent unsaved translation")
    monkeypatch.setattr(QMessageBox, "exec", lambda _self: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: QMessageBox.Ok)

    assert window._export_profile_translator(profile.id)
    expected = editor.toPlainText().encode("utf-8")
    assert translator.read_bytes() == context.read_bytes() == expected
    exports = list((folder / "Context Exports").glob("*.txt"))
    assert len(exports) == 1 and exports[0].read_bytes() == expected
    window.close()


def test_export_replaces_context_with_exact_translator_bytes_without_backup(tmp_path, monkeypatch):
    app()
    from novel_workflow.recovery import list_backups

    repo = ProjectRepository(tmp_path / "data")
    profile = NovelProfile()
    folder = repo.profile_dir(profile.id)
    translator = folder / "source" / "SELFLOVETranslator.txt"
    context = tmp_path / "SELFLOVEContext.md"
    translator.parent.mkdir(parents=True)
    translator.write_text("บทที่ 6-10\nNew Context", encoding="utf-8")
    old_bytes = "\ufeff# Chapter Progress\r\n\r\nChapter 1\r\nChapter 2\r\nChapter 3\r\nChapter 4\r\nChapter 5\r\n\t中文  \r\n".encode("utf-8")
    context.write_bytes(old_bytes)
    profile.context_path = str(context)
    profile.working_files = [StepFile(path=f"source/{translator.name}")]
    configure_translator_export_history(profile, folder, translator, context)
    repo.save_profile(profile)
    window = MainWindow(repo)
    window.refresh_profiles(profile.id)
    workspace = window._workspace(window.profile)
    workspace.editor.open_file(translator)
    monkeypatch.setattr(QMessageBox, "exec", lambda _self: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: QMessageBox.Ok)

    assert window.update_context_from_translator(workspace)

    exports = list((folder / "Context Exports").glob("*.txt"))
    assert [item.name for item in exports] == ["SELFLOVETranslator 6-10.txt"]
    assert exports[0].read_bytes() == context.read_bytes() == translator.read_bytes()
    history = folder / "Polish History" / "ตรวจคำแปล บท 6-10"
    manifest = json.loads((history / "manifest.json").read_text(encoding="utf-8"))
    context_record = next(item for item in manifest["files"] if item["is_context"])
    assert manifest["chapter_range"] == "6-10"
    assert manifest["file_count"] == 2
    assert context_record["sha256"] == hashlib.sha256(old_bytes).hexdigest()
    assert (history / context_record["snapshot_path"]).read_bytes() == old_bytes
    assert not list_backups(context)
    assert not list(context.parent.glob(".palantir-recovery/*.bak"))
    assert not list(context.parent.glob(".palantir-recovery/*.bak.meta"))
    window.close()


def test_context_update_backup_uses_actual_translator_name_and_profile_binding(tmp_path, monkeypatch):
    app()
    from novel_workflow.recovery import list_backups

    repo = ProjectRepository(tmp_path / "data")
    profile = NovelProfile()
    folder = repo.profile_dir(profile.id)
    translator = folder / "source" / "作品Translator.txt"
    context = tmp_path / "Context.md"
    translator.parent.mkdir(parents=True)
    translator.write_text("第101章\n新しい内容", encoding="utf-8")
    context.write_text("Chapter 101\nold", encoding="utf-8")
    profile.context_path = str(context)
    profile.working_files = [StepFile(path=f"source/{translator.name}")]
    configure_translator_export_history(profile, folder, translator, context)
    repo.save_profile(profile)
    window = MainWindow(repo)
    window.refresh_profiles(profile.id)
    workspace = window._workspace(window.profile)
    workspace.editor.open_file(translator)
    monkeypatch.setattr(QMessageBox, "exec", lambda _self: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: QMessageBox.Ok)

    assert window.update_context_from_translator(workspace)

    assert (repo.profile_dir(profile.id) / "Context Exports" / "作品Translator 101.txt").read_bytes() == context.read_bytes()
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
    configure_translator_export_history(profile, folder, translator, context)
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
    assert all(action.text() != "Export" for action in workspace.more_menu.actions())
    assert workspace.update_context_button.text() == "Export"
    assert workspace.update_context_button.toolTip() == "ส่งออก Translator เป็น TXT และอัปเดต Context"
    window.close()


@pytest.mark.parametrize(
    ("chapter_text", "filename"),
    [
        ("บทที่ 1\nบทที่ 3", "ABCTranslator 1-3.txt"),
        ("Chapter 4\nChapter 10", "ABCTranslator 4-10.txt"),
        ("บทที่ 11-12", "ABCTranslator 11-12.txt"),
        ("บทที่ 13\nบทที่ 25", "ABCTranslator 13-25.txt"),
        ("第26章", "ABCTranslator 26.txt"),
    ],
)
def test_export_uses_dynamic_chapter_span_and_keeps_exact_bytes(
    tmp_path, monkeypatch, chapter_text, filename
):
    app()
    repo = ProjectRepository(tmp_path / "data")
    profile = NovelProfile()
    folder = repo.profile_dir(profile.id)
    translator = folder / "source" / "ABCTranslator.txt"
    context = tmp_path / "ABCContext.md"
    translator.parent.mkdir(parents=True)
    payload = ("\ufeff" + chapter_text + "\r\n\t  中文  \r\n[จบตอน]\r\n").encode("utf-8")
    translator.write_bytes(payload)
    context.write_bytes(b"old context must not be appended")
    profile.context_path = str(context)
    profile.working_files = [StepFile(path=f"source/{translator.name}")]
    configure_translator_export_history(profile, folder, translator, context)
    repo.save_profile(profile)
    window = MainWindow(repo)
    window.refresh_profiles(profile.id)
    workspace = window._workspace(window.profile)
    workspace.editor.open_file(translator)
    monkeypatch.setattr(QMessageBox, "exec", lambda _self: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: QMessageBox.Ok)

    assert window.update_context_from_translator(workspace)
    output = folder / "Context Exports" / filename
    assert translator.read_bytes() == payload
    assert output.read_bytes() == payload
    assert context.read_bytes() == payload
    assert not list(folder.rglob("*.transaction-recovery"))
    assert not list(folder.rglob("*.bak"))
    window.close()


def test_export_duplicate_names_are_case_insensitive_and_never_overwrite(tmp_path, monkeypatch):
    app()
    repo = ProjectRepository(tmp_path / "data")
    profile = NovelProfile()
    folder = repo.profile_dir(profile.id)
    translator = folder / "source" / "WSTTranslator.txt"
    context = tmp_path / "WSTContext.md"
    export_folder = folder / "Context Exports"
    translator.parent.mkdir(parents=True)
    export_folder.mkdir()
    translator.write_text("บทที่ 4-10\nnew", encoding="utf-8")
    context.write_text("old", encoding="utf-8")
    prior = export_folder / "wsttranslator 4-10.TXT"
    prior.write_text("keep", encoding="utf-8")
    profile.context_path = str(context)
    profile.working_files = [StepFile(path=f"source/{translator.name}")]
    configure_translator_export_history(profile, folder, translator, context)
    repo.save_profile(profile)
    window = MainWindow(repo)
    window.refresh_profiles(profile.id)
    workspace = window._workspace(window.profile)
    workspace.editor.open_file(translator)
    monkeypatch.setattr(QMessageBox, "exec", lambda _self: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: QMessageBox.Ok)

    assert window.update_context_from_translator(workspace)
    assert (export_folder / "WSTTranslator 4-10 (2).txt").exists()
    assert prior.read_text(encoding="utf-8") == "keep"
    assert window.update_context_from_translator(workspace)
    assert (export_folder / "WSTTranslator 4-10 (3).txt").exists()
    window.close()


@pytest.mark.parametrize(
    ("translator_text", "expected"),
    [
        ("[A]第82章 標題\n[A]ข้อความ 82 อยู่กลางประโยค\n[B]บทที่ 82 ชื่อบท", "82"),
        ("[A] 第82章 标题\n[B] บทที่ 83 ชื่อบท", "82-83"),
        ("[A]第82-84章 ชื่อบท\n[B]บทที่ 82-84", "82-84"),
        ("บทที่ 1\nบทที่ 3", "1-3"),
        ("Chapter 4\nChapter 10", "4-10"),
        ("บทที่ 318-325", "318-325"),
        ("[B]บทที่ 26", "26"),
        ("ข้อความทั่วไป มีเลข 82 และ 84\n[A]ตัวละครพูดว่า Chapter 9", None),
    ],
)
def test_translator_chapter_range_supports_bilingual_markers(translator_text, expected):
    from novel_workflow.recovery import translator_chapter_range

    assert translator_chapter_range(translator_text.encode("utf-8")) == expected


def test_export_without_chapter_heading_uses_visible_timestamp_name(tmp_path, monkeypatch):
    app()
    repo = ProjectRepository(tmp_path / "data")
    profile = NovelProfile()
    folder = repo.profile_dir(profile.id)
    translator = folder / "source" / "ABCTranslator.txt"
    context = tmp_path / "ABCContext.md"
    translator.parent.mkdir(parents=True)
    translator.write_text("A sentence containing numbers 1 and 5", encoding="utf-8")
    context.write_text("old", encoding="utf-8")
    profile.context_path = str(context)
    profile.working_files = [StepFile(path=f"source/{translator.name}")]
    configure_translator_export_history(profile, folder, translator, context)
    repo.save_profile(profile)
    window = MainWindow(repo)
    window.refresh_profiles(profile.id)
    workspace = window._workspace(window.profile)
    workspace.editor.open_file(translator)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: (warnings.append(repr(_args)), QMessageBox.Ok)[1])
    monkeypatch.setattr(QMessageBox, "exec", lambda _self: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: QMessageBox.Ok)
    monkeypatch.setattr("novel_workflow.workspace_window.QInputDialog.getText", lambda *_args: ("1-5", True))
    monkeypatch.setattr(
        QMessageBox, "setDetailedText",
        lambda *_args: pytest.fail("Export confirmation must not receive novel text"),
    )

    assert window.update_context_from_translator(workspace), warnings
    exports = list((folder / "Context Exports").glob("ABCTranslator *.txt"))
    assert len(exports) == 1
    assert exports[0].name.startswith("ABCTranslator 20")
    assert context.read_bytes() == translator.read_bytes() == exports[0].read_bytes()
    window.close()


def test_export_large_translator_reuses_saved_snapshot_and_profile_listing(tmp_path, monkeypatch):
    app()
    repo = ProjectRepository(tmp_path / "data")
    profile = NovelProfile()
    folder = repo.profile_dir(profile.id)
    translator = folder / "source" / "FASTTranslator.txt"
    context = tmp_path / "FASTContext.md"
    translator.parent.mkdir(parents=True)
    payload = b"[A]Chapter 82\r\n" + (b"\t[A]Chinese text 82\r\n[B]Thai text 82\r\n" * 24000)
    translator.write_bytes(payload)
    context.write_bytes(b"old context")
    profile.context_path = str(context)
    profile.working_files = [StepFile(path=f"source/{translator.name}")]
    configure_translator_export_history(profile, folder, translator, context)
    repo.save_profile(profile)
    window = MainWindow(repo)
    window.refresh_profiles(profile.id)
    workspace = window._workspace(window.profile)
    workspace.editor.open_file(translator)
    monkeypatch.setattr(QMessageBox, "exec", lambda _self: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: QMessageBox.Ok)

    reads = {"source": 0}
    profile_lists = {"count": 0}
    snapshot_hashes = {"count": 0}
    tracking = {"active": True}
    real_read_bytes = Path.read_bytes
    real_list_profiles = repo.list_profiles
    import novel_workflow.workspace_window as workspace_window
    real_sha256 = workspace_window.hashlib.sha256

    def counted_read_bytes(path):
        if tracking["active"] and path.resolve() == translator.resolve():
            reads["source"] += 1
        return real_read_bytes(path)

    def counted_list_profiles():
        profile_lists["count"] += 1
        return real_list_profiles()

    def counted_sha256(data=b"", *args, **kwargs):
        if tracking["active"] and data == payload:
            snapshot_hashes["count"] += 1
        return real_sha256(data, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", counted_read_bytes)
    monkeypatch.setattr(repo, "list_profiles", counted_list_profiles)
    monkeypatch.setattr(workspace_window.hashlib, "sha256", counted_sha256)

    assert window.update_context_from_translator(workspace)
    tracking["active"] = False
    assert reads["source"] == 3
    assert snapshot_hashes["count"] == 3
    assert profile_lists["count"] <= 14
    assert context.read_bytes() == translator.read_bytes() == next(
        (folder / "Context Exports").glob("FASTTranslator 82.txt")
    ).read_bytes()
    window.close()


def test_export_staging_failure_leaves_context_and_export_folder_unchanged(tmp_path, monkeypatch):
    app()
    import novel_workflow.workspace_window as workspace_window

    repo = ProjectRepository(tmp_path / "data")
    profile = NovelProfile()
    folder = repo.profile_dir(profile.id)
    translator = folder / "source" / "ABCTranslator.txt"
    context = tmp_path / "ABCContext.md"
    translator.parent.mkdir(parents=True)
    translator.write_text("บทที่ 1\nnew", encoding="utf-8")
    context.write_text("old", encoding="utf-8")
    profile.context_path = str(context)
    profile.working_files = [StepFile(path=f"source/{translator.name}")]
    configure_translator_export_history(profile, folder, translator, context)
    repo.save_profile(profile)
    window = MainWindow(repo)
    window.refresh_profiles(profile.id)
    workspace = window._workspace(window.profile)
    workspace.editor.open_file(translator)
    monkeypatch.setattr(QMessageBox, "exec", lambda _self: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: QMessageBox.Ok)
    real_stage = workspace_window._stage_bytes_file
    count = 0

    def fail_second_stage(destination, data):
        nonlocal count
        count += 1
        if count == 2:
            raise OSError("simulated staging failure")
        return real_stage(destination, data)

    monkeypatch.setattr(workspace_window, "_stage_bytes_file", fail_second_stage)
    assert not window.update_context_from_translator(workspace)
    assert context.read_text(encoding="utf-8") == "old"
    assert not list((folder / "Context Exports").glob("*.txt"))
    assert not list(folder.rglob(".palantir-staging-*"))
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
    configure_translator_export_history(profile, folder, translator, context)
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
    configure_translator_export_history(profile, folder, translator, context)
    repo.save_profile(profile)
    window = MainWindow(repo)
    window.refresh_profiles(profile.id)
    workspace = window._workspace(window.profile)
    editor = workspace.editor.open_file(translator)
    translator.write_text("external edit", encoding="utf-8")
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: QMessageBox.Ok)

    assert not window.update_context_from_translator(workspace)

    assert context.read_text(encoding="utf-8") == "old context"
    assert not list((folder / "Polish History").glob("ตรวจคำแปล บท *"))
    window.close()


def test_translator_external_change_during_confirmation_stops_update(tmp_path, monkeypatch):
    app()
    repo = ProjectRepository(tmp_path / "data")
    profile = NovelProfile()
    folder = repo.profile_dir(profile.id)
    translator = folder / "source" / "ABCTranslator.txt"
    context = tmp_path / "ABCContext.md"
    translator.parent.mkdir(parents=True)
    translator.write_text("Chapter 6\nold translator", encoding="utf-8")
    context.write_text("old context", encoding="utf-8")
    profile.context_path = str(context)
    profile.working_files = [StepFile(path=f"source/{translator.name}")]
    configure_translator_export_history(profile, folder, translator, context)
    repo.save_profile(profile)
    window = MainWindow(repo)
    window.refresh_profiles(profile.id)
    workspace = window._workspace(window.profile)
    workspace.editor.open_file(translator)

    def external_change(_self):
        translator.write_text("Chapter 6\nexternal translator", encoding="utf-8")
        return QMessageBox.Yes

    monkeypatch.setattr(QMessageBox, "exec", external_change)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: QMessageBox.Ok)

    assert not window.update_context_from_translator(workspace)

    assert context.read_text(encoding="utf-8") == "old context"
    assert not list((folder / "Polish History").glob("ตรวจคำแปล บท *"))
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
    translator.write_text("บทที่ 1\nnew context", encoding="utf-8")
    context.write_text("old context", encoding="utf-8")
    profile.context_path = str(context)
    profile.working_files = [StepFile(path=f"source/{translator.name}")]
    configure_translator_export_history(profile, folder, translator, context)
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
    assert not list((context.parent / ".palantir-recovery").glob("*.bak"))
    assert not list((folder / "Context Exports").glob("*.txt"))
    history = folder / "Polish History" / "ตรวจคำแปล บท 1"
    manifest = json.loads((history / "manifest.json").read_text(encoding="utf-8"))
    context_record = next(item for item in manifest["files"] if item["is_context"])
    assert (history / context_record["snapshot_path"]).read_bytes() == b"old context"
    window.close()


def test_display_normalization_only_context_does_not_block_export(tmp_path, monkeypatch):
    app()
    repo = ProjectRepository(tmp_path / "data")
    profile = NovelProfile()
    folder = repo.profile_dir(profile.id)
    translator = folder / "source" / "FATETranslator.txt"
    translator.parent.mkdir(parents=True)
    translator.write_text("บทที่ 6-10\nNew Context", encoding="utf-8")
    context = tmp_path / "FATEContext.md"
    old = b"Chapter 1-5\r\n\r\nold text  \r\n\r\n"
    context.write_bytes(old)
    profile.context_path = str(context)
    profile.working_files = [StepFile(path=f"source/{translator.name}")]
    configure_translator_export_history(profile, folder, translator, context)
    repo.save_profile(profile)
    window = MainWindow(repo); window.refresh_profiles(profile.id)
    workspace = window._workspace(window.profile)
    context_editor = workspace.editor.open_file(context)
    assert workspace.editor._dirty(context_editor)
    assert context_editor.property("normalizationPending")
    assert context_editor.property("displayNormalization")
    assert context_editor.toPlainText() == context_editor.property("documentSavedText")
    assert context.read_bytes() == old
    workspace.editor.open_file(translator)
    monkeypatch.setattr(QMessageBox, "exec", lambda *_: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *_: QMessageBox.Ok)
    assert window.update_context_from_translator(workspace)
    assert context.read_bytes() == translator.read_bytes()
    history = folder / "Polish History" / "ตรวจคำแปล บท 6-10"
    manifest = json.loads((history / "manifest.json").read_text(encoding="utf-8"))
    entry = next(item for item in manifest["files"] if item["is_context"])
    assert (history / entry["snapshot_path"]).read_bytes() == old
    assert manifest.get("capture_reason") == "translator_pre_export"
    window._close_export_reminder_accepted = True; window.close()


def test_review_copy_and_post_txt_export_keep_pre_export_context(tmp_path, monkeypatch):
    import time
    app()
    repo = ProjectRepository(tmp_path / "data")
    profile = NovelProfile()
    folder = repo.profile_dir(profile.id)
    translator = folder / "source" / "FATETranslator.txt"
    translator.parent.mkdir(parents=True)
    translator.write_text("บทที่ 6-10\nTranslation", encoding="utf-8")
    context = tmp_path / "FATEContext.md"
    old = b"Chapter 1-5\nold Context"
    context.write_bytes(old)
    profile.context_path = str(context)
    profile.working_files = [StepFile(path=f"source/{translator.name}")]
    configure_translator_export_history(profile, folder, translator, context)
    repo.save_profile(profile)
    window = MainWindow(repo); window.refresh_profiles(profile.id)
    workspace = window._workspace(window.profile)
    workspace.editor.open_file(translator)
    monkeypatch.setattr(QMessageBox, "exec", lambda *_: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *_: QMessageBox.Ok)
    assert window.update_context_from_translator(workspace)
    assert context.read_bytes() == translator.read_bytes()
    assert len(window.polish_history.list(window.profile)) == 1
    workspace.history_range.setText("6-10")
    workspace.step_selector.setCurrentIndex(
        workspace.step_selector.findData(window.profile.workflow.steps[1].id)
    )
    # Stage selection does not touch the clipboard. Explicit stage copy uses
    # current files, while a history-copy action returns the old Context.
    window.copy_step(advance=False)
    live_payloads = [Path(u.toLocalFile()) for u in QApplication.clipboard().mimeData().urls()]
    assert any(path.read_bytes() == context.read_bytes() for path in live_payloads)
    snapshot = window.polish_history.list(window.profile)[0]
    window.copy_history_snapshot(window.profile, snapshot)
    stop = time.monotonic() + 15
    while window.history_busy() and time.monotonic() < stop:
        QApplication.processEvents(); time.sleep(0.01)
    assert not window.history_busy()
    payloads = [Path(u.toLocalFile()) for u in QApplication.clipboard().mimeData().urls()]
    assert any(path.read_bytes() == old for path in payloads)
    assert len(window.polish_history.list(window.profile)) == 1
    window.snapshot_export_for_review(profile.id, "6-10")
    stop = time.monotonic() + 15
    while window.history_busy() and time.monotonic() < stop:
        QApplication.processEvents(); time.sleep(0.01)
    assert not window.history_busy()
    assert len(window.polish_history.list(window.profile)) == 1
    assert context.read_bytes() == translator.read_bytes()
    window._close_export_reminder_accepted = True; window.close()
