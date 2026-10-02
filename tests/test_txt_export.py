import os
from dataclasses import asdict
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


def test_export_overwrites_context_and_increments_only_after_both_writes(tmp_path):
    app()
    context = tmp_path / "Context.md"
    context.write_text("old context", encoding="utf-8")
    text = "บทที่ 126\nสวัสดี 卡"
    export = panel(tmp_path, context_path_callback=lambda: context)
    export.editor.setPlainText(text)

    export.submit_button.click()

    assert (tmp_path / "segverified1.txt").read_text(encoding="utf-8") == text
    assert context.read_text(encoding="utf-8") == text
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

    assert messages == ["ส่งออก segverified80.txt และอัปเดต Context แล้ว · เลขถัดไป 20"]


def test_context_write_failure_keeps_number_and_export_text(tmp_path, monkeypatch):
    app()
    quiet_warning(monkeypatch)
    missing_context = tmp_path / "missing" / "Context.md"
    export = panel(tmp_path, context_path_callback=lambda: missing_context)
    text = "ข้อความยังอยู่"
    export.editor.setPlainText(text)

    export.submit_button.click()

    assert not (tmp_path / "segverified1.txt").exists()
    assert export.current.value() == 1
    assert export.editor.toPlainText() == text


def test_context_staging_failure_leaves_existing_files_unchanged(tmp_path, monkeypatch):
    app()
    quiet_warning(monkeypatch)
    import novel_workflow.workspace_editor as workspace_editor

    context = tmp_path / "Context.md"
    context.write_text("old context", encoding="utf-8")
    target = tmp_path / "segverified1.txt"
    target.write_text("old export", encoding="utf-8")
    export = panel(tmp_path, context_path_callback=lambda: context)
    export.editor.setPlainText("new text")
    stage = workspace_editor._stage_text_file

    def fail_context_stage(destination, text):
        if destination == context:
            raise OSError("simulated context write failure")
        return stage(destination, text)

    monkeypatch.setattr(workspace_editor, "_stage_text_file", fail_context_stage)
    export.submit_button.click()

    assert target.read_text(encoding="utf-8") == "old export"
    assert context.read_text(encoding="utf-8") == "old context"
    assert export.current.value() == 1
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
    assert tabs.tabs.tabText(0) == "TXT Export"


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
    assert context.read_text(encoding="utf-8") == "new"
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
        "first.txt", "second.txt", "TXT Export",
    ]
    assert restored.active_tab_key() == "txt-export"
    restored.close_tab(restored.tabs.indexOf(restored.export_tab))
    assert restored.tabs.indexOf(restored.export_tab) == 2


def test_editor_font_uses_single_primary_family_and_default_hinting():
    app()
    editor = CodeEditor()
    assert len(editor.font().families()) == 1
    assert editor.font().hintingPreference() == editor.font().HintingPreference.PreferDefaultHinting
