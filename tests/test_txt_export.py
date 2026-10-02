import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from novel_workflow.models import AppSettings
from novel_workflow.storage import ProjectRepository
from novel_workflow.workspace_editor import CodeEditor, EditorTabs, TxtExportTab


def app():
    return QApplication.instance() or QApplication([])


def panel(tmp_path, **values):
    settings = AppSettings()
    settings.txt_export_directory = str(tmp_path)
    for key, value in values.items():
        setattr(settings, key, value)
    return TxtExportTab(settings)


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


def test_app_level_export_settings_sync_across_novel_workspaces(tmp_path):
    app()
    settings = AppSettings()
    first = TxtExportTab(settings)
    second = TxtExportTab(settings)
    first.filename.setText("shared-prefix.txt")
    first.start.setValue(20)
    first.end.setValue(80)
    first.current.setValue(38)

    assert second.filename.text() == "shared-prefix.txt"
    assert (second.start.value(), second.end.value(), second.current.value()) == (20, 80, 38)


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


def test_editor_font_uses_single_primary_family_and_default_hinting():
    app()
    editor = CodeEditor()
    assert len(editor.font().families()) == 1
    assert editor.font().hintingPreference() == editor.font().HintingPreference.PreferDefaultHinting
