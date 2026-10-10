import os
from dataclasses import asdict
from pathlib import Path
import pytest
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from novel_workflow.models import AppSettings, NovelProfile
from novel_workflow.storage import ProjectRepository, write_json
from novel_workflow.workspace_editor import CodeEditor, EditorTabs, TxtExportTab


def app():
    return QApplication.instance() or QApplication([])


def panel(tmp_path, context_path_callback=None, **values):
    settings = AppSettings()
    settings.txt_export_directory = str(tmp_path)
    for key, value in values.items():
        setattr(settings, key, value)
    return TxtExportTab(settings, context_path_callback=context_path_callback)


def quiet_warning(monkeypatch):
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: QMessageBox.Ok)


def test_export_increments_then_wraps_end_to_start(tmp_path):
    app()
    export = panel(tmp_path, txt_export_filename="segverified", txt_export_start=1,
                   txt_export_end=2, txt_export_current=1)
    export.editor.setPlainText("text")

    assert export.export()
    assert (tmp_path / "segverified1.txt").read_text(encoding="utf-8") == "text"
    assert export.current.value() == 2
    assert export.export()
    assert (tmp_path / "segverified2.txt").exists()
    assert export.current.value() == 1


def test_submit_exports_only_and_preserves_context(tmp_path):
    app()
    context = tmp_path / "Context.md"
    context.write_text("old context", encoding="utf-8")
    text = "บทที่ 126\nสวัสดี 卡"
    export = panel(tmp_path, context_path_callback=lambda: context)
    export.editor.setPlainText(text)

    export.submit_button.click()

    assert (tmp_path / "segverified1.txt").read_text(encoding="utf-8") == text
    assert context.read_text(encoding="utf-8") == "old context"
    assert export.current.value() == 2


def test_submit_success_status_shows_exported_file_and_next_wrapped_number(tmp_path):
    app()
    context = tmp_path / "Context.md"
    context.write_text("old context", encoding="utf-8")
    messages = []
    export = panel(
        tmp_path, context_path_callback=lambda: context,
        txt_export_start=20, txt_export_end=80, txt_export_current=80,
    )
    export.status_callback = messages.append
    export.editor.setPlainText("เนื้อหา")

    export.submit_button.click()

    assert messages == ["ส่งออก segverified80.txt แล้ว"]


def test_submit_does_not_refresh_or_write_open_context_tab(tmp_path):
    app()
    context = tmp_path / "Context.md"
    context.write_text("old context", encoding="utf-8")
    tabs = EditorTabs(settings=AppSettings())
    context_editor = tabs.open_file(context)
    context_editor.setPlainText("stale unsaved edits")
    assert tabs.dirty_count() == 1

    export = panel(tmp_path, context_path_callback=lambda: context)
    export.context_saved_callback = lambda path, text: tabs.apply_external_update(path, text)
    export.editor.setPlainText("บทที่ 126\nเนื้อหาใหม่ 卡")
    export.submit_button.click()

    assert context.read_text(encoding="utf-8") == "old context"
    assert context_editor.toPlainText() == "stale unsaved edits"
    assert tabs.dirty_count() == 1


def test_editor_save_keeps_original_file_when_atomic_replace_fails(tmp_path, monkeypatch):
    app()
    import novel_workflow.workspace_editor as workspace_editor

    source = tmp_path / "Context.md"
    source.write_text("บันทึกเดิม 原文", encoding="utf-8")
    tabs = EditorTabs(settings=AppSettings())
    editor = tabs.open_file(source)
    editor.setPlainText("ฉบับแก้ไขใหม่ 新内容")

    def fail_replace(_source, _destination):
        raise PermissionError("ไฟล์ถูกล็อกโดยโปรแกรมอื่น")

    monkeypatch.setattr(workspace_editor.os, "replace", fail_replace)

    assert not tabs.save_editor(editor, quiet=True, autosave=True)
    assert source.read_text(encoding="utf-8") == "บันทึกเดิม 原文"
    assert tabs.dirty_count() == 1
    assert editor.property("saveState") == "บันทึกอัตโนมัติไม่สำเร็จ"
    assert editor.autosave_timer.isActive()
    assert list(tmp_path.glob(".Context.md.*.part")) == []


@pytest.mark.parametrize("appearance", ["Dark", "Light"])
def test_save_all_persists_open_utf8_files_in_every_appearance(tmp_path, appearance):
    app()
    source = tmp_path / "บทต้นฉบับ.txt"
    context = tmp_path / "Context.md"
    source.write_text("ต้นฉบับเดิม", encoding="utf-8")
    context.write_text("บทที่ 1\nข้อความเดิม", encoding="utf-8")
    tabs = EditorTabs(settings=AppSettings(), appearance=appearance)
    source_editor = tabs.open_file(source)
    context_editor = tabs.open_file(context)
    source_editor.setPlainText("ต้นฉบับแก้แล้ว 原文")
    context_editor.setPlainText("บทที่ 1\nContext แก้แล้ว 新内容")

    assert tabs.save_all()
    assert source.read_text(encoding="utf-8") == "ต้นฉบับแก้แล้ว 原文"
    assert context.read_text(encoding="utf-8") == "บทที่ 1\nContext แก้แล้ว 新内容"
    assert tabs.dirty_count() == 0


def test_submit_does_not_send_context_update_notification(tmp_path):
    app()
    context = tmp_path / "Context.md"
    context.write_text("old", encoding="utf-8")
    export = panel(tmp_path, context_path_callback=lambda: context)
    notices = []
    export.notification_callback = notices.append
    export.editor.setPlainText("new content")

    export.submit_button.click()

    assert notices == ["ส่งออก segverified1.txt แล้ว"]


def test_export_number_label_explains_next_file_number(tmp_path):
    app()
    export = panel(tmp_path)

    assert export.number_current_label.text() == "เลขถัดไป"


def test_submit_does_not_depend_on_context_path(tmp_path, monkeypatch):
    app()
    quiet_warning(monkeypatch)
    missing_context = tmp_path / "missing" / "Context.md"
    export = panel(tmp_path, context_path_callback=lambda: missing_context)
    text = "ข้อความยังอยู่"
    export.editor.setPlainText(text)

    export.submit_button.click()

    assert (tmp_path / "segverified1.txt").read_text(encoding="utf-8") == text
    assert export.current.value() == 2
    assert export.editor.toPlainText() == text


def test_legacy_export_keeps_overwrite_behavior_and_does_not_write_context(tmp_path, monkeypatch):
    app()
    quiet_warning(monkeypatch)

    context = tmp_path / "Context.md"
    context.write_text("old context", encoding="utf-8")
    target = tmp_path / "segverified1.txt"
    target.write_text("old export", encoding="utf-8")
    export = panel(tmp_path, context_path_callback=lambda: context)
    export.editor.setPlainText("new text")
    export.submit_button.click()

    assert target.read_text(encoding="utf-8") == "new text"
    assert context.read_text(encoding="utf-8") == "old context"
    assert export.current.value() == 2
    assert export.editor.toPlainText() == "new text"
    assert not list(tmp_path.glob("*.part"))


def test_custom_range_and_reset(tmp_path):
    app()
    export = panel(tmp_path, txt_export_start=20, txt_export_end=80, txt_export_current=57)
    export.reset_number()
    assert export.current.value() == 20
    export.current.setValue(80)
    assert export.export()
    assert export.current.value() == 20
    assert (tmp_path / "segverified80.txt").exists()


def test_overwrite_is_immediate_and_utf8_is_preserved(tmp_path):
    app()
    target = tmp_path / "segverified1.txt"
    target.write_text("old", encoding="utf-8")
    export = panel(tmp_path)
    text = "สวัสดี 卡 中文"
    export.editor.setPlainText(text)

    assert export.export()
    assert target.read_text(encoding="utf-8") == text


def test_failed_write_keeps_number_and_text(tmp_path, monkeypatch):
    app()
    quiet_warning(monkeypatch)
    export = panel(tmp_path / "missing")
    text = "keep me"
    export.editor.setPlainText(text)

    assert not export.export()
    assert export.current.value() == 1
    assert export.editor.toPlainText() == text


def test_filename_txt_extension_normalizes_and_invalid_windows_names_rejected(tmp_path, monkeypatch):
    app()
    export = panel(tmp_path, txt_export_filename="segverified.txt")
    assert export.export()
    assert (tmp_path / "segverified1.txt").exists()
    for invalid in ("a/b", "a\\b", "bad:name", "bad?.txt", "CON.txt"):
        try:
            TxtExportTab.normalized_filename(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted invalid Windows name: {invalid}")
    quiet_warning(monkeypatch)
    export.filename.setText("bad/name")
    assert not export.export()
    assert export.current.value() == 2


def test_export_settings_persist_across_repository_reload(tmp_path):
    app()
    repo = ProjectRepository(tmp_path / "data")
    settings = repo.load_settings()
    export = panel(tmp_path, txt_export_current=38)
    export.settings_callback = lambda: repo.save_settings(export.settings)
    export.filename.setText("chapter")
    export.start.setValue(20)
    export.end.setValue(80)
    export.current.setValue(38)
    export.directory.setText(str(tmp_path))

    restored = repo.load_settings()
    assert restored.txt_export_filename == "chapter"
    assert restored.txt_export_directory == str(tmp_path)
    assert (restored.txt_export_start, restored.txt_export_end, restored.txt_export_current) == (20, 80, 38)


def test_export_settings_are_independent_per_novel_and_persist(tmp_path):
    app()
    repo = ProjectRepository(tmp_path / "data")
    first_profile = NovelProfile(name="First")
    second_profile = NovelProfile(name="Second")
    repo.save_profile(first_profile)
    repo.save_profile(second_profile)
    first = TxtExportTab(first_profile.txt_export_settings)
    second = TxtExportTab(second_profile.txt_export_settings)
    first.settings_callback = lambda: repo.save_profile(first_profile)
    first.filename.setText("first.txt")
    first.current.setValue(38)

    restored = {p.name: p for p in repo.list_profiles()}
    assert restored["First"].txt_export_settings.filename == "first.txt"
    assert restored["First"].txt_export_settings.current == 38
    assert restored["Second"].txt_export_settings.filename == "segverified"
    assert restored["Second"].txt_export_settings.current == 1
    assert second.filename.text() == "segverified"


def test_legacy_app_export_settings_migrate_to_existing_profiles_once(tmp_path):
    repo = ProjectRepository(tmp_path / "data")
    profile = NovelProfile(name="Legacy", schema_version=4)
    profile_data = asdict(profile)
    profile_data.pop("txt_export_settings", None)
    repo.profiles_dir.joinpath(profile.id).mkdir(parents=True)
    write_json(repo.profiles_dir / profile.id / "profile.json", profile_data)
    legacy = repo.load_settings()
    legacy.txt_export_filename = "old-prefix"
    legacy.txt_export_directory = str(tmp_path)
    legacy.txt_export_start = 20
    legacy.txt_export_end = 80
    legacy.txt_export_current = 38
    repo.save_settings(legacy)

    migrated = repo.list_profiles()[0]
    assert migrated.txt_export_settings.filename == "old-prefix"
    assert migrated.txt_export_settings.directory == str(tmp_path)
    assert (migrated.txt_export_settings.start, migrated.txt_export_settings.end,
            migrated.txt_export_settings.current) == (20, 80, 38)
    created_later = NovelProfile(name="New")
    repo.save_profile(created_later)
    assert repo.list_profiles()[1].txt_export_settings.filename == "segverified"


def test_copy_and_copy_export_and_word_character_counts(tmp_path):
    qapp = app()
    export = panel(tmp_path)
    export.editor.setPlainText("ไทย 卡 one two")
    QTest.qWait(350)
    assert export.word_count.text() == "4 คำ"
    assert export.character_count.text() == "13 อักขระ"

    export.copy_button.click()
    assert qapp.clipboard().text() == "ไทย 卡 one two"
    assert export.current.value() == 1
    export.copy_export_button.click()
    assert qapp.clipboard().text() == "ไทย 卡 one two"
    assert (tmp_path / "segverified1.txt").read_text(encoding="utf-8") == "ไทย 卡 one two"
    assert export.current.value() == 2


def test_export_tab_is_permanent_and_not_a_disk_editor_file(tmp_path):
    qapp = app()
    settings = AppSettings()
    tabs = EditorTabs(settings=settings)
    tabs.close_tab(0)
    assert tabs.tabs.count() == 1
    assert tabs.tabs.tabText(0) == "TXT Export"
    assert tabs.open_paths() == []
    path = tmp_path / "ordinary.txt"
    path.write_text("file", encoding="utf-8")
    tabs.open_file(path)
    assert tabs.tabs.count() == 2
    assert tabs.open_paths() == [str(path.resolve())]
    assert tabs.tabs.tabText(tabs.tabs.count()-1) == "TXT Export"


def test_submit_is_single_export_and_context_action(tmp_path):
    app()
    context = tmp_path / "Context.md"
    context.write_text("old", encoding="utf-8")
    export = panel(tmp_path, context_path_callback=lambda: context)
    export.editor.setPlainText("new")

    assert export.submit_button.text() == "Submit"
    assert not hasattr(export, "export_button")
    assert not hasattr(export, "export_context_button")
    export.submit_button.click()

    assert (tmp_path / "segverified1.txt").read_text(encoding="utf-8") == "new"
    assert context.read_text(encoding="utf-8") == "old"
    assert export.current.value() == 2


def test_txt_export_tab_order_persists_after_reopening(tmp_path):
    app()
    first_path = tmp_path / "first.txt"
    second_path = tmp_path / "second.txt"
    first_path.write_text("one", encoding="utf-8")
    second_path.write_text("two", encoding="utf-8")
    original = EditorTabs(settings=AppSettings())
    original.open_file(first_path)
    original.open_file(second_path)
    original.tabs.tabBar().moveTab(0, 2)
    original.tabs.setCurrentIndex(2)

    order = original.tab_order()
    repo = ProjectRepository(tmp_path / "data")
    saved = repo.load_settings()
    saved.editor_tab_order["profile"] = order
    saved.editor_active_tab_keys["profile"] = original.active_tab_key()
    repo.save_settings(saved)
    reloaded = repo.load_settings()
    restored = EditorTabs(settings=AppSettings())
    restored.restore_paths(
        original.open_paths(), tab_order=reloaded.editor_tab_order["profile"],
        active_tab_key=reloaded.editor_active_tab_keys["profile"],
    )

    assert [restored.tabs.tabText(i) for i in range(restored.tabs.count())] == [
        "second.txt", "first.txt", "TXT Export",
    ]
    assert restored.active_tab_key() == "txt-export"
    restored.close_tab(restored.tabs.indexOf(restored.export_tab))
    assert restored.tabs.indexOf(restored.export_tab) == 2


def test_editor_font_uses_single_primary_family_and_default_hinting():
    app()
    editor = CodeEditor()
    assert len(editor.font().families()) == 1
    assert editor.font().hintingPreference() == editor.font().HintingPreference.PreferDefaultHinting


def test_split_export_creates_one_utf8_file_for_each_chapter(tmp_path, monkeypatch):
    app()
    export = panel(tmp_path)
    export.mode.setCurrentIndex(1)
    export.editor.setPlainText(
        "บทที่ 410 งั้นก็กลับไปดื่มที่โรงแรม\nเนื้อหา 410\n[จบตอน]\n"
        "บทที่ 412 วิลล่าหลังนี้ขายไหม?\nเนื้อหา 412\n[จบตอน]"
    )

    assert export.export()

    assert sorted(path.name for path in tmp_path.glob("*.txt")) == [
        "บทที่ 410 งั้นก็กลับไปดื่มที่โรงแรม.txt",
        "บทที่ 412 วิลล่าหลังนี้ขายไหม？.txt",
    ]
    assert (tmp_path / "บทที่ 410 งั้นก็กลับไปดื่มที่โรงแรม.txt").read_text(encoding="utf-8") == (
        "บทที่ 410 งั้นก็กลับไปดื่มที่โรงแรม\nเนื้อหา 410\n[จบตอน]\n"
    )
    assert (tmp_path / "บทที่ 412 วิลล่าหลังนี้ขายไหม？.txt").read_text(encoding="utf-8") == (
        "บทที่ 412 วิลล่าหลังนี้ขายไหม?\nเนื้อหา 412\n[จบตอน]"
    )


def test_submit_exports_without_updating_context(tmp_path):
    app()
    context = tmp_path / "Context.md"
    context.write_text("old context", encoding="utf-8")
    export = panel(tmp_path, context_path_callback=lambda: context)
    export.editor.setPlainText("new text")

    export.submit_button.click()

    assert context.read_text(encoding="utf-8") == "old context"


def test_split_export_refuses_case_insensitive_existing_filename(tmp_path, monkeypatch):
    app()
    quiet_warning(monkeypatch)
    export = panel(tmp_path)
    export.mode.setCurrentIndex(1)
    export.editor.setPlainText("บทที่ 1 Title\nnew")
    existing = tmp_path / "บทที่ 1 title.TXT"
    existing.write_text("user data", encoding="utf-8")

    assert not export.export()

    assert existing.read_text(encoding="utf-8") == "user data"
    assert len(list(tmp_path.glob("*.txt"))) == 1


def test_split_export_rolls_back_files_when_second_publish_fails(tmp_path, monkeypatch):
    app()
    quiet_warning(monkeypatch)
    import novel_workflow.workspace_editor as workspace_editor
    export = panel(tmp_path)
    export.mode.setCurrentIndex(1)
    export.editor.setPlainText("บทที่ 1 First\none\nบทที่ 2 Second\ntwo")
    original = workspace_editor.os.link
    calls = 0

    def fail_second(source, destination, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated batch failure")
        return original(source, destination, *args, **kwargs)

    monkeypatch.setattr(workspace_editor.os, "link", fail_second)

    assert not export.export()

    assert not list(tmp_path.glob("*.txt"))
    assert export.current.value() == 1
    assert not list(tmp_path.glob(".palantir-staging-*"))


def test_split_export_does_not_replace_file_created_after_preview(tmp_path, monkeypatch):
    app()
    quiet_warning(monkeypatch)
    import novel_workflow.workspace_editor as workspace_editor
    export = panel(tmp_path)
    export.mode.setCurrentIndex(1)
    export.editor.setPlainText("บทที่ 1 First\none\nบทที่ 2 Second\ntwo")
    original = workspace_editor.os.link
    calls = 0

    def create_collision_then_link(source, destination, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            Path(destination).write_text("user file", encoding="utf-8")
        return original(source, destination, *args, **kwargs)

    monkeypatch.setattr(workspace_editor.os, "link", create_collision_then_link)

    assert not export.export()

    assert not (tmp_path / "บทที่ 1 First.txt").exists()
    assert (tmp_path / "บทที่ 2 Second.txt").read_text(encoding="utf-8") == "user file"


def test_split_metadata_failure_rolls_back_batch_without_verified_count(tmp_path, monkeypatch):
    app()
    quiet_warning(monkeypatch)
    repo = ProjectRepository(tmp_path / "data")
    profile = NovelProfile()
    profile.txt_export_settings.directory = str(tmp_path)
    profile.txt_export_settings.mode = "split"
    repo.save_profile(profile)
    from novel_workflow.export_service import ExportService
    service = ExportService(repo, profile.id)
    export = TxtExportTab(profile.txt_export_settings, export_service=service)
    export.editor.setPlainText("บทที่ 1 First\none\nบทที่ 2 Second\ntwo")
    monkeypatch.setattr(service, "commit_batch", lambda _exports: (_ for _ in ()).throw(OSError("profile save failed")))

    assert not export.export()

    assert not list(tmp_path.glob("*.txt"))
    saved = repo.list_profiles()[0]
    assert saved.verified_goal_count == 0
    assert saved.verified_export_history == []
    assert saved.txt_export_settings.current == 1


def test_split_export_records_one_verified_event_per_file(tmp_path):
    app()
    repo = ProjectRepository(tmp_path / "data")
    profile = NovelProfile()
    profile.txt_export_settings.directory = str(tmp_path)
    profile.txt_export_settings.mode = "split"
    repo.save_profile(profile)
    from novel_workflow.export_service import ExportService
    service = ExportService(repo, profile.id)
    export = TxtExportTab(profile.txt_export_settings, export_service=service)
    export.editor.setPlainText("บทที่ 1 First\none\nบทที่ 3 Third\nthree")

    assert export.export()

    latest = repo.list_profiles()[0]
    assert latest.verified_goal_count == 2
    assert [item["sequence"] for item in latest.verified_export_history] == [1, 3]
    assert latest.txt_export_settings.current == 1


def test_split_chapter_parser_keeps_whitespace_and_ignores_inline_chapter_text():
    raw = "บทที่ 1 First\n \t\nมีคำว่า บทที่ 2 อยู่กลางย่อหน้า\n[จบตอน]\nบทที่ 7 Last\n終わり"

    chapters = TxtExportTab.split_chapters(raw)

    assert len(chapters) == 2
    assert chapters[0][2] == "บทที่ 1 First\n \t\nมีคำว่า บทที่ 2 อยู่กลางย่อหน้า\n[จบตอน]\n"
    assert chapters[1][2] == "บทที่ 7 Last\n終わり"


def test_split_chapter_parser_rejects_duplicate_chapter_number():
    with pytest.raises(ValueError, match="เลขบทซ้ำ"):
        TxtExportTab.split_chapters("บทที่ 1 First\none\nบทที่ 1 Again\ntwo")


def test_split_submit_preview_lists_files_and_requires_confirmation(tmp_path, monkeypatch):
    app()
    export = panel(tmp_path)
    export.mode.setCurrentIndex(1)
    export.editor.setPlainText("บทที่ 1 First\none\nบทที่ 3 Third\nthree")
    prompts = []
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *_args: prompts.append(_args[2]) or QMessageBox.No,
    )

    export.submit_button.click()

    assert len(prompts) == 1
    assert "ตรวจพบบท 2 บท" in prompts[0]
    assert "บทที่ 1 First.txt" in prompts[0]
    assert "บทที่ 3 Third.txt" in prompts[0]
    assert not list(tmp_path.glob("*.txt"))


def test_old_profile_export_settings_default_to_legacy_mode():
    from novel_workflow.models import TxtExportSettings

    assert TxtExportSettings.from_dict({}).mode == "legacy"
